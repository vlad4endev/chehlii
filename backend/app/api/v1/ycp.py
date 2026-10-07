"""YCP (Yandex Commerce Protocol): API магазина, которое вызывает Яндекс.

В ЛК YCP поле «URL для API» — база, к которой кабинет дописывает `/api/v1/...`.
Подходят и `{сайт}/ycp/`, и корень сайта: оба адреса переписываются на `/api/v1/ycp/...`.
Токен доступа — из «Настройки → Интеграции → YCP».
Фид для Яндекс Товаров — `{публичный адрес}/ycp/feed.yml`, без Bearer.
Ошибки — всегда `{"error": "..."}` (формат спеки).
Оплату и доставку до покупателя ведёт Яндекс; мы отдаём каталог/цены/остатки, создаём заказ
на `/checkout` и проводим оплату на `/checkout/placed` (дальше заказ как обычный
PREPAYMENT_PAID: списание остатка, виден в AdminUI). Подробности модели — services/ycp.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.orders import _record_status
from app.core.database import get_session
from app.enums import CaseBranch, Channel, OrderStatus, PaymentKind, PaymentStatus
from app.models.catalog import CaseType, CaseTypeModel
from app.models.client import Client
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.services import integrations, pricing, stock, ycp

GATEWAY = Channel.YCP

Session = Annotated[AsyncSession, Depends(get_session)]


class YcpError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        self.status, self.message, self.extra = status, message, extra


class YcpRoute(APIRoute):
    """Ошибки и невалидный вход — в формате YCP (`{"error"}`, 400), а не FastAPI `detail`."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except YcpError as e:
                return JSONResponse({"error": e.message, **e.extra}, status_code=e.status)
            except RequestValidationError:
                return JSONResponse({"error": "invalid request"}, status_code=400)

        return handler


async def require_token(request: Request, session: Session) -> None:
    enabled = await integrations.get(session, ycp.ENABLED_KEY)
    if not ycp.enabled_flag(enabled):
        raise YcpError(503, "ycp disabled")
    expected = await integrations.get(session, ycp.TOKEN_KEY)
    if not ycp.token_ok(expected, request.headers.get("authorization")):
        raise YcpError(401, "unauthorized")


router = APIRouter(route_class=YcpRoute, dependencies=[Depends(require_token)])


# ---------- схемы запросов (только нужные нам поля; лишнее Яндекс может добавлять) ----------


class _Item(BaseModel):
    id: str
    quantity: int


class BasketCheckIn(BaseModel):
    items: list[_Item]


class _CheckoutItem(_Item):
    regular_price: float
    final_price: float


class CheckoutIn(BaseModel):
    session_id: str
    items: list[_CheckoutItem]
    customer: dict
    delivery: dict


class DeliveryOptionsIn(BaseModel):
    items: list[_Item]
    delivery_target: dict


# ---------- помощники ----------


async def _params(request: Request) -> dict:
    """Параметры метода: в спеке `session_id`/`order_id` описаны и в query, и в теле — берём оба."""
    data: dict = dict(request.query_params)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        data.update(body)
    return data


async def _offers(
    session: AsyncSession, raw_ids: list[str]
) -> dict[int, tuple[CaseTypeModel, CaseType]]:
    """Оффер = (тип без кастома × модель) активный и доступный. Прочие ID молча выпадают."""
    ids = [int(i) for i in raw_ids if i.isdigit()]
    if not ids:
        return {}
    rows = await session.execute(
        select(CaseTypeModel, CaseType)
        .join(CaseType, CaseType.id == CaseTypeModel.case_type_id)
        .where(
            CaseTypeModel.id.in_(ids),
            CaseTypeModel.is_available.is_(True),
            CaseType.is_active.is_(True),
            CaseType.is_custom.is_(False),
        )
    )
    return {m.id: (m, ct) for m, ct in rows.all()}


def _available(model: CaseTypeModel) -> int:
    return max(0, min(model.stock, ycp.MAX_QTY))


def _warehouses(model: CaseTypeModel) -> list[dict]:
    return [{"id": ycp.WAREHOUSE_ID, "available_quantity": _available(model)}]


