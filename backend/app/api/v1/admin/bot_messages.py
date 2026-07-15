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

router = APIRouter()


class BotMessageOut(BaseModel):
    code: str
    trigger: str
    text: str
    buttons: list | None
    channel_tg: bool
    channel_max: bool


class BotMessagePatch(BaseModel):
    text: str
    channel_tg: bool | None = None
    channel_max: bool | None = None


def _to_out(m: BotMessage) -> BotMessageOut:
    return BotMessageOut(
        code=m.code,
        trigger=m.trigger,
        text=m.text,
        buttons=m.buttons,
        channel_tg=m.channel_tg,
        channel_max=m.channel_max,
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
    await session.commit()
    await session.refresh(m)
    return _to_out(m)
