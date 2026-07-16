"""Настройки мини-приложения (Админ): главная картинка + текст."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.models.settings import IntegrationSetting
from app.services import integrations

router = APIRouter()


class HeroIn(BaseModel):
    image_url: str | None = None
    title: str | None = None


class HeroOut(BaseModel):
    image_url: str | None
    title: str | None


@router.get("/hero", response_model=HeroOut)
async def read_hero(
    _: AdminOnly, session: Annotated[AsyncSession, Depends(get_session)]
) -> HeroOut:
    return HeroOut(
        image_url=await integrations.get(session, "miniapp.hero_image_url"),
        title=await integrations.get(session, "miniapp.hero_title"),
    )


@router.put("/hero", response_model=HeroOut)
async def save_hero(
    body: HeroIn, _: AdminOnly, session: Annotated[AsyncSession, Depends(get_session)]
) -> HeroOut:
    # Пишем напрямую — integrations.set_many фильтрует по INTEGRATION_SCHEMA.
    for key, val in [
        ("miniapp.hero_image_url", body.image_url or ""),
        ("miniapp.hero_title", body.title or ""),
    ]:
        row = await session.get(IntegrationSetting, key)
        if row is None:
            session.add(IntegrationSetting(key=key, value=val))
        else:
            row.value = val
    await session.commit()
    return HeroOut(image_url=body.image_url, title=body.title)
