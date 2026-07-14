"""Отзывы (AdminUI, только Админ): очередь модерации — одобрить/отклонить."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import ReviewStatus
from app.models.engagement import Review

router = APIRouter()

STATUS_LABELS = {
    ReviewStatus.PENDING: "На модерации",
    ReviewStatus.PUBLISHED: "Опубликован",
    ReviewStatus.REJECTED: "Отклонён",
}


class ReviewAdminOut(BaseModel):
    id: int
    author_name: str | None
    text: str | None
    photo_url: str | None
    status: ReviewStatus
    status_label: str
    created_at: datetime


class ModerateIn(BaseModel):
    status: ReviewStatus


def _to_out(r: Review) -> ReviewAdminOut:
    return ReviewAdminOut(
        id=r.id,
        author_name=r.author_name,
        text=r.text,
        photo_url=r.photo_url,
        status=r.status,
        status_label=STATUS_LABELS.get(r.status, r.status),
        created_at=r.created_at,
    )


@router.get("", response_model=list[ReviewAdminOut])
async def list_reviews(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[ReviewStatus | None, Query(alias="status")] = None,
) -> list[ReviewAdminOut]:
    stmt = select(Review).order_by(Review.created_at.desc())
    if status_filter:
        stmt = stmt.where(Review.status == status_filter)
    result = await session.execute(stmt)
    return [_to_out(r) for r in result.scalars().all()]


@router.patch("/{review_id}", response_model=ReviewAdminOut)
async def moderate(
    review_id: int,
    payload: ModerateIn,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReviewAdminOut:
    r = await session.get(Review, review_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Отзыв не найден")
    r.status = payload.status
    await session.commit()
    await session.refresh(r)
    return _to_out(r)
