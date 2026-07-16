"""Клиентские пути (AdminUI, только Админ): кто где остановился в диалоге бота."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import Channel
from app.models.client import Client

router = APIRouter()


class JourneyRow(BaseModel):
    client_id: int
    nickname: str | None
    phone: str | None
    channel: Channel
    last_msg_at: datetime | None
    last_msg_code: str | None
    master_code: str | None  # промокод, введённый клиентом


@router.get("", response_model=list[JourneyRow])
async def list_journeys(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[JourneyRow]:
    rows = (
        await session.scalars(
            select(Client)
            .where(Client.deleted_at.is_(None), Client.last_msg_code.is_not(None))
            .order_by(Client.last_msg_at.desc())
        )
    ).all()
    return [
        JourneyRow(
            client_id=c.id,
            nickname=c.nickname,
            phone=c.phone,
            channel=c.channel,
            last_msg_at=c.last_msg_at,
            last_msg_code=c.last_msg_code,
            master_code=c.master_code,
        )
        for c in rows
    ]