def _basket_item(model: CaseTypeModel, ct: CaseType) -> dict:
    price = ycp.rub(ct.client_price)
    item: dict[str, Any] = {
        "id": str(model.id),
        "name": f"{ct.name} для {model.model_name}",
        "regular_price": price,
        "final_price": price,
        "warehouses": _warehouses(model),
        "dimensions": ycp.DIMENSIONS,
        "characteristics": [
            {
                "display_type": "text",
                "code": "MODEL",
                "name": "Модель",
                "properties": {"value": model.model_name},
            }
        ],
        "variations": [],
    }
    img = model.photo_url or ct.photo_url
    if img and img.startswith("http"):
        item["img"] = img
    return item


async def _delivery_cost(session: AsyncSession) -> float:
    return float(await integrations.get(session, "ycp.delivery_cost", "300") or 300)


async def _payment_by_session(session: AsyncSession, session_id: str) -> Payment | None:
    return await session.scalar(
        select(Payment).where(Payment.idempotency_key == f"{GATEWAY}:{session_id}")
    )


async def _payment_by_ycp_order(session: AsyncSession, ycp_order_id: str) -> Payment:
    payment = await session.scalar(
        select(Payment).where(Payment.gateway == GATEWAY, Payment.external_id == ycp_order_id)
    )
    if payment is None:
        raise YcpError(404, "order not found")
    return payment


def _required(params: dict, key: str) -> str:
    value = str(params.get(key) or "")
    if not value:
        raise YcpError(400, f"{key} is required")
    return value


# ---------- фид (публичный: его забирает Яндекс Товары, не кабинет YCP) ----------

feed_router = APIRouter()


@feed_router.get("/feed.yml")
async def yml_feed(session: Session) -> Response:
    """YML некастомных чехлов. Кнопка «Купить» — только у позиций в наличии и при включённом YCP."""
    public_base = await integrations.get(session, ycp.PUBLIC_BASE_KEY) or ""
    shop_url = (await integrations.get(session, ycp.SHOP_URL_KEY) or "").strip()
    shop_url = shop_url or public_base.strip()
    checkout_on = ycp.enabled_flag(await integrations.get(session, ycp.ENABLED_KEY))
    rows = await session.execute(
        select(CaseTypeModel, CaseType)
        .join(CaseType, CaseType.id == CaseTypeModel.case_type_id)
        .where(
            CaseTypeModel.is_available.is_(True),
            CaseType.is_active.is_(True),
            CaseType.is_custom.is_(False),
        )
        .order_by(CaseType.id, CaseTypeModel.id)
    )
    categories: dict[int, ycp.FeedCategory] = {}
    offers: list[ycp.FeedOffer] = []
    for model, ct in rows.all():
        categories.setdefault(ct.id, ycp.FeedCategory(str(ct.id), ct.name))
        in_stock = model.stock > 0
        picture = ycp.absolute_url(model.photo_url or ct.photo_url, public_base)
        offers.append(
            ycp.FeedOffer(
                offer_id=str(model.id),
                name=f"{ct.name} для {model.model_name}",
                price=ycp.rub(ct.client_price),
                category_id=str(ct.id),
                available=in_stock,
                checkout=checkout_on and in_stock,
                picture=picture,
                description=(ct.description or "").strip() or None,
                url=shop_url or None,
            )
        )
    xml = ycp.yml_catalog(
        shop_name=ycp.SHOP_NAME,
        shop_url=shop_url or public_base,
        categories=list(categories.values()),
        offers=offers,
        when=datetime.now(UTC),
    )
    return Response(content=xml, media_type="application/xml")


# ---------- методы YCP ----------


@router.get("/health")
async def health() -> dict:
    """Корень `{URL для API}`: кабинет иногда проверяет саму базу, не только склады."""
    return {"status": "ok"}


@router.get("/warehouses")
async def warehouses(session: Session, limit: int = 1000, offset: int = 0) -> dict:
    address = (await integrations.get(session, "ycp.warehouse_address") or "").strip()
    phone = ycp.cabinet_phone(
        await integrations.get(session, "ycp.warehouse_phone")
        or await integrations.get(session, "cdek.sender_phone")
    )
    rows = [
        {
            "id": ycp.WAREHOUSE_ID,
            "title": "Склад casetop",
            "address": address,
            "phone": phone,
            "description": "Склад casetop",
            "self_pickup_options": {"enabled": False},
            # Поле не передаём: по спеке это значит, что доставка YCP для склада включена.
            # `enabled: false` кабинет читает как «доставлять неоткуда» и не сохраняет связь.
        }
    ]
    return {"warehouses": rows[offset : offset + limit], "total_count": len(rows)}


