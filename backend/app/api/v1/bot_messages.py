"""Тексты сообщений бота (редактируются через AdminUI). Бот их подгружает."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.messaging import BotMessage

router = APIRouter()


class BotMessageOut(BaseModel):
    code: str
    trigger: str
    text: str
    buttons: list | None
    mode: str
    channel_tg: bool
    channel_max: bool
    media_format: str = "text"
    media_url: str | None = None
    media_file_id_tg: str | None = None
    media_poster_url: str | None = None


class FileIdIn(BaseModel):
    media_file_id_tg: str = Field(min_length=1, max_length=256)


def _to_out(m: BotMessage) -> BotMessageOut:
    return BotMessageOut(
        code=m.code,
        trigger=m.trigger,
        text=m.text,
        buttons=m.buttons,
        mode=m.mode,
        channel_tg=m.channel_tg,
        channel_max=m.channel_max,
        media_format=m.media_format or "text",
        media_url=m.media_url,
        media_file_id_tg=m.media_file_id_tg,
        media_poster_url=m.media_poster_url,
    )


@router.get("", response_model=list[BotMessageOut])
async def list_messages(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BotMessageOut]:
    result = await session.execute(select(BotMessage).order_by(BotMessage.code))
    return [_to_out(m) for m in result.scalars().all()]


@router.get("/{code}", response_model=BotMessageOut)
async def get_message(
    code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BotMessageOut:
    m = await session.scalar(select(BotMessage).where(BotMessage.code == code))
    if m is None:
        raise HTTPException(status_code=404, detail=f"Сообщение {code} не найдено")
    return _to_out(m)


@router.patch("/{code}/file-id", response_model=BotMessageOut)
async def cache_file_id(
    code: str,
    body: FileIdIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BotMessageOut:
    """Кэш Telegram file_id после успешной отправки кружка — бот не качает файл снова."""
    m = await session.scalar(select(BotMessage).where(BotMessage.code == code))
    if m is None:
        raise HTTPException(status_code=404, detail=f"Сообщение {code} не найдено")
    m.media_file_id_tg = body.media_file_id_tg.strip()
    await session.commit()
    await session.refresh(m)
    return _to_out(m)
