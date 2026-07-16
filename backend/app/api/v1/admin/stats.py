"""Сводка для дашборда AdminUI: достоверные метрики заказов, денег, воронки.

Деньги считаются честно и раздельно:
- «Выручка» = сумма фактически оплаченных заказов (payment_status = PAID);
- «Сумма в работе» = стоимость активных (незавершённых, неотменённых) заказов.
Стоимость одного заказа — order_value() (себес+маржа−скидка+доставка); order.final_price
в БД не хранится, поэтому считается на лету — так же, как в списке заказов.
Финансовые показатели скрыты для Дизайнера (RBAC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import CurrentAdmin, is_admin
from app.api.v1.admin.orders import STATUS_LABELS, order_value
from app.core.database import get_session
from app.enums import Channel, OrderStatus, PaymentStatus, ReviewStatus
from app.models.client import Client
from app.models.engagement import Review
from app.models.messaging import Broadcast
from app.models.order import Order

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

S = OrderStatus

# Заказ вне активной воронки (завершён или отменён).
_TERMINAL = {S.DELIVERED, S.CANCELLED, S.REVIEW_RECEIVED}

# Этапы воронки: статус → (ключ этапа, порядок). Порядок задаёт вывод.
_STAGES: list[tuple[str, str, set[OrderStatus]]] = [
    ("new", "Оформление", {S.CASE_TYPE_SELECTED, S.MODEL_SELECTED, S.CASE_CONFIRMED, S.MATERIALS_SUBMITTED}),
    ("pay", "Оплата", {S.PREPAYMENT_ISSUED, S.PREPAYMENT_PAID, S.POSTPAYMENT_ISSUED, S.POSTPAYMENT_PAID, S.DELIVERY_PAYMENT}),
    ("design", "Дизайн", {S.HANDED_TO_DESIGN, S.DESIGN_IN_PROGRESS, S.MOCKUP_SENT, S.MOCKUP_APPROVAL, S.MOCKUP_REVISION}),
    ("ship", "Доставка", {S.DELIVERY_SERVICE_SELECTION, S.DELIVERY_ADDRESS_SELECTION, S.SHIPPED}),
    ("done", "Завершён", {S.DELIVERED, S.REVIEW_OFFERED, S.REVIEW_RECEIVED}),
    ("cancel", "Отменён", {S.CANCELLED}),
]


class StageBucket(BaseModel):
    key: str
    label: str
    count: int


class AttentionItem(BaseModel):
    key: str
    label: str
    count: int
    href: str  # куда ведёт клик (раздел админки, при необходимости с фильтром)


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
    orders_week: int
    orders_done: int
    orders_cancelled: int
    clients_total: int
    reviews_pending: int
    broadcasts_drafts: int
    # Финансы — None для Дизайнера
    revenue_paid: float | None
    pipeline_value: float | None
    avg_check: float | None
    stages: list[StageBucket]
    attention: list[AttentionItem]
    recent_orders: list[RecentOrder]


@router.get("", response_model=StatsOut)
async def dashboard_stats(user: CurrentAdmin, session: Session) -> StatsOut:
    admin = is_admin(user)
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    orders = (await session.scalars(select(Order).where(Order.deleted_at.is_(None)))).all()
    total = len(orders)
    active_orders = [o for o in orders if o.status not in _TERMINAL]
    active = len(active_orders)
    done = sum(1 for o in orders if o.status in {S.DELIVERED, S.REVIEW_OFFERED, S.REVIEW_RECEIVED})
    cancelled = sum(1 for o in orders if o.status == S.CANCELLED)
    today_count = sum(1 for o in orders if o.created_at and o.created_at >= today_start)
    week_count = sum(1 for o in orders if o.created_at and o.created_at >= week_start)

    # Деньги (только Админ).
    revenue_paid = pipeline_value = avg_check = None
    if admin:
        revenue_paid = sum(order_value(o) for o in orders if o.payment_status == PaymentStatus.PAID)
        pipeline_value = sum(order_value(o) for o in active_orders)
        billable = [o for o in orders if o.status != S.CANCELLED]
        avg_check = round(sum(order_value(o) for o in billable) / len(billable), 2) if billable else 0.0

    # Этапы воронки (сгруппировано, в порядке пути заказа).
    stages = []
    for key, label, members in _STAGES:
        c = sum(1 for o in orders if o.status in members)
        stages.append(StageBucket(key=key, label=label, count=c))

    reviews_pending = int(
        await session.scalar(
            select(func.count()).select_from(Review).where(Review.status == ReviewStatus.PENDING)
        )
        or 0
    )

    # Требует внимания — показываем только ненулевые actionable-пункты.
    def _count(statuses: set[OrderStatus]) -> int:
        return sum(1 for o in orders if o.status in statuses)

    attention_raw = [
        ("pay", "Ждут оплаты", _count({S.PREPAYMENT_ISSUED, S.POSTPAYMENT_ISSUED}), "/orders?status=prepayment_issued"),
        ("design", "Передать в дизайн", _count({S.PREPAYMENT_PAID}), "/orders?status=prepayment_paid"),
        ("mockup", "Ждут макет/ответ", _count({S.HANDED_TO_DESIGN, S.DESIGN_IN_PROGRESS, S.MOCKUP_SENT, S.MOCKUP_REVISION}), "/orders?status=design_in_progress"),
        ("review", "Отзывы на модерации", reviews_pending, "/reviews"),
    ]
    attention = [
        AttentionItem(key=k, label=lbl, count=c, href=href)
        for k, lbl, c, href in attention_raw
        if c > 0
    ]

    clients_total = int(
        await session.scalar(
            select(func.count()).select_from(Client).where(Client.deleted_at.is_(None))
        )
        or 0
    )
    drafts = int(
        await session.scalar(
            select(func.count()).select_from(Broadcast).where(Broadcast.sent_at.is_(None))
        )
        or 0
    )

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
            client_price=order_value(o) if admin else None,
        )
        for o, c in recent_rows
    ]

    return StatsOut(
        orders_total=total,
        orders_active=active,
        orders_today=today_count,
        orders_week=week_count,
        orders_done=done,
        orders_cancelled=cancelled,
        clients_total=clients_total,
        reviews_pending=reviews_pending,
        broadcasts_drafts=drafts,
        revenue_paid=revenue_paid,
        pipeline_value=pipeline_value,
        avg_check=avg_check,
        stages=stages,
        attention=attention,
        recent_orders=recent,
    )
