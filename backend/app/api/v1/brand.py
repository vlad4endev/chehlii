"""Публичный бренд: логотип читают админка (экран входа), мини-приложение и лендинг."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services import brand

router = APIRouter()


class BrandOut(BaseModel):
    logo_url: str | None


@router.get("", response_model=BrandOut)
async def get_brand(session: Annotated[AsyncSession, Depends(get_session)]) -> BrandOut:
    return BrandOut(logo_url=await brand.get_logo_url(session))
