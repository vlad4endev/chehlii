"""Публичные отзывы (для мини-приложения и лендинга): только опубликованные."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import ReviewStatus
from app.models.engagement import Review

router = APIRouter()


class ReviewPublicOut(BaseModel):
    id: int
    author_name: str | None
    text: str | None
    photo_url: str | None
    date: str


@router.get("", response_model=list[ReviewPublicOut])
async def list_published(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReviewPublicOut]:
    result = await session.execute(
        select(Review)
        .where(Review.status == ReviewStatus.PUBLISHED)
        .order_by(Review.created_at.desc())
    )
    return [
        ReviewPublicOut(
            id=r.id,
            author_name=r.author_name,
            text=r.text,
            photo_url=r.photo_url,
            date=r.created_at.strftime("%d.%m") if r.created_at else "",
        )
        for r in result.scalars().all()
    ]
