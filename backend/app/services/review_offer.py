"""Запрос отзыва: единый текст и постановка сообщения в очередь отправки."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.messaging import BotMessage, OutboundMessage
from app.models.order import Order

DEFAULT_TEXT = "Оставьте отзыв и пришлите фото чехла — будем благодарны!"


async def enqueue(session: AsyncSession, order: Order, client: Client | None) -> None:
    """Поставить сообщение `msg_016` клиенту. Коммит — на вызывающем."""
    if client is None:
        return
    msg = await session.scalar(select(BotMessage).where(BotMessage.code == "msg_016"))
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            order_id=order.id,
            kind="text",
            text=msg.text if msg else DEFAULT_TEXT,
        )
    )
