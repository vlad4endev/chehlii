"""Оплата через Robokassa: генерация ссылки (для бота), вебхук ResultURL, Success/Fail.

Модель платежей двухступенчатая: предоплата (% от цены со скидкой) и постоплата
(остаток). Статус заказа меняется по подтверждённому вебхуку (Пароль №2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import OrderStatus, PaymentKind, PaymentStatus
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.services import integrations, pricing, robokassa, stock

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Статус заказа при успешной оплате данного вида.
_PAID_STATUS = {
    PaymentKind.PREPAYMENT: OrderStatus.PREPAYMENT_PAID,
    PaymentKind.POSTPAYMENT: OrderStatus.POSTPAYMENT_PAID,
}


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


@router.post("/link", response_model=LinkOut)
async def create_link(body: LinkIn, session: Session) -> LinkOut:
    """Создать ссылку оплаты Robokassa для заказа (вызывает бот)."""
    order = await session.get(Order, body.order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    cfg = await _robokassa_cfg(session)
    amount = _amount(order, body.kind, cfg["percent"])
    if amount <= 0:
        raise HTTPException(400, "Сумма оплаты равна нулю")

    payment = Payment(
        order_id=order.id,
        kind=body.kind,
        gateway="robokassa",
        amount=amount,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.flush()

    kind_ru = {"prepayment": "предоплата", "postpayment": "постоплата", "delivery": "доставка"}
    url = robokassa.payment_url(
        login=cfg["login"],
        password1=cfg["pass1"],
        out_sum=amount,
        inv_id=payment.id,
        description=f"casetop заказ #{order.id} ({kind_ru.get(body.kind, body.kind)})",
        is_test=cfg["is_test"],
        shp={"Shp_order": str(order.id)},
    )
    payment.payment_url = url
    await session.commit()
    return LinkOut(url=url, amount=amount, inv_id=payment.id)


async def _params(request: Request) -> dict[str, str]:
    data = dict(request.query_params)
    if request.method == "POST":
        data.update({k: str(v) for k, v in (await request.form()).items()})
    return data


@router.api_route("/robokassa/result", methods=["GET", "POST"])
async def robokassa_result(request: Request, session: Session):
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

    if payment.status != PaymentStatus.PAID:
        payment.status = PaymentStatus.PAID
        payment.paid_at = datetime.now(UTC)
        payment.raw_webhook = p
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
                        trigger="Robokassa: оплата подтверждена",
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

    return PlainTextResponse(f"OK{inv_id}")


_PAGE = """<!doctype html><html lang=ru><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>casetop</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f4f3;color:#17181a;display:grid;
place-items:center;min-height:100vh;margin:0}}.c{{text-align:center;max-width:340px;padding:28px}}
h1{{font-size:22px;margin:0 0 10px}}p{{color:#6d6f73;line-height:1.5}}</style>
<div class=c><h1>{title}</h1><p>{text}</p></div>"""


@router.get("/robokassa/success", response_class=HTMLResponse)
async def robokassa_success() -> str:
    return _PAGE.format(
        title="Оплата прошла ✅", text="Спасибо! Вернитесь в чат бота — продолжим оформление."
    )


@router.get("/robokassa/fail", response_class=HTMLResponse)
async def robokassa_fail() -> str:
    return _PAGE.format(
        title="Оплата не завершена",
        text="Платёж отменён или не прошёл. Вернитесь в бот и попробуйте снова.",
    )
