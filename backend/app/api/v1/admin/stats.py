"""Сводка для дашборда AdminUI: метрики заказов, клиентов, модерации.

Финансовые показатели (сумма заказов, цены) скрываются для Дизайнера (RBAC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import CurrentAdmin, is_admin
from app.api.v1.admin.orders import STATUS_LABELS
from app.core.database import get_session
from app.enums import Channel, OrderStatus, ReviewStatus
from app.models.client import Client
from app.models.engagement import Review
from app.models.messaging import Broadcast
from app.models.order import Order
from app.services import pricing

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Терминальные статусы — заказ вне активной воронки.
_TERMINAL = {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REVIEW_RECEIVED}


class StatusBucket(BaseModel):
    status: str
    label: str
    count: int


class RecentOrder(BaseModel):
    id: int
    created_at: datetime
    client_name: str | None
    channel: Channel
    status: str
    label: str
    client_price: float | None  # None для Дизайнера


class StatsOut(BaseModel):
    orders_total: int
    orders_active: int
    orders_today: int
    orders_cancelled: int
    clients_total: int
    reviews_pending: int
    broadcasts_drafts: int
    revenue_active: float | None  # сумма активных заказов; None для Дизайнера
    status_distribution: list[StatusBucket]
    recent_orders: list[RecentOrder]


def _price(order: Order) -> float:
    breakdown = pricing.compute(
        order.cost or 0, order.margin or 0, float(order.total_discount or 0)
    )
    return float(breakdown.price_with_discount)


@router.get("", response_model=StatsOut)
async def dashboard_stats(user: CurrentAdmin, session: Session) -> StatsOut:
    admin = is_admin(user)
    today = datetime.now(UTC) - timedelta(days=1)

    orders = (await session.scalars(select(Order).where(Order.deleted_at.is_(None)))).all()
    total = len(orders)
    active = sum(1 for o in orders if o.status not in _TERMINAL)
    cancelled = sum(1 for o in orders if o.status == OrderStatus.CANCELLED)
    today_count = sum(1 for o in orders if o.created_at and o.created_at >= today)
    revenue = (
        sum(_price(o) for o in orders if o.status != OrderStatus.CANCELLED) if admin else None
    )

    # Распределение по статусам (только ненулевые), по убыванию.
    by_status: dict[str, int] = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1
    distribution = [
        StatusBucket(status=s, label=STATUS_LABELS.get(s, s), count=c)
        for s, c in sorted(by_status.items(), key=lambda kv: kv[1], reverse=True)
    ]

    clients_total = int(
        await session.scalar(
            select(func.count()).select_from(Client).where(Client.deleted_at.is_(None))
        )
        or 0
    )
    reviews_pending = int(
        await session.scalar(
            select(func.count()).select_from(Review).where(Review.status == ReviewStatus.PENDING)
        )
        or 0
    )
    drafts = int(
        await session.scalar(
            select(func.count()).select_from(Broadcast).where(Broadcast.sent_at.is_(None))
        )
        or 0
    )

    # Последние заказы + имя/канал клиента.
    recent_rows = (
        await session.execute(
            select(Order, Client)
            .join(Client, Client.id == Order.client_id)
            .where(Order.deleted_at.is_(None))
            .order_by(Order.id.desc())
            .limit(6)
        )
    ).all()
    recent = [
        RecentOrder(
            id=o.id,
            created_at=o.created_at,
            client_name=c.nickname or c.phone,
            channel=c.channel,
            status=o.status,
            label=STATUS_LABELS.get(o.status, o.status),
            client_price=_price(o) if admin else None,
        )
        for o, c in recent_rows
    ]

    return StatsOut(
        orders_total=total,
        orders_active=active,
        orders_today=today_count,
        orders_cancelled=cancelled,
        clients_total=clients_total,
        reviews_pending=reviews_pending,
        broadcasts_drafts=drafts,
        revenue_active=revenue,
        status_distribution=distribution,
        recent_orders=recent,
    )
