"""Внутренний API консультаций: бот кладёт сообщения клиента."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import ConsultSender, ConsultStatus
from app.models.client import Client
from app.models.consult import ConsultThread
from app.services import consult, media

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


class MediaItem(BaseModel):
    url: str
    type: str = "image"
    name: str | None = None


class ConsultIn(BaseModel):
    client_id: int
    text: str | None = Field(default=None, max_length=4000)
    media: list[MediaItem] = Field(default_factory=list, max_length=10)


class ConsultOut(BaseModel):
    thread_id: int
    message_id: int
    created_at: datetime


def _saved_file(url: str, kind: str, name: str | None) -> dict[str, str]:
    return {"url": url, "type": kind, "name": name or ""}


@router.post("/files")
async def upload_consult_file(file: UploadFile) -> dict[str, str]:
    """Сохранить вложение клиента (фото, видео, голосовое, файл)."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")
    ext, kind = media.consult_kind(file.content_type, file.filename)
    limit = media.MAX_VIDEO_BYTES if kind in ("video", "audio") else media.MAX_BYTES
    if len(data) > limit:
        mb = limit // (1024 * 1024)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Файл больше {mb} МБ.")
    url = media.save_bytes(data, ext, "consult")
    return _saved_file(url, kind, file.filename)


@router.post("/messages", response_model=ConsultOut)
async def post_client_message(body: ConsultIn, session: Session) -> ConsultOut:
    client = await session.get(Client, body.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    client.deleted_at = None
    text = (body.text or "").strip() or None
    items = [m.model_dump() for m in body.media if m.url]
    if not text and not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")
    thread = await consult.get_or_create_thread(session, client.id)
    msg = await consult.add_message(
        session,
        thread=thread,
        sender=ConsultSender.CLIENT,
        text=text,
        media=items,
    )
    await session.commit()
    return ConsultOut(thread_id=thread.id, message_id=msg.id, created_at=msg.created_at)


@router.get("/open/{client_id}")
async def has_open_thread(client_id: int, session: Session) -> dict:
    """Есть ли открытый диалог — бот решает, слать свободный текст сюда."""
    row = await session.scalar(
        select(ConsultThread).where(
            ConsultThread.client_id == client_id,
            ConsultThread.status == ConsultStatus.OPEN,
        )
    )
    return {"open": row is not None, "thread_id": row.id if row else None}
