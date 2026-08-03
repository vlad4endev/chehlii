"""Доставка СДЭК: расчёт стоимости, создание заявки, вебхук статуса.

Креды и параметры отправителя — из «Настройки → Интеграции → СДЭК».
Статусы приходят вебхуком ORDER_STATUS и переводят заказ в «Отправлен»/«Получен».
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal import require_internal
from app.core.database import get_session
from app.enums import OrderStatus
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import cdek, integrations

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Коды статусов СДЭК → статус заказа.
_DELIVERED = {"DELIVERED"}
_SHIPPED = {"RECEIVED_AT_SHIPMENT_WAREHOUSE", "ACCEPTED_AT_PICK_UP_POINT", "IN_TRANSIT",
            "ACCEPTED_AT_TRANSIT_WAREHOUSE", "RECEIVED_AT_TRANSIT_WAREHOUSE"}


async def _cfg(session: AsyncSession) -> dict:
    account = await integrations.get(session, "cdek.account")
    secret = await integrations.get(session, "cdek.secret")
    if not (account and secret):
        raise HTTPException(400, "СДЭК не настроен — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "cdek.test", "true") or "true").lower()
    return {
        "account": account,
        "secret": secret,
        "is_test": test in ("1", "true", "yes", "да"),
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
            cfg, to_postal=body.to_postal, weight_g=body.weight or cfg["weight"],
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
            cfg, order_id=order_id, to_postal=body.to_postal, to_address=body.to_address,
            recipient_name=body.recipient_name, recipient_phone=body.recipient_phone,
            weight_g=cfg["weight"], tariff_code=cfg["tariff_code"],
        )
    except cdek.CdekError as e:
        raise HTTPException(400, f"СДЭК: {e}") from e
    order.delivery_service = "cdek"
    order.delivery_address = body.to_address
    order.delivery_cost = calc["delivery_sum"]
    order.tracking_code = created["uuid"]
    await session.commit()
    return {"uuid": created["uuid"], "delivery_cost": calc["delivery_sum"]}


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
    if new and order.status != new:
        order.status = new
        if attrs.get("cdek_number"):
            order.tracking_code = str(attrs["cdek_number"])
        session.add(
            OrderStatusHistory(
                order_id=order.id, status=new, changed_by="system",
                trigger=f"СДЭК: {code}", created_at=datetime.now(UTC),
            )
        )
        client = await session.get(Client, order.client_id)
        if client is not None:
            txt = "Заказ доставлен ✅" if new == OrderStatus.DELIVERED else "Заказ отправлен 🚚"
            session.add(
                OutboundMessage(
                    client_id=client.id, channel=client.channel,
                    channel_user_id=client.channel_user_id, order_id=order.id,
                    kind="text", text=f"{txt} #{order.id}",
                )
            )
        await session.commit()
    return {"ok": True}
