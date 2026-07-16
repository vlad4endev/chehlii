"""Рассылки (AdminUI, только Админ): ручная отправка сегментам клиентов.

Сегмент задаётся фильтрами: канал (ТГ/МАКС), диапазон даты регистрации,
статус заказа. Отправка — best-effort через Bot API нужного канала.
Черновик = запись без sent_at; после отправки фиксируется sent_at и число получателей.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import Channel, OrderStatus
from app.models.client import Client
from app.models.messaging import Broadcast, OutboundMessage
from app.models.order import Order
from app.services import video_note

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class Segment(BaseModel):
    """Фильтры аудитории. Пустые поля не сужают выборку."""

    channel: Channel | None = None
    registered_from: datetime | None = None
    registered_to: datetime | None = None
    order_status: OrderStatus | None = None
    only_with_orders: bool = False


class MediaItem(BaseModel):
    url: str
    type: str  # image | video


class BroadcastOut(BaseModel):
    id: int
    text: str
    media: list[MediaItem]
    segment: Segment
    recipients_count: int
    sent_at: datetime | None
    created_at: datetime
    is_draft: bool


class BroadcastCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    media: list[MediaItem] = Field(default_factory=list, max_length=10)
    segment: Segment = Field(default_factory=Segment)


class PreviewIn(BaseModel):
    segment: Segment = Field(default_factory=Segment)


class PreviewOut(BaseModel):
    recipients_count: int
    by_channel: dict[str, int]


class SendResult(BaseModel):
    broadcast: BroadcastOut
    delivered: int
    failed: int
    skipped: int
    note: str | None = None


def _recipients_query(segment: Segment) -> Select:
    """SELECT по клиентам, удовлетворяющим сегменту."""
    q = select(Client)
    if segment.channel is not None:
        q = q.where(Client.channel == segment.channel)
    if segment.registered_from is not None:
        q = q.where(Client.date_start >= segment.registered_from)
    if segment.registered_to is not None:
        q = q.where(Client.date_start <= segment.registered_to)
    if segment.only_with_orders:
        q = q.where(Client.number_orders > 0)
    if segment.order_status is not None:
        sub = select(Order.client_id).where(Order.status == segment.order_status)
        q = q.where(Client.id.in_(sub))
    return q


def _segment_of(row: Broadcast) -> Segment:
    return Segment(**(row.segment or {}))


def _media_of(row: Broadcast) -> list[MediaItem]:
    items = list(row.media or [])
    # Совместимость со старой одиночной картинкой.
    if not items and row.image_url:
        items = [{"url": row.image_url, "type": "image"}]
    return [MediaItem(**m) for m in items]


def _out(row: Broadcast) -> BroadcastOut:
    return BroadcastOut(
        id=row.id,
        text=row.text,
        media=_media_of(row),
        segment=_segment_of(row),
        recipients_count=row.recipients_count,
        sent_at=row.sent_at,
        created_at=row.created_at,
        is_draft=row.sent_at is None,
    )


@router.get("", response_model=list[BroadcastOut])
async def list_broadcasts(_: AdminOnly, session: Session) -> list[BroadcastOut]:
    rows = (await session.scalars(select(Broadcast).order_by(Broadcast.id.desc()))).all()
    return [_out(r) for r in rows]


@router.post("/preview", response_model=PreviewOut)
async def preview(body: PreviewIn, _: AdminOnly, session: Session) -> PreviewOut:
    base = _recipients_query(body.segment).subquery()
    counts = dict(
        (await session.execute(select(base.c.channel, func.count()).group_by(base.c.channel))).all()
    )
    tg = int(counts.get(Channel.TG, 0))
    mx = int(counts.get(Channel.MAX, 0))
    return PreviewOut(recipients_count=tg + mx, by_channel={"tg": tg, "max": mx})


@router.post("", response_model=BroadcastOut, status_code=status.HTTP_201_CREATED)
async def create_broadcast(
    body: BroadcastCreate, admin: AdminOnly, session: Session
) -> BroadcastOut:
    row = Broadcast(
        text=body.text,
        media=[m.model_dump() for m in body.media],
        segment=body.segment.model_dump(mode="json"),
        created_by=admin.id,
        recipients_count=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _out(row)


@router.post("/{broadcast_id}/send", response_model=SendResult)
async def send_broadcast(broadcast_id: int, _: AdminOnly, session: Session) -> SendResult:
    """Ставит сообщения в очередь (outbox) — боты (у них доступ к мессенджерам через
    прокси) доставят их в Telegram и MAX. Картинка уходит вложением (kind=photo)."""
    row = await session.get(Broadcast, broadcast_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рассылка не найдена")
    if row.sent_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Рассылка уже отправлена")

    recipients = (await session.scalars(_recipients_query(_segment_of(row)))).all()
    media = [m.model_dump() for m in _media_of(row)]
    # Автоподготовка кружков — один раз на рассылку, до постановки в outbox.
    for m in media:
        if m.get("type") == "video_note":
            m["url"] = await video_note.prepare(m["url"])
    kind = "album" if media else "text"
    queued = 0
    for c in recipients:
        session.add(
            OutboundMessage(
                client_id=c.id,
                channel=c.channel,
                channel_user_id=c.channel_user_id,
                kind=kind,
                text=row.text,
                media=media or None,
            )
        )
        queued += 1

    row.recipients_count = queued
    row.sent_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)

    note = (
        "Поставлено в очередь — боты доставят в течение минуты."
        if queued
        else "В сегменте нет получателей."
    )
    return SendResult(broadcast=_out(row), delivered=queued, failed=0, skipped=0, note=note)