@router.post("/checkout/basket/check")
async def basket_check(body: BasketCheckIn, session: Session) -> dict:
    offers = await _offers(session, [i.id for i in body.items])
    return {"items": [_basket_item(m, ct) for m, ct in offers.values()]}


@router.get("/checkout/delivery/pickup_points")
async def pickup_points(limit: int = 1000, offset: int = 0) -> dict:
    return {"pickup_points": [], "total_count": 0}  # только курьер


@router.post("/checkout/delivery/options")
async def delivery_options(body: DeliveryOptionsIn, session: Session) -> dict:
    if body.delivery_target.get("delivery_method") != "courier":
        return {"delivery_options": []}
    days = int(await integrations.get(session, "ycp.delivery_days", "5") or 5)
    return {
        "delivery_options": [
            {
                "id": "flat",
                "cost": await _delivery_cost(session),
                "delivery_date_interval": ycp.delivery_interval(date.today(), days),
            }
        ]
    }


@router.post("/checkout", status_code=201)
async def checkout(body: CheckoutIn, session: Session) -> dict:
    """Сессия оформления: сверяем цены/остаток, заводим клиента, заказ и ожидающий платёж."""
    if (existing := await _payment_by_session(session, body.session_id)) is not None:
        return {"order_number": str(existing.order_id)}  # ретрай Яндекса

    if sum(i.quantity for i in body.items) != 1 or len(body.items) != 1:
        raise YcpError(400, "only a single case per order is supported")
    asked = body.items[0]
    offers = await _offers(session, [asked.id])
    found = offers.get(int(asked.id)) if asked.id.isdigit() else None
    if found is None:
        raise YcpError(404, "item not found")
    model, ct = found
    price = ycp.rub(ct.client_price)
    if _available(model) < 1 or asked.regular_price != price or asked.final_price != price:
        raise YcpError(
            409,
            "price or stock changed",
            actual_inventory={
                "items": [
                    {
                        "id": str(model.id),
                        "regular_price": price,
                        "final_price": price,
                        "warehouses": _warehouses(model),
                    }
                ]
            },
            checkout_canceled=False,
        )
    if body.delivery.get("delivery_method") != "courier":
        raise YcpError(400, "only courier delivery is supported")

    phone = str(body.customer.get("phone") or "")
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        raise YcpError(400, "customer phone is required")
    client = await session.scalar(
        select(Client).where(Client.channel == GATEWAY, Client.channel_user_id == digits)
    )
    if client is None:
        client = Client(
            channel=GATEWAY,
            channel_user_id=digits,
            phone=phone,
            nickname=str(body.customer.get("full_name") or "")[:255] or None,
            date_start=datetime.now(UTC),
        )
        session.add(client)
        await session.flush()
    elif client.deleted_at is not None:
        client.deleted_at = None
        if phone:
            client.phone = phone
        name = str(body.customer.get("full_name") or "")[:255] or None
        if name:
            client.nickname = name

    addr = body.delivery.get("address") or {}
    parts = [addr.get("locality"), addr.get("address")]
    if addr.get("apartment"):
        parts.append(f"кв. {addr['apartment']}")
    delivery_cost = float(body.delivery.get("price") or 0)
    breakdown = pricing.compute(ct.cost, ct.margin, 0, delivery_cost)
    order = Order(
        client_id=client.id,
        case_type_id=ct.id,
        branch=CaseBranch.STANDARD,
        model_name=model.model_name,
        status=OrderStatus.CASE_CONFIRMED,
        cost=ct.cost,
        margin=ct.margin,
        total_discount=0,
        delivery_cost=delivery_cost,
        final_price=breakdown.final_price,
        delivery_address=", ".join(str(p) for p in parts if p) or None,
        payment_status=PaymentStatus.PENDING,
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=OrderStatus.CASE_CONFIRMED,
            changed_by="system",
            trigger="ycp: сессия оформления",
            created_at=datetime.now(UTC),
        )
    )
    session.add(
        Payment(
            order_id=order.id,
            kind=PaymentKind.PREPAYMENT,
            gateway=GATEWAY,
            amount=breakdown.final_price,
            status=PaymentStatus.PENDING,
            idempotency_key=f"{GATEWAY}:{body.session_id}",
            # Покупатель, адрес и заметки — для менеджера (в модели заказа под них нет колонок).
            raw_webhook={"customer": body.customer, "delivery": body.delivery},
        )
    )
    await session.commit()
    return {"order_number": str(order.id)}


