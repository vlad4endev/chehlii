"""Приём отзыва клиента: запись в reviews + переход заказа + msg_017.

Ответ на msg_016 не должен попадать в консультацию («Сообщения») —
только в очередь модерации отзывов.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OrderStatus, ReviewStatus
from app.models.client import Client
from app.models.engagement import Review
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import consult

_THANKS = "Спасибо за отзыв! Нам очень приятно ✨"


async def pending_order(session: AsyncSession, client_id: int) -> Order | None:
    """Последний заказ клиента в статусе «предложен отзыв»."""
    return await session.scalar(
        select(Order)
        .where(
            Order.client_id == client_id,
            Order.deleted_at.is_(None),
            Order.status == OrderStatus.REVIEW_OFFERED,
        )
        .order_by(Order.id.desc())
        .limit(1)
    )


async def _thanks_text(session: AsyncSession) -> str:
    text = await consult.bot_message_text(session, "msg_017")
    if not text or text == "msg_017":
        return _THANKS
    return text


async def submit(
    session: AsyncSession,
    *,
    client: Client,
    text: str | None,
    photo_url: str | None,
    order: Order | None = None,
) -> Review:
    """Создать отзыв (pending), закрыть заказ как review_received, поставить msg_017."""
    body = (text or "").strip() or None
    photo = (photo_url or "").strip() or None
    if not body and not photo:
        raise ValueError("Пустой отзыв: нужен текст или фото")

    target = order or await pending_order(session, client.id)
    if target is None or target.status != OrderStatus.REVIEW_OFFERED:
        raise ValueError("Нет заказа, ожидающего отзыв")

    review = Review(
        client_id=client.id,
        order_id=target.id,
        text=body,
        photo_url=photo,
        author_name=client.nickname,
        status=ReviewStatus.PENDING,
    )
    session.add(review)

    target.status = OrderStatus.REVIEW_RECEIVED
    session.add(
        OrderStatusHistory(
            order_id=target.id,
            status=OrderStatus.REVIEW_RECEIVED,
            changed_by="system",
            trigger="Клиент прислал отзыв",
            created_at=datetime.now(UTC),
        )
    )
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            order_id=target.id,
            kind="text",
            text=await _thanks_text(session),
        )
    )
    await session.flush()
    return review
