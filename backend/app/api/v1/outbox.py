"""Исходящая очередь для ботов (backend → клиент).

Backend не ходит в мессенджеры напрямую (TG заблокирован на сервере), поэтому
кладёт сообщения в outbox, а бот забирает их (GET) и после доставки помечает
отправленными (POST /{id}/sent).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import Channel
from app.models.messaging import OutboundMessage

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class OutboxItem(BaseModel):
    id: int
    channel: Channel
    channel_user_id: str
    order_id: int | None
    kind: str
    text: str | None
    attachment_url: str | None


@router.get("", response_model=list[OutboxItem])
async def pending(
    channel: Channel,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[OutboxItem]:
    rows = (
        await session.scalars(
            select(OutboundMessage)
            .where(OutboundMessage.channel == channel, OutboundMessage.sent_at.is_(None))
            .order_by(OutboundMessage.id)
            .limit(limit)
        )
    ).all()
    return [
        OutboxItem(
            id=m.id,
            channel=m.channel,
            channel_user_id=m.channel_user_id,
            order_id=m.order_id,
            kind=m.kind,
            text=m.text,
            attachment_url=m.attachment_url,
        )
        for m in rows
    ]


@router.post("/{msg_id}/sent")
async def mark_sent(msg_id: int, session: Session) -> dict:
    m = await session.get(OutboundMessage, msg_id)
    if m and m.sent_at is None:
        m.sent_at = datetime.now(UTC)
        await session.commit()
    return {"ok": True}
