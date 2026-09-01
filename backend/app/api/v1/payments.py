"""Оплата: генерация ссылки (для бота), вебхуки шлюзов, страницы Success/Fail.

Шлюз выбирается настройкой `payment.provider` (robokassa | yandex_pay) — бот всегда
зовёт один и тот же POST /payments/link. Модель платежей двухступенчатая: предоплата
(% от цены со скидкой) и постоплата (остаток).

Подтверждение оплаты: Robokassa — вебхук с подписью (Пароль №2); Яндекс Пэй — вебхук
без проверки подписи, статус перечитывается по API (см. services/yandex_pay.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal import require_internal
from app.core.config import settings
from app.core.database import get_session
from app.enums import OrderStatus, PaymentKind, PaymentStatus
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.services import integrations, pricing, robokassa, stock, yandex_pay

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Статус заказа при успешной оплате данного вида.
_PAID_STATUS = {
    PaymentKind.PREPAYMENT: OrderStatus.PREPAYMENT_PAID,
    PaymentKind.POSTPAYMENT: OrderStatus.POSTPAYMENT_PAID,
}

_KIND_RU = {"prepayment": "предоплата", "postpayment": "постоплата", "delivery": "доставка"}


class LinkIn(BaseModel):
    order_id: int
    kind: PaymentKind = PaymentKind.PREPAYMENT


class LinkOut(BaseModel):
    url: str
    amount: float
    inv_id: int


def _discounted(order: Order) -> float:
    b = pricing.compute(order.cost or 0, order.margin or 0, float(order.total_discount or 0))
    return float(b.price_with_discount)


def _amount(order: Order, kind: PaymentKind, percent: float) -> float:
    disc = _discounted(order)
    prepay = round(disc * percent / 100, 2)
    if kind == PaymentKind.PREPAYMENT:
        return prepay
    if kind == PaymentKind.POSTPAYMENT:
        return round(disc - prepay, 2)
    if kind == PaymentKind.DELIVERY:
        return float(order.delivery_cost or 0)
    return 0.0


async def _robokassa_cfg(session: AsyncSession) -> dict:
    login = await integrations.get(session, "payment.robokassa_login")
    pass1 = await integrations.get(session, "payment.robokassa_pass1")
    pass2 = await integrations.get(session, "payment.robokassa_pass2")
    if not (login and pass1 and pass2):
        raise HTTPException(400, "Robokassa не настроена — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "payment.robokassa_test", "true") or "true").lower()
    percent = float(await integrations.get(session, "payment.prepay_percent", "50") or 50)
    return {
        "login": login,
        "pass1": pass1,
        "pass2": pass2,
        "is_test": test in ("1", "true", "yes", "да"),
        "percent": percent,
    }


async def yandexpay_cfg(session: AsyncSession) -> dict:
    """Креды Пэй из настроек. Публичная — админка использует её для проверки связи."""
    key = await integrations.get(session, "payment.yandexpay_api_key")
    if not key:
        raise HTTPException(400, "Яндекс Пэй не настроен — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "payment.yandexpay_test", "true") or "true").lower()
    return {
        "api_key": key,
        "merchant_id": await integrations.get(session, "payment.yandexpay_merchant_id"),
        "is_test": test in ("1", "true", "yes", "да"),
        "public_base_url": await integrations.get(session, "payment.yandexpay_public_base_url"),
    }


async def _provider(session: AsyncSession) -> str:
    return (await integrations.get(session, "payment.provider", "robokassa") or "robokassa").strip()


async def _yandexpay_link(session: AsyncSession, payment: Payment, description: str) -> str:
    cfg = await yandexpay_cfg(session)
    body = yandex_pay.build_order(
        order_id=str(payment.id),
        amount=float(payment.amount),
        title=description,
        # Ссылка должна жить не меньше, чем заказ до автоотмены, иначе клиент
        # получит напоминание об оплате с уже мёртвой ссылкой.
        ttl_seconds=settings.order_autocancel_hours * 3600,
        redirect_base=cfg["public_base_url"],
    )
    try:
        return await yandex_pay.create_order(cfg, body)
    except yandex_pay.YandexPayError as e:
        raise HTTPException(502, f"Яндекс Пэй: {e}") from e


async def _robokassa_link(
    session: AsyncSession, payment: Payment, order: Order, description: str
) -> str:
    cfg = await _robokassa_cfg(session)
    return robokassa.payment_url(
        login=cfg["login"],
        password1=cfg["pass1"],
        out_sum=float(payment.amount),
        inv_id=payment.id,
        description=description,
        is_test=cfg["is_test"],
        shp={"Shp_order": str(order.id)},
    )


@router.post("/link", response_model=LinkOut, dependencies=[Depends(require_internal)])
async def create_link(body: LinkIn, session: Session) -> LinkOut:
    """Создать ссылку оплаты для заказа (вызывает бот). Шлюз — из `payment.provider`."""
    order = await session.get(Order, body.order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    provider = await _provider(session)
    percent = float(await integrations.get(session, "payment.prepay_percent", "50") or 50)
    amount = _amount(order, body.kind, percent)
    if amount <= 0:
        raise HTTPException(400, "Сумма оплаты равна нулю")

    payment = Payment(
        order_id=order.id,
        kind=body.kind,
        gateway=provider,
        amount=amount,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.flush()

    description = f"casetop заказ #{order.id} ({_KIND_RU.get(body.kind, body.kind)})"
    if provider == "yandex_pay":
        url = await _yandexpay_link(session, payment, description)
    else:
        url = await _robokassa_link(session, payment, order, description)
    payment.payment_url = url
    await session.commit()
    return LinkOut(url=url, amount=amount, inv_id=payment.id)


async def _params(request: Request) -> dict[str, str]:
    data = dict(request.query_params)
    if request.method == "POST":
        data.update({k: str(v) for k, v in (await request.form()).items()})
    return data


async def _robokassa_result(request: Request, session: AsyncSession):
    """ResultURL: подтверждение оплаты от Robokassa (подпись Пароль №2). Ответ «OK<InvId>»."""
    p = await _params(request)
    out_sum, inv_id, sig = p.get("OutSum", ""), p.get("InvId", ""), p.get("SignatureValue", "")
    shp = {k: v for k, v in p.items() if k.startswith("Shp_")}

    payment = await session.get(Payment, int(inv_id)) if inv_id.isdigit() else None
    if payment is None:
        return PlainTextResponse("bad invoice", status_code=400)

    cfg = await _robokassa_cfg(session)
    if not robokassa.verify_result(
        password2=cfg["pass2"], out_sum=out_sum, inv_id=inv_id, signature=sig, shp=shp
    ):
        return PlainTextResponse("bad sign", status_code=400)

    payment.raw_webhook = p
    await _apply_paid(session, payment)
    return PlainTextResponse(f"OK{inv_id}")


# Robokassa дёргает ResultURL и GET, и POST. Два обработчика вместо одного
# api_route(methods=[...]): у роута на два метода один operation_id на обе
# операции, из-за чего OpenAPI отдаёт дубликат и ломает генерацию клиентов.
@router.get("/robokassa/result")
async def robokassa_result_get(request: Request, session: Session):
    return await _robokassa_result(request, session)


@router.post("/robokassa/result")
async def robokassa_result_post(request: Request, session: Session):
    return await _robokassa_result(request, session)


@router.post("/yandex-pay/webhook")
async def yandex_pay_webhook(request: Request, session: Session):
    """Callback Яндекс Пэй: тело — JWT (ES256).

    Подпись не проверяем: из payload берём только `orderId`, а платёжный статус
    перечитываем авторизованным запросом к API — подделанный вебхук стоит лишний
    GET, но не ложную оплату. Любой ответ кроме 200 Пэй ретраит до 24 часов.
    """
    try:
        payload = yandex_pay.webhook_payload(await request.body())
    except yandex_pay.YandexPayError as e:
        return JSONResponse(
            {"status": "fail", "reasonCode": "OTHER", "reason": str(e)[:200]}, status_code=400
        )

    order_id = str((payload.get("order") or {}).get("orderId") or "")
    payment = await session.get(Payment, int(order_id)) if order_id.isdigit() else None
    if payment is None or payment.gateway != "yandex_pay":
        return JSONResponse(
            {"status": "fail", "reasonCode": "ORDER_NOT_FOUND", "reason": "unknown order"},
            status_code=404,
        )

    cfg = await yandexpay_cfg(session)
    try:
        status = await yandex_pay.order_status(cfg, order_id)
        # AUTHORIZED — деньги захолдированы; без capture холд снимется и оплаты не будет.
        if status == "AUTHORIZED":
            if await yandex_pay.capture(cfg, order_id, float(payment.amount)) == "SUCCESS":
                status = "CAPTURED"
    except yandex_pay.YandexPayError as e:
        return JSONResponse(
            {"status": "fail", "reasonCode": "OTHER", "reason": str(e)[:200]}, status_code=502
        )

    if status in yandex_pay.PAID_STATUSES:
        payment.raw_webhook = payload
        await _apply_paid(session, payment)
    elif status in yandex_pay.FAILED_STATUSES and payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.FAILED
        payment.raw_webhook = payload
        await session.commit()
    return {"status": "success"}


async def _apply_paid(session: AsyncSession, payment: Payment) -> None:
    """Провести оплату: статус заказа, списание остатков, уведомление клиенту.

    Идемпотентно — вебхуки шлюзов повторяются, второй раз ничего не меняем.
    """
    if payment.status == PaymentStatus.PAID:
        await session.commit()
        return
    payment.status = PaymentStatus.PAID
    payment.paid_at = datetime.now(UTC)
    order = await session.get(Order, payment.order_id)
    if order is not None:
        order.payment_status = PaymentStatus.PAID
        new = _PAID_STATUS.get(payment.kind)
        if new is not None:
            order.status = new
            if new == OrderStatus.PREPAYMENT_PAID:
                await stock.deduct_for_order(session, order)
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    status=new,
                    changed_by="system",
                    trigger=f"{payment.gateway}: оплата подтверждена",
                    created_at=datetime.now(UTC),
                )
            )
        client = await session.get(Client, order.client_id)
        if client is not None:
            session.add(
                OutboundMessage(
                    client_id=client.id,
                    channel=client.channel,
                    channel_user_id=client.channel_user_id,
                    order_id=order.id,
                    kind="text",
                    text=f"Оплата получена ✅ Спасибо! Заказ #{order.id} в работе.",
                )
            )
    await session.commit()


_PAGE = """<!doctype html><html lang=ru><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>casetop</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f4f3;color:#17181a;display:grid;
place-items:center;min-height:100vh;margin:0}}.c{{text-align:center;max-width:340px;padding:28px}}
h1{{font-size:22px;margin:0 0 10px}}p{{color:#6d6f73;line-height:1.5}}</style>
<div class=c><h1>{title}</h1><p>{text}</p></div>"""


@router.get("/success", response_class=HTMLResponse)
@router.get("/robokassa/success", response_class=HTMLResponse)
async def payment_success() -> str:
    return _PAGE.format(
        title="Оплата прошла ✅", text="Спасибо! Вернитесь в чат бота — продолжим оформление."
    )


@router.get("/fail", response_class=HTMLResponse)
@router.get("/robokassa/fail", response_class=HTMLResponse)
async def payment_fail() -> str:
    return _PAGE.format(
        title="Оплата не завершена",
        text="Платёж отменён или не прошёл. Вернитесь в бот и попробуйте снова.",
    )