@router.post("/checkout/placed")
async def checkout_placed(request: Request, session: Session) -> dict:
    params = await _params(request)
    payment = await _payment_by_session(session, _required(params, "session_id"))
    if payment is None:
        raise YcpError(404, "session not found")
    if payment.status == PaymentStatus.CANCELLED:
        raise YcpError(409, "session was cancelled")
    payment.external_id = _required(params, "order_id")
    if params.get("payment_method") == "online" and payment.status != PaymentStatus.PAID:
        payment.status = PaymentStatus.PAID
        payment.paid_at = datetime.now(UTC)
        payment.raw_webhook = {**(payment.raw_webhook or {}), "placed": params}
        order = await session.get(Order, payment.order_id)
        order.payment_status = PaymentStatus.PAID
        await _record_status(session, order, OrderStatus.PREPAYMENT_PAID, "ycp: оплата в Яндексе")
        await stock.deduct_for_order(session, order)
    # ponytail: on_delivery лишь фиксируем (заказ остаётся неоплаченным), разбирать при включении.
    await session.commit()
    return {}


@router.post("/checkout/cancel")
async def checkout_cancel(request: Request, session: Session) -> dict:
    params = await _params(request)
    payment = await _payment_by_session(session, _required(params, "session_id"))
    if payment is None:
        raise YcpError(404, "session not found")
    if payment.status == PaymentStatus.PAID:
        raise YcpError(409, "order already placed")
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
        order = await session.get(Order, payment.order_id)
        await _record_status(session, order, OrderStatus.CANCELLED, "ycp: сессия отменена")
        await session.commit()
    return {}


@router.post("/order/cancel")
async def order_cancel(request: Request, session: Session) -> dict:
    payment = await _payment_by_ycp_order(session, _required(await _params(request), "order_id"))
    order = await session.get(Order, payment.order_id)
    if order.status != OrderStatus.CANCELLED:
        await _record_status(session, order, OrderStatus.CANCELLED, "ycp: отмена заказа")
        await stock.restore_for_order(session, order)
        # Возврат денег покупателю делает Яндекс; статус платежа у нас не трогаем.
        await session.commit()
    return {}


@router.post("/order/delivered")
async def order_delivered(request: Request, session: Session) -> dict:
    payment = await _payment_by_ycp_order(session, _required(await _params(request), "order_id"))
    order = await session.get(Order, payment.order_id)
    if order.status == OrderStatus.CANCELLED:
        raise YcpError(409, "order is cancelled")
    if order.status != OrderStatus.DELIVERED:
        await _record_status(session, order, OrderStatus.DELIVERED, "ycp: доставлен")
        await session.commit()
    return {}


@router.get("/order")
async def order_info(request: Request, session: Session) -> dict:
    payment = await _payment_by_ycp_order(session, _required(await _params(request), "order_id"))
    order = await session.get(Order, payment.order_id)
    model = await session.scalar(
        select(CaseTypeModel).where(
            CaseTypeModel.case_type_id == order.case_type_id,
            CaseTypeModel.model_name == order.model_name,
        )
    )
    history = await session.scalars(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order.id)
        .order_by(OrderStatusHistory.id)
    )
    statuses = [
        {
            "status": ycp.delivery_status(h.status),
            "timestamp": int(h.created_at.timestamp()),
        }
        for h in history
    ]
    cancelled = order.status == OrderStatus.CANCELLED
    return {
        "items": [
            {
                "id": str(model.id) if model else "",
                "quantity": 1,
                "refused_count": 1 if cancelled else 0,
            }
        ],
        "delivery_statuses": statuses,
    }
