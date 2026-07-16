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
from app.enums import Channel
from app.models.client import Client

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
