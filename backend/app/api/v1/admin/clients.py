"""Клиенты (AdminUI, только Админ): список, карточка, ручная установка скидок.

Скидки задаются вручную (ТЗ); автоматического расчёта нет.
total_discount = loyal_discount + discount_for_slave + discount_master_code — пересчёт
при изменении любого компонента.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import Channel
from app.models.client import Client
from app.models.order import Order
from app.services import pricing

router = APIRouter()


class ClientOut(BaseModel):
    id: int
    phone: str | None
    channel: Channel
    channel_user_id: str
    nickname: str | None
    date_start: datetime | None
    master_code: str | None
    date_master_code: datetime | None
    discount_master_code: float
    slave_code: str | None
    discount_slave_code: float
    number_slave: int
    discount_for_slave: float
    number_orders: int
    loyal_discount: float
    total_discount: float


class DiscountsIn(BaseModel):
    loyal_discount: float
    discount_for_slave: float
    discount_master_code: float
    discount_slave_code: float


def _to_out(c: Client, orders: int) -> ClientOut:
    return ClientOut(
        id=c.id,
        phone=c.phone,
        channel=c.channel,
        channel_user_id=c.channel_user_id,
        nickname=c.nickname,
        date_start=c.date_start,
        master_code=c.master_code,
        date_master_code=c.date_master_code,
        discount_master_code=float(c.discount_master_code),
        slave_code=c.slave_code,
        discount_slave_code=float(c.discount_slave_code),
        number_slave=c.number_slave,
        discount_for_slave=float(c.discount_for_slave),
        number_orders=orders,
        loyal_discount=float(c.loyal_discount),
        total_discount=float(c.total_discount),
    )


async def _orders_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(Order.client_id, func.count(Order.id)).group_by(Order.client_id)
    )
    return dict(rows.all())


@router.get("", response_model=list[ClientOut])
async def list_clients(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query()] = None,
    channel: Channel | None = None,
) -> list[ClientOut]:
    stmt = select(Client).order_by(Client.id.desc())
    if channel:
        stmt = stmt.where(Client.channel == channel)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Client.phone.ilike(term), Client.nickname.ilike(term)))
    counts = await _orders_counts(session)
    result = await session.execute(stmt)
    return [_to_out(c, counts.get(c.id, 0)) for c in result.scalars().all()]


async def _get_or_404(session: AsyncSession, client_id: int) -> Client:
    c = await session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return c


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: int,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientOut:
    c = await _get_or_404(session, client_id)
    n = await session.scalar(select(func.count(Order.id)).where(Order.client_id == client_id))
    return _to_out(c, n or 0)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_discounts(
    client_id: int,
    payload: DiscountsIn,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClientOut:
    c = await _get_or_404(session, client_id)
    c.loyal_discount = payload.loyal_discount
    c.discount_for_slave = payload.discount_for_slave
    c.discount_master_code = payload.discount_master_code
    c.discount_slave_code = payload.discount_slave_code
    # Автопересчёт итоговой скидки (сумма трёх компонент).
    c.total_discount = float(
        pricing.total_discount(
            payload.loyal_discount, payload.discount_for_slave, payload.discount_master_code
        )
    )
    await session.commit()
    n = await session.scalar(select(func.count(Order.id)).where(Order.client_id == client_id))
    return _to_out(c, n or 0)
