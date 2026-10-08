"""Отзывы: публичный список опубликованных + внутренний приём от бота."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal import require_internal
from app.core.database import get_session
from app.enums import ReviewStatus
from app.models.client import Client
from app.models.engagement import Review
from app.models.order import Order
from app.services import media, media_assets, review_intake, yandex_disk

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Internal = Annotated[None, Depends(require_internal)]


class ReviewPublicOut(BaseModel):
    id: int
    author_name: str | None
    text: str | None
    photo_url: str | None
    date: str


@router.get("", response_model=list[ReviewPublicOut])
async def list_published(session: Session) -> list[ReviewPublicOut]:
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


class ReviewSubmitIn(BaseModel):
    client_id: int
    text: str | None = Field(default=None, max_length=4000)
    photo_url: str | None = Field(default=None, max_length=1024)
    order_id: int | None = None


class ReviewSubmitOut(BaseModel):
    id: int
    order_id: int | None
    status: ReviewStatus
    created_at: datetime


class PendingOut(BaseModel):
    pending: bool
    order_id: int | None = None


@router.get("/pending/{client_id}", response_model=PendingOut)
async def review_pending(_: Internal, client_id: int, session: Session) -> PendingOut:
    """Есть ли заказ, ждущий отзыв — бот шлёт ответ в reviews, а не в consult."""
    order = await review_intake.pending_order(session, client_id)
    return PendingOut(pending=order is not None, order_id=order.id if order else None)


@router.post("/files")
async def upload_review_file(_: Internal, file: UploadFile, session: Session) -> dict[str, str]:
    """Фото чехла к отзыву (локально + опционально Я.Диск)."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")
    kind_info = media.media_kind(file.content_type, file.filename)
    if kind_info is None or kind_info[1] != "image":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужно изображение.")
    ext, kind = kind_info
    if len(data) > media.MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Файл больше {media.MAX_BYTES // (1024 * 1024)} МБ.",
        )
    root = await media_assets.disk_root(session)
    remote = yandex_disk.review_path(root, file.filename or f"review.{ext}")
    saved, _asset, disk_url = await media_assets.persist(
        session,
        data,
        ext=ext,
        subdir="reviews",
        kind=kind,
        owner_type="review",
        original_filename=file.filename,
        disk_remote_path=remote,
        require_disk=False,
    )
    await session.commit()
    out: dict[str, str] = {
        "url": saved.url,
        "type": kind,
        "name": file.filename or "",
        "sha256": saved.sha256,
    }
    if disk_url:
        out["disk_url"] = disk_url
    return out


@router.post("", response_model=ReviewSubmitOut, status_code=status.HTTP_201_CREATED)
async def submit_review(_: Internal, body: ReviewSubmitIn, session: Session) -> ReviewSubmitOut:
    """Бот кладёт ответ клиента на запрос отзыва в очередь модерации."""
    client = await session.get(Client, body.client_id)
    if client is None or client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")

    order = None
    if body.order_id is not None:
        order = await session.get(Order, body.order_id)
        if order is None or order.client_id != client.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")

    try:
        review = await review_intake.submit(
            session,
            client=client,
            text=body.text,
            photo_url=body.photo_url,
            order=order,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    await session.commit()
    await session.refresh(review)
    return ReviewSubmitOut(
        id=review.id,
        order_id=review.order_id,
        status=review.status,
        created_at=review.created_at,
    )
