"""Тексты бота (AdminUI, только Админ): редактор всех msg_XXX без перепрограммирования."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.models.messaging import BotMessage
from app.services import video_note

router = APIRouter()

_MEDIA_FORMATS = frozenset({"text", "video_note", "video_note_text"})


class BotMessageOut(BaseModel):
    code: str
    trigger: str
    text: str
    buttons: list | None
    channel_tg: bool
    channel_max: bool
    media_format: str
    media_url: str | None
    media_file_id_tg: str | None
    media_poster_url: str | None


class BotMessagePatch(BaseModel):
    text: str
    channel_tg: bool | None = None
    channel_max: bool | None = None
    media_format: str | None = None
    media_url: str | None = None
    media_poster_url: str | None = None
    clear_media: bool = False


def _to_out(m: BotMessage) -> BotMessageOut:
    return BotMessageOut(
        code=m.code,
        trigger=m.trigger,
        text=m.text,
        buttons=m.buttons,
        channel_tg=m.channel_tg,
        channel_max=m.channel_max,
        media_format=m.media_format or "text",
        media_url=m.media_url,
        media_file_id_tg=m.media_file_id_tg,
        media_poster_url=m.media_poster_url,
    )


@router.get("", response_model=list[BotMessageOut])
async def list_messages(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BotMessageOut]:
    result = await session.execute(select(BotMessage).order_by(BotMessage.code))
    return [_to_out(m) for m in result.scalars().all()]


@router.patch("/{code}", response_model=BotMessageOut)
async def update_message(
    code: str,
    payload: BotMessagePatch,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BotMessageOut:
    m = await session.scalar(select(BotMessage).where(BotMessage.code == code))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
    m.text = payload.text
    if payload.channel_tg is not None:
        m.channel_tg = payload.channel_tg
    if payload.channel_max is not None:
        m.channel_max = payload.channel_max
    if payload.media_format is not None:
        fmt = payload.media_format.strip()
        if fmt not in _MEDIA_FORMATS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный media_format")
        m.media_format = fmt
    if payload.clear_media:
        m.media_url = None
        m.media_file_id_tg = None
        m.media_poster_url = None
        m.media_format = "text"
    else:
        if payload.media_url is not None:
            url = payload.media_url.strip() or None
            if url and (m.media_format or "text") in ("video_note", "video_note_text"):
                url = await video_note.prepare(url)
            # Смена видео сбрасывает кэш Telegram file_id.
            if url != m.media_url:
                m.media_file_id_tg = None
            m.media_url = url
        if payload.media_poster_url is not None:
            m.media_poster_url = payload.media_poster_url.strip() or None
    await session.commit()
    await session.refresh(m)
    return _to_out(m)
