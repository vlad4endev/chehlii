"""Корзина (AdminUI, только Админ): мягко удалённые клиенты и заказы.

Удаление клиента/заказа выставляет deleted_at (см. clients.py, orders.py) — записи
скрываются из списков, но остаются в БД. Здесь их можно восстановить (deleted_at=NULL)
или удалить окончательно (hard delete).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.api.v1.admin.orders import STATUS_LABELS
from app.core.database import get_session
from app.enums import Channel
from app.models.catalog import CaseType
from app.models.client import Client
from app.models.engagement import PromoActivation
from app.models.order import Order

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class TrashClient(BaseModel):
    id: int
    nickname: str | None
    phone: str | None
    channel: Channel
    number_orders: int
    deleted_at: datetime | None


class TrashOrder(BaseModel):
    id: int
    created_at: datetime
    client_name: str | None
    case_name: str | None
    model_name: str | None
    status_label: str
    deleted_at: datetime | None


class TrashOut(BaseModel):
    clients: list[TrashClient]
    orders: list[TrashOrder]


@router.get("", response_model=TrashOut)
async def list_trash(_: AdminOnly, session: Session) -> TrashOut:
    # Клиенты в корзине + число их заказов.
    counts = dict(
        (
            await session.execute(
                select(Order.client_id, func.count(Order.id)).group_by(Order.client_id)
            )
        ).all()
    )
    dcl = (
        await session.scalars(
            select(Client).where(Client.deleted_at.is_not(None)).order_by(Client.deleted_at.desc())
        )
    ).all()
    clients = [
        TrashClient(
            id=c.id,
            nickname=c.nickname,
            phone=c.phone,
            channel=c.channel,
            number_orders=counts.get(c.id, 0),
            deleted_at=c.deleted_at,
        )
        for c in dcl
    ]

    # Заказы в корзине + имя клиента и тип чехла.
    rows = (
        await session.execute(
            select(Order, Client, CaseType)
            .join(Client, Order.client_id == Client.id)
            .outerjoin(CaseType, Order.case_type_id == CaseType.id)
            .where(Order.deleted_at.is_not(None))
            .order_by(Order.deleted_at.desc())
        )
    ).all()
    orders = [
        TrashOrder(
            id=o.id,
            created_at=o.created_at,
            client_name=c.nickname or c.phone,
            case_name=ct.name if ct else None,
            model_name=o.model_name,
            status_label=STATUS_LABELS.get(o.status, o.status),
            deleted_at=o.deleted_at,
        )
        for o, c, ct in rows
    ]
    return TrashOut(clients=clients, orders=orders)


@router.post("/clients/{client_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_client(client_id: int, _: AdminOnly, session: Session) -> None:
    c = await session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    c.deleted_at = None
    await session.commit()


@router.post("/orders/{order_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_order(order_id: int, _: AdminOnly, session: Session) -> None:
    o = await session.get(Order, order_id)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    o.deleted_at = None
    await session.commit()


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def purge_client(client_id: int, _: AdminOnly, session: Session) -> None:
    """Удалить клиента окончательно. Заказы клиента блокируют — их историю не теряем."""
    c = await session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    n = await session.scalar(select(func.count(Order.id)).where(Order.client_id == client_id))
    if n:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Нельзя удалить окончательно: у клиента есть заказы. Сначала удалите их из корзины.",
        )
    # Снять ссылку-владельца в чужих активациях промокода (FK без каскада иначе заблокирует).
    await session.execute(
        update(PromoActivation)
        .where(PromoActivation.owner_client_id == client_id)
        .values(owner_client_id=None)
    )
    await session.delete(c)  # favorites/promo_activations — каскад, reviews — SET NULL
    await session.commit()


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def purge_order(order_id: int, _: AdminOnly, session: Session) -> None:
    """Удалить заказ окончательно. История статусов и платежи удаляются каскадом."""
    o = await session.get(Order, order_id)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    await session.delete(o)
    await session.commit()
