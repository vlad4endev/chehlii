"""Тексты сообщений бота (редактируются через AdminUI). Бот их подгружает."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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


@router.get("", response_model=list[BotMessageOut])
async def list_messages(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BotMessageOut]:
    result = await session.execute(select(BotMessage).order_by(BotMessage.code))
    return [
        BotMessageOut(
            code=m.code,
            trigger=m.trigger,
            text=m.text,
            buttons=m.buttons,
            mode=m.mode,
            channel_tg=m.channel_tg,
            channel_max=m.channel_max,
        )
        for m in result.scalars().all()
    ]


@router.get("/{code}", response_model=BotMessageOut)
async def get_message(
    code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BotMessageOut:
    m = await session.scalar(select(BotMessage).where(BotMessage.code == code))
    if m is None:
        raise HTTPException(status_code=404, detail=f"Сообщение {code} не найдено")
    return BotMessageOut(
        code=m.code,
        trigger=m.trigger,
        text=m.text,
        buttons=m.buttons,
        mode=m.mode,
        channel_tg=m.channel_tg,
        channel_max=m.channel_max,
    )
