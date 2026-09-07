"""Переписка «Поможем выбрать»: треды, сообщения, постановка ответа в outbox."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ConsultSender, ConsultStatus
from app.models.client import Client
from app.models.consult import ConsultMessage, ConsultThread
from app.models.messaging import OutboundMessage

PREVIEW_LEN = 140

_MEDIA_LABEL = {
    "image": "фото",
    "video": "видео",
    "audio": "голосовое",
    "file": "файл",
    "video_note": "кружок",
}


def preview_text(text: str | None, media: list | None) -> str:
    """Короткий превью для списка диалогов."""
    body = (text or "").strip()
    if body:
        return body if len(body) <= PREVIEW_LEN else body[: PREVIEW_LEN - 1] + "…"
    items = media or []
    if not items:
        return "Сообщение"
    kinds = [
        _MEDIA_LABEL.get(str(m.get("type") or ""), "файл")
        for m in items
        if isinstance(m, dict)
    ]
    if not kinds:
        return "Вложение"
    if len(kinds) == 1:
        return kinds[0].capitalize()
    return f"{len(kinds)} вложения"


def message_kind(text: str | None, media: list | None) -> str:
    items = [m for m in (media or []) if isinstance(m, dict) and m.get("url")]
    if not items:
        return "text"
    if len(items) > 1:
        return "album"
    return str(items[0].get("type") or "file")


async def get_or_create_thread(session: AsyncSession, client_id: int) -> ConsultThread:
    row = await session.scalar(select(ConsultThread).where(ConsultThread.client_id == client_id))
    if row is not None:
        return row
    row = ConsultThread(client_id=client_id, status=ConsultStatus.OPEN, unread_admin=0)
    session.add(row)
    await session.flush()
    return row


async def add_message(
    session: AsyncSession,
    *,
    thread: ConsultThread,
    sender: ConsultSender,
    text: str | None,
    media: list | None,
    admin_user_id: int | None = None,
) -> ConsultMessage:
    """Добавить сообщение и обновить сводку треда. Коммит — на вызывающей стороне."""
    clean_media = [m for m in (media or []) if isinstance(m, dict) and m.get("url")] or None
    body = (text or "").strip() or None
    msg = ConsultMessage(
        thread_id=thread.id,
        sender=sender,
        admin_user_id=admin_user_id,
        kind=message_kind(body, clean_media),
        text=body,
        media=clean_media,
    )
    session.add(msg)
    now = datetime.now(UTC)
    thread.last_message_at = now
    thread.last_preview = preview_text(body, clean_media)
    thread.last_sender = sender
    thread.status = ConsultStatus.OPEN
    thread.closed_at = None
    if sender == ConsultSender.CLIENT:
        thread.unread_admin = int(thread.unread_admin or 0) + 1
    else:
        thread.unread_admin = 0
    await session.flush()
    return msg


async def enqueue_admin_reply(session: AsyncSession, client: Client, msg: ConsultMessage) -> None:
    """Поставить ответ продавца в outbox — бот доставит в Telegram/MAX."""
    media = list(msg.media or [])
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            kind="album" if media else "text",
            text=msg.text,
            media=media or None,
        )
    )
