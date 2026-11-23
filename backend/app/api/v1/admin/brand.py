"""Логотип (только Админ): загрузка файла идёт через /admin/media, здесь — сохранить ссылку."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.services import brand

router = APIRouter()


class LogoIn(BaseModel):
    logo_url: str | None = None


class LogoOut(BaseModel):
    logo_url: str | None


@router.get("/logo", response_model=LogoOut)
async def read_logo(
    _: AdminOnly, session: Annotated[AsyncSession, Depends(get_session)]
) -> LogoOut:
    return LogoOut(logo_url=await brand.get_logo_url(session))


@router.put("/logo", response_model=LogoOut)
async def save_logo(
    body: LogoIn, _: AdminOnly, session: Annotated[AsyncSession, Depends(get_session)]
) -> LogoOut:
    value = await brand.set_logo_url(session, body.logo_url)
    await session.commit()
    return LogoOut(logo_url=value)
