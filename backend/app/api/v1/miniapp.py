"""Публичные настройки мини-приложения (главная картинка + текст).

Хранится в integration_settings (ключи miniapp.hero_image_url, miniapp.hero_title).
Правится через /admin/miniapp (только Админ), см. admin/miniapp.py.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services import integrations

router = APIRouter()


class Hero(BaseModel):
    image_url: str | None
    title: str | None


@router.get("/hero", response_model=Hero)
async def get_hero(session: Annotated[AsyncSession, Depends(get_session)]) -> Hero:
    return Hero(
        image_url=await integrations.get(session, "miniapp.hero_image_url"),
        title=await integrations.get(session, "miniapp.hero_title"),
    )
