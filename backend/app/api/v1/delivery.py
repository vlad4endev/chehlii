"""Доставка: СДЭК и Яндекс Доставка.

СДЭК: расчёт стоимости, создание заявки, вебхук статуса ORDER_STATUS.
Яндекс: ПВЗ, варианты доставки (offers/create) и бронь (offers/confirm). У служб
разный набор входных данных, поэтому у Яндекса свои маршруты `/yandex/*`, а не
общий эндпоинт с опциональными полями.

Креды и параметры отправителя — из «Настройки → Интеграции».
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal import require_internal
from app.core.database import get_session
from app.enums import OrderStatus
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import cdek, integrations, pricing, yandex_delivery

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Коды статусов СДЭК → статус заказа.
_DELIVERED = {"DELIVERED"}
_SHIPPED = {
    "RECEIVED_AT_SHIPMENT_WAREHOUSE",
    "ACCEPTED_AT_PICK_UP_POINT",
    "IN_TRANSIT",
    "ACCEPTED_AT_TRANSIT_WAREHOUSE",
    "RECEIVED_AT_TRANSIT_WAREHOUSE",
}

# Значения настроек-флагов, которые считаем «да».
_TRUE = ("1", "true", "yes", "да")


async def _advance(session: AsyncSession, order: Order, new: OrderStatus, trigger: str) -> bool:
    """Перевести заказ в статус доставки и уведомить клиента. Идемпотентно.

    Общая точка для вебхука СДЭК и опроса Яндекса: у служб разные коды, но одни
    последствия — история статусов и сообщение клиенту.
    """
    if order.status == new:
        return False
    # Опрос может вернуть промежуточный статус после выдачи — назад не откатываем.
    if new == OrderStatus.SHIPPED and order.status == OrderStatus.DELIVERED:
        return False
    order.status = new
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=new,
            changed_by="system",
            trigger=trigger,
            created_at=datetime.now(UTC),
        )
    )
    client = await session.get(Client, order.client_id)
    if client is not None:
        txt = "Заказ доставлен ✅" if new == OrderStatus.DELIVERED else "Заказ отправлен 🚚"
        session.add(
            OutboundMessage(
                client_id=client.id,
                channel=client.channel,
                channel_user_id=client.channel_user_id,
                order_id=order.id,
                kind="text",
                text=f"{txt} #{order.id}",
            )
        )
    await session.commit()
    return True


def _int(value: str | None, default: int) -> int:
    """Числовая настройка из админки: пустое или мусор → default, без падения."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


