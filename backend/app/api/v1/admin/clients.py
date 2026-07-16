"""Клиенты (AdminUI, только Админ): список, карточка, ручная установка скидок.

Скидки задаются вручную (ТЗ); автоматического расчёта нет.
total_discount = loyal_discount + discount_for_slave + discount_master_code — пересчёт
при изменении любого компонента.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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

# Хэндл мессенджера (буквы/цифры/подчёркивание) — для прямой ссылки на профиль.
_HANDLE = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def _norm_phone(phone: str | None) -> str | None:
    """Нормализация телефона до последних 10 цифр (РФ) — ключ объединения контактов."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else (digits or None)


def _chat_url(c: Client) -> str | None:
    """Ссылка «открыть чат» с клиентом в его мессенджере."""
    handle = c.nickname if c.nickname and _HANDLE.match(c.nickname) else None
    if c.channel == Channel.TG:
        # По хэндлу — универсальная веб-ссылка; иначе — deep link по id (в приложении).
        return f"https://t.me/{handle}" if handle else f"tg://user?id={c.channel_user_id}"
    if c.channel == Channel.MAX:
        return f"https://max.ru/{handle}" if handle else None
    return None


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


class ContactChannel(BaseModel):
    client_id: int
    channel: Channel
    channel_user_id: str
    nickname: str | None
    number_orders: int
    total_discount: float
    chat_url: str | None  # «открыть чат» в мессенджере


class ContactOut(BaseModel):
    """Единый контакт: один человек, объединённый по номеру телефона из разных каналов."""

    key: str
    display_name: str | None
    phone: str | None
    total_orders: int
    max_discount: float
    channels: list[ContactChannel]


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
    stmt = select(Client).where(Client.deleted_at.is_(None)).order_by(Client.id.desc())
    if channel:
        stmt = stmt.where(Client.channel == channel)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Client.phone.ilike(term), Client.nickname.ilike(term)))
    counts = await _orders_counts(session)
    result = await session.execute(stmt)
    return [_to_out(c, counts.get(c.id, 0)) for c in result.scalars().all()]


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query()] = None,
) -> list[ContactOut]:
    """Клиенты, объединённые в контакты по номеру телефона (TG + MAX = один контакт)."""
    stmt = select(Client).where(Client.deleted_at.is_(None)).order_by(Client.id.desc())
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Client.phone.ilike(term), Client.nickname.ilike(term)))
    clients = (await session.scalars(stmt)).all()
    counts = await _orders_counts(session)

    groups: dict[str, list[Client]] = {}
    for c in clients:
        norm = _norm_phone(c.phone)
        groups.setdefault(norm or f"c{c.id}", []).append(c)

    contacts: list[ContactOut] = []
    for key, members in groups.items():
        channels = [
            ContactChannel(
                client_id=m.id,
                channel=m.channel,
                channel_user_id=m.channel_user_id,
                nickname=m.nickname,
                number_orders=counts.get(m.id, 0),
                total_discount=float(m.total_discount),
                chat_url=_chat_url(m),
            )
            for m in sorted(members, key=lambda m: m.channel)
        ]
        contacts.append(
            ContactOut(
                key=key,
                display_name=next((m.nickname for m in members if m.nickname), None),
                phone=next((m.phone for m in members if m.phone), None),
                total_orders=sum(ch.number_orders for ch in channels),
                max_discount=max((ch.total_discount for ch in channels), default=0.0),
                channels=channels,
            )
        )
    # Сначала с бо́льшим числом заказов, затем объединённые (2 канала) выше.
    contacts.sort(key=lambda x: (-x.total_orders, -len(x.channels)))
    return contacts


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


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Переместить клиента в корзину (мягкое удаление). Обратимо — восстановить
    можно в разделе «Корзина». Заказы клиента остаются на месте.
    """
    c = await _get_or_404(session, client_id)
    if c.deleted_at is None:
        c.deleted_at = datetime.now(UTC)
        await session.commit()
