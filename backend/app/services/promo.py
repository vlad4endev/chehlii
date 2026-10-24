"""Промокоды друзей: активация, дефолты скидок, бонус пригласившему после оплаты."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PaymentKind, PaymentStatus
from app.models.client import Client
from app.models.engagement import PromoActivation
from app.models.messaging import OutboundMessage
from app.models.order import Order
from app.models.payment import Payment
from app.services import integrations, pricing

FRIEND_KEY = "promo.friend_discount_pct"
INVITER_KEY = "promo.inviter_bonus_pct"
MAX_KEY = "promo.max_total_discount_pct"


async def setting_pct(session: AsyncSession, key: str) -> float:
    raw = await integrations.get(session, key, "0")
    try:
        return max(0.0, float(raw or 0))
    except (TypeError, ValueError):
        return 0.0


async def apply_defaults(session: AsyncSession, client: Client) -> None:
    """Если поля скидок ещё 0 — подставить дефолты из настроек (ручной PATCH важнее)."""
    friend = await setting_pct(session, FRIEND_KEY)
    if float(client.discount_slave_code or 0) == 0 and friend > 0:
        client.discount_slave_code = friend
    _recalc(client)


def _recalc(client: Client) -> None:
    client.total_discount = float(
        pricing.total_discount(
            client.loyal_discount,
            client.discount_for_slave,
            client.discount_master_code,
        )
    )


async def has_paid_order(session: AsyncSession, client_id: int) -> bool:
    """Есть ли у клиента хотя бы одна успешная оплата чехла (не доставка)."""
    n = await session.scalar(
        select(func.count(Payment.id)).where(
            Payment.order_id.in_(select(Order.id).where(Order.client_id == client_id)),
            Payment.status == PaymentStatus.PAID,
            Payment.kind.in_((PaymentKind.PREPAYMENT, PaymentKind.POSTPAYMENT)),
        )
    )
    return bool(n)


async def activate(
    session: AsyncSession,
    client: Client,
    code: str,
) -> Client:
    """Активировать чужой slave_code. Один раз, до первой оплаты, не свой код."""
    raw = (code or "").strip().upper()
    if not raw:
        raise ValueError("Введите промокод")
    own = (client.slave_code or "").upper()
    if raw == own:
        raise ValueError("Нельзя активировать свой промокод")
    if client.master_code:
        raise ValueError("Промокод уже активирован")
    if await has_paid_order(session, client.id):
        raise ValueError("Промокод можно активировать только до первой оплаты")

    owner = await session.scalar(select(Client).where(Client.slave_code == raw))
    if owner is None or owner.deleted_at is not None:
        raise ValueError("Промокод не найден")

    friend = await setting_pct(session, FRIEND_KEY)
    disc = float(owner.discount_slave_code or 0) or friend
    if disc <= 0:
        raise ValueError("У этого промокода нет скидки")

    client.master_code = raw
    client.date_master_code = datetime.now(UTC)
    client.discount_master_code = disc
    _recalc(client)

    session.add(
        PromoActivation(
            client_id=client.id,
            code=raw,
            owner_client_id=owner.id,
            discount=disc,
            created_at=datetime.now(UTC),
        )
    )
    return client


async def on_friend_order_paid(session: AsyncSession, order: Order, client: Client | None) -> None:
    """После первой оплаты приглашённого — бонус пригласившему (идемпотентно)."""
    if client is None or not getattr(client, "master_code", None):
        return

    act = await session.scalar(
        select(PromoActivation).where(PromoActivation.client_id == client.id)
    )
    if act is None or act.owner_client_id is None or act.rewarded_at is not None:
        return

    # Бонус только за первую оплату чехла (не доставку).
    paid_count = await session.scalar(
        select(func.count(Payment.id)).where(
            Payment.order_id.in_(select(Order.id).where(Order.client_id == client.id)),
            Payment.status == PaymentStatus.PAID,
            Payment.kind.in_((PaymentKind.PREPAYMENT, PaymentKind.POSTPAYMENT)),
        )
    )
    # Если Payment уже есть — ждём ровно первую; если ручной статус без Payment — тоже ок.
    if paid_count and int(paid_count) > 1:
        return

    inviter = await session.get(Client, act.owner_client_id)
    if inviter is None or inviter.deleted_at is not None:
        return

    bonus = await setting_pct(session, INVITER_KEY)
    cap = await setting_pct(session, MAX_KEY)
    inviter.number_slave = int(inviter.number_slave or 0) + 1
    if bonus > 0:
        new_val = float(inviter.discount_for_slave or 0) + bonus
        if cap > 0:
            new_val = min(new_val, cap)
        inviter.discount_for_slave = Decimal(str(round(new_val, 2)))
        _recalc(inviter)

    act.rewarded_at = datetime.now(UTC)
    text = (
        f"Друг оформил заказ по вашему коду {inviter.slave_code}!\n"
        f"Приглашено: {inviter.number_slave}. "
        f"Ваша скидка за друзей: {int(float(inviter.discount_for_slave or 0))}%."
    )
    session.add(
        OutboundMessage(
            client_id=inviter.id,
            channel=inviter.channel,
            channel_user_id=inviter.channel_user_id,
            order_id=order.id,
            kind="text",
            text=text,
        )
    )