async def _cfg(session: AsyncSession) -> dict:
    account = await integrations.get(session, "cdek.account")
    secret = await integrations.get(session, "cdek.secret")
    if not (account and secret):
        raise HTTPException(400, "СДЭК не настроен — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "cdek.test", "true") or "true").lower()
    return {
        "account": account,
        "secret": secret,
        "is_test": test in _TRUE,
        "from_postal": await integrations.get(session, "cdek.from_postal", "101000"),
        "tariff_code": int(await integrations.get(session, "cdek.tariff_code", "137") or 137),
        "weight": int(await integrations.get(session, "cdek.weight", "300") or 300),
        "sender_name": await integrations.get(session, "cdek.sender_name", "casetop"),
    }


class CalcIn(BaseModel):
    to_postal: str
    weight: int | None = None


class CalcOut(BaseModel):
    delivery_sum: float
    period_min: int | None
    period_max: int | None
    tariff_code: int


@router.post("/calc", response_model=CalcOut, dependencies=[Depends(require_internal)])
async def calculate(body: CalcIn, session: Session) -> CalcOut:
    cfg = await _cfg(session)
    try:
        res = await cdek.calculate(
            cfg,
            to_postal=body.to_postal,
            weight_g=body.weight or cfg["weight"],
            tariff_code=cfg["tariff_code"],
        )
    except cdek.CdekError as e:
        raise HTTPException(400, f"СДЭК: {e}") from e
    return CalcOut(**res)


class CreateIn(BaseModel):
    to_postal: str
    to_address: str
    recipient_name: str
    recipient_phone: str


@router.post("/orders/{order_id}/create", dependencies=[Depends(require_internal)])
async def create_delivery(order_id: int, body: CreateIn, session: Session) -> dict:
    """Создать заявку СДЭК для заказа. Сохраняет службу/адрес/стоимость/трек."""
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    cfg = await _cfg(session)
    try:
        calc = await cdek.calculate(
            cfg, to_postal=body.to_postal, weight_g=cfg["weight"], tariff_code=cfg["tariff_code"]
        )
        created = await cdek.create_order(
            cfg,
            order_id=order_id,
            to_postal=body.to_postal,
            to_address=body.to_address,
            recipient_name=body.recipient_name,
            recipient_phone=body.recipient_phone,
            weight_g=cfg["weight"],
            tariff_code=cfg["tariff_code"],
        )
    except cdek.CdekError as e:
        raise HTTPException(400, f"СДЭК: {e}") from e
    order.delivery_service = "cdek"
    order.delivery_address = body.to_address
    order.delivery_cost = calc["delivery_sum"]
    order.tracking_code = created["uuid"]
    await session.commit()
    return {"uuid": created["uuid"], "delivery_cost": calc["delivery_sum"]}


# ── Яндекс Доставка ────────────────────────────────────
async def yandex_cfg(session: AsyncSession) -> dict:
    token = await integrations.get(session, "yandex.oauth_token")
    if not token:
        raise HTTPException(
            400, "Яндекс Доставка не настроена — задайте токен в «Настройки → Интеграции»."
        )
    test = (await integrations.get(session, "yandex.test", "true") or "true").lower()
    return {
        "token": token,
        "is_test": test in _TRUE,
        "merchant_id": await integrations.get(session, "yandex.merchant_id"),
        "platform_station_id": await integrations.get(session, "yandex.platform_station_id"),
        "last_mile_policy": await integrations.get(
            session, "yandex.last_mile_policy", "time_interval"
        ),
        "payment_method": await integrations.get(session, "yandex.payment_method", "already_paid"),
        "weight": _int(await integrations.get(session, "yandex.weight", "300"), 300),
        "pickup_delay_hours": _int(
            await integrations.get(session, "yandex.pickup_delay_hours", "24"), 24
        ),
        "nds": _int(await integrations.get(session, "yandex.nds", "0"), 0),
        "geocoder_apikey": await integrations.get(session, "yandex.geocoder_apikey"),
    }


class PickupPointOut(BaseModel):
    id: str
    name: str | None
    address: str | None
    latitude: float | None
    longitude: float | None


@router.get(
    "/yandex/pickup-points",
    response_model=list[PickupPointOut],
    dependencies=[Depends(require_internal)],
)
async def yandex_pickup_points(
    session: Session,
    location: Annotated[str | None, Query(description="Город или адрес для фильтра")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[PickupPointOut]:
    """ПВЗ Яндекса для выбора клиентом. `location` сужает список до города."""
    cfg = await yandex_cfg(session)
    try:
        geo_id = await yandex_delivery.detect_geo_id(cfg, location) if location else None
        points = await yandex_delivery.pickup_points(cfg, geo_id=geo_id, limit=limit)
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e
    return [PickupPointOut(**p) for p in points if p.get("id")]


class YandexIn(BaseModel):
    # Либо ПВЗ, либо адрес курьеру. Координаты — если уже известны (иначе Геокодер).
    pickup_point_id: str | None = None
    to_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # По умолчанию берём из карточки клиента.
    recipient_name: str | None = None
    recipient_phone: str | None = None


class YandexCreateIn(YandexIn):
    # Забронировать конкретный оффер из /quote; иначе берём самый дешёвый.
    offer_id: str | None = None


class OfferOut(BaseModel):
    offer_id: str
    expires_at: str | None
    delivery_cost: float
    total_cost: float
    delivery_from: str | None
    delivery_to: str | None
    policy: str | None


async def _yandex_body(session: AsyncSession, cfg: dict, order_id: int, body: YandexIn) -> dict:
    """Собрать заявку Яндекса из заказа, клиента и переданных полей."""
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    client = await session.get(Client, order.client_id)
    name = body.recipient_name or (client.nickname if client else None)
    phone = body.recipient_phone or (client.phone if client else None)
    if not phone:
        raise HTTPException(400, "У клиента нет телефона — передайте recipient_phone.")
    if not (body.pickup_point_id or body.to_address):
        raise HTTPException(400, "Укажите ПВЗ (pickup_point_id) или адрес (to_address).")

    lat, lon = body.latitude, body.longitude
    # Курьеру до двери нужны координаты: адрес геокодируем, если задан ключ.
    if not body.pickup_point_id and lat is None and cfg.get("geocoder_apikey"):
        try:
            lat, lon = await yandex_delivery.geocode(cfg["geocoder_apikey"], body.to_address or "")
        except yandex_delivery.YandexDeliveryError as e:
            raise HTTPException(400, f"Яндекс Доставка: {e}") from e

    # Оценочная стоимость вложения = цена чехла со скидкой (без доставки).
    item_price = float(
        pricing.compute(
            order.cost or 0, order.margin or 0, float(order.total_discount or 0)
        ).price_with_discount
    )
    try:
        return yandex_delivery.build_request(
            cfg,
            order_id=order_id,
            item_price_rub=item_price,
            recipient_name=name or "Получатель",
            recipient_phone=phone,
            pickup_point_id=body.pickup_point_id,
            address=body.to_address,
            latitude=lat,
            longitude=lon,
        )
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e


@router.post(
    "/yandex/orders/{order_id}/quote",
    response_model=list[OfferOut],
    dependencies=[Depends(require_internal)],
)
async def yandex_quote(order_id: int, body: YandexIn, session: Session) -> list[OfferOut]:
    """Варианты доставки с ценой и интервалом. Офферы живут до `expires_at`."""
    cfg = await yandex_cfg(session)
    request = await _yandex_body(session, cfg, order_id, body)
    try:
        offers = await yandex_delivery.offers_create(cfg, request)
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e
    return [OfferOut(**o) for o in offers if o.get("offer_id")]


@router.post("/yandex/orders/{order_id}/create", dependencies=[Depends(require_internal)])
async def yandex_create(order_id: int, body: YandexCreateIn, session: Session) -> dict:
    """Создать доставку Яндекса: оффер → бронь. Сохраняет службу/адрес/цену/трек."""
    cfg = await yandex_cfg(session)
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")

    request = await _yandex_body(session, cfg, order_id, body)
    try:
        offers = await yandex_delivery.offers_create(cfg, request)
        chosen = (
            next((o for o in offers if o["offer_id"] == body.offer_id), None)
            if body.offer_id
            else min(offers, key=lambda o: o["delivery_cost"])
        )
        if chosen is None:
            raise HTTPException(400, "Оффер устарел — запросите варианты заново.")
        request_id = await yandex_delivery.offers_confirm(cfg, chosen["offer_id"])
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e

    order.delivery_service = "yandex"
    order.delivery_address = body.to_address or f"ПВЗ {body.pickup_point_id}"
    order.delivery_cost = chosen["delivery_cost"]
    order.tracking_code = request_id
    await session.commit()
    return {
        "request_id": request_id,
        "delivery_cost": chosen["delivery_cost"],
        "delivery_from": chosen["delivery_from"],
        "delivery_to": chosen["delivery_to"],
    }


async def _yandex_order(session: AsyncSession, order_id: int) -> Order:
    """Заказ с созданной доставкой Яндекса. `tracking_code` = request_id заявки."""
    order = await session.get(Order, order_id)
    if order is None or not order.tracking_code or order.delivery_service != "yandex":
        raise HTTPException(404, "Доставка Яндекса для заказа не создана")
    return order


@router.get("/yandex/orders/{order_id}/status", dependencies=[Depends(require_internal)])
async def yandex_status(order_id: int, session: Session) -> dict:
    """Статус доставки у Яндекса + ссылка на трекинг; двигает заказ по статусам.

    Вебхуков у Platform API нет — статус тянем опросом, поэтому перевод в
    «Отправлен»/«Доставлен» делаем здесь же (боты опрашивают активные доставки).
    """
    order = await _yandex_order(session, order_id)
    cfg = await yandex_cfg(session)
    try:
        info = await yandex_delivery.request_info(cfg, order.tracking_code or "")
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e

    mapped = yandex_delivery.map_status(info.get("status"))
    if mapped:
        new = OrderStatus.DELIVERED if mapped == "delivered" else OrderStatus.SHIPPED
        info["order_status_changed"] = await _advance(
            session, order, new, f"Яндекс: {info.get('status')}"
        )
    return info


@router.post("/yandex/orders/{order_id}/cancel", dependencies=[Depends(require_internal)])
async def yandex_cancel(order_id: int, session: Session) -> dict:
    """Отменить заявку у Яндекса. Наш статус заказа не меняем — это решение оператора."""
    order = await _yandex_order(session, order_id)
    cfg = await yandex_cfg(session)
    try:
        return await yandex_delivery.cancel(cfg, order.tracking_code or "")
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e


@router.get("/yandex/orders/{order_id}/label", dependencies=[Depends(require_internal)])
async def yandex_label(
    order_id: int,
    session: Session,
    size: Annotated[
        Literal["210x297", "100x150", "75x120", "58x60", "58x40"],
        Query(description="Размер ярлыка, мм"),
    ] = "210x297",
) -> Response:
    """PDF-ярлык на посылку — без него её не примут на отгрузке."""
    order = await _yandex_order(session, order_id)
    cfg = await yandex_cfg(session)
    try:
        pdf = await yandex_delivery.generate_label(cfg, order.tracking_code or "", size_mm=size)
    except yandex_delivery.YandexDeliveryError as e:
        raise HTTPException(400, f"Яндекс Доставка: {e}") from e
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="label-{order_id}.pdf"'},
    )


@router.post("/webhooks/cdek")
async def cdek_webhook(request: Request, session: Session) -> dict:
    """Вебхук СДЭК ORDER_STATUS → перевод заказа в «Отправлен»/«Получен»."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}
    attrs = body.get("attributes") or {}
    code = (attrs.get("code") or "").upper()
    number = attrs.get("number") or ""  # наш number = casetop-{order_id}
    order_id = None
    if number.startswith("casetop-"):
        tail = number.split("-", 1)[1]
        if tail.isdigit():
            order_id = int(tail)
    if order_id is None:
        return {"ok": True}

    order = await session.get(Order, order_id)
    if order is None:
        return {"ok": True}

    new = None
    if code in _DELIVERED:
        new = OrderStatus.DELIVERED
    elif code in _SHIPPED:
        new = OrderStatus.SHIPPED
    if new is None:
        return {"ok": True}
    if attrs.get("cdek_number"):
        order.tracking_code = str(attrs["cdek_number"])
    await _advance(session, order, new, f"СДЭК: {code}")
    await session.commit()  # трек-номер сохраняем и когда статус не поменялся
    return {"ok": True}
