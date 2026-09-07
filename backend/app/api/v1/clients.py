"""Клиенты: upsert по каналу (для бота при /start и получении контакта)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import Channel, OrderStatus
from app.models.catalog import CaseType
from app.models.client import Client
from app.models.order import Order
from app.services.cdek_checkout import decode_destination

router = APIRouter()


class ClientUpsertIn(BaseModel):
    channel: Channel
    channel_user_id: str
    nickname: str | None = None
    phone: str | None = None


class ClientOut(BaseModel):
    id: int
    phone: str | None
    channel: Channel
    channel_user_id: str
    nickname: str | None
    total_discount: float
    loyal_discount: float
    discount_for_slave: float
    discount_master_code: float
    slave_code: str | None
    number_orders: int
    is_new: bool


def _gen_slave_code() -> str:
    return "CHL" + secrets.token_hex(3).upper()


def _to_out(c: Client, *, is_new: bool) -> ClientOut:
    return ClientOut(
        id=c.id,
        phone=c.phone,
        channel=c.channel,
        channel_user_id=c.channel_user_id,
        nickname=c.nickname,
        total_discount=float(c.total_discount),
        loyal_discount=float(c.loyal_discount),
        discount_for_slave=float(c.discount_for_slave),
        discount_master_code=float(c.discount_master_code),
        slave_code=c.slave_code,
        number_orders=c.number_orders,
        is_new=is_new,
    )


@router.post("/upsert", response_model=ClientOut)
async def upsert_client(
    payload: ClientUpsertIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientOut:
    result = await session.execute(
        select(Client).where(
            Client.channel == payload.channel,
            Client.channel_user_id == payload.channel_user_id,
        )
    )
    client = result.scalar_one_or_none()
    is_new = client is None

    if client is None:
        client = Client(
            channel=payload.channel,
            channel_user_id=payload.channel_user_id,
            date_start=datetime.now(UTC),
            slave_code=_gen_slave_code(),
        )
        session.add(client)

    if payload.nickname is not None:
        client.nickname = payload.nickname
    if payload.phone and not client.phone:
        client.phone = payload.phone
    # upsert вызывается из ботов только на входящее действие клиента (start,
    # контакт, кнопка, ответ) — используем как отметку последней активности.
    client.last_msg_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(client)
    return _to_out(client, is_new=is_new)


class JourneyIn(BaseModel):
    code: str  # msg_XXX


@router.post("/{client_id}/journey")
async def mark_journey(
    client_id: int,
    body: JourneyIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Отметить последний коданный шаг клиента — что бот ему отправил и когда."""
    c = await session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "client not found")
    c.last_msg_code = body.code
    c.last_msg_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


_DELIVERY_STATUSES = (
    OrderStatus.POSTPAYMENT_PAID,
    OrderStatus.DELIVERY_SERVICE_SELECTION,
    OrderStatus.DELIVERY_ADDRESS_SELECTION,
    OrderStatus.DELIVERY_PAYMENT,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
)


class ClientOrderOut(BaseModel):
    id: int
    status: OrderStatus
    case_name: str
    model_name: str | None
    delivery_service: str | None
    delivery_address: str | None
    delivery_cost: float | None
    tracking_code: str | None


@router.get("/{client_id}/orders", response_model=list[ClientOrderOut])
async def client_orders(
    client_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ClientOrderOut]:
    """Заказы клиента, по которым можно оформить или отследить доставку."""
    c = await session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "client not found")
    rows = (
        await session.scalars(
            select(Order)
            .where(
                Order.client_id == client_id,
                Order.deleted_at.is_(None),
                Order.status.in_(_DELIVERY_STATUSES),
            )
            .order_by(Order.id.desc())
            .limit(20)
        )
    ).all()
    out: list[ClientOrderOut] = []
    for order in rows:
        ct = await session.get(CaseType, order.case_type_id) if order.case_type_id else None
        dest = decode_destination(order.delivery_address)
        out.append(
            ClientOrderOut(
                id=order.id,
                status=order.status,
                case_name=ct.name if ct else "",
                model_name=order.model_name,
                delivery_service=order.delivery_service,
                delivery_address=dest.get("label") or None,
                delivery_cost=(
                    float(order.delivery_cost) if order.delivery_cost is not None else None
                ),
                tracking_code=order.tracking_code,
            )
        )
    return out
