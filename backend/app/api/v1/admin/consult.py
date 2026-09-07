"""Админка: инбокс «Сообщения» — диалоги клиента с продавцом."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import Channel, ConsultSender, ConsultStatus
from app.models.client import Client
from app.models.consult import ConsultMessage, ConsultThread
from app.services import consult, media

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]

FilterTab = Literal["waiting", "open", "closed", "all"]


class MediaItem(BaseModel):
    url: str = ""
    type: str = "image"
    name: str | None = None
    code: str | None = None
    state: str | None = None


class ThreadOut(BaseModel):
    id: int
    client_id: int
    client_name: str
    client_phone: str | None
    channel: Channel
    status: ConsultStatus
    last_message_at: datetime | None
    last_preview: str | None
    last_sender: ConsultSender | None
    unread_admin: int
    created_at: datetime


class MessageOut(BaseModel):
    id: int
    sender: ConsultSender
    admin_user_id: int | None
    kind: str
    text: str | None
    media: list[MediaItem]
    created_at: datetime


class ThreadDetail(BaseModel):
    thread: ThreadOut
    messages: list[MessageOut]


class ReplyIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    media: list[MediaItem] = Field(default_factory=list, max_length=10)


class ScenarioIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


def _name(c: Client) -> str:
    return (c.nickname or c.phone or f"Клиент #{c.id}").strip()


def _thread_out(row: ConsultThread, client: Client) -> ThreadOut:
    return ThreadOut(
        id=row.id,
        client_id=client.id,
        client_name=_name(client),
        client_phone=client.phone,
        channel=client.channel,
        status=row.status,
        last_message_at=row.last_message_at,
        last_preview=row.last_preview,
        last_sender=row.last_sender,
        unread_admin=row.unread_admin,
        created_at=row.created_at,
    )


def _msg_out(m: ConsultMessage) -> MessageOut:
    items: list[MediaItem] = []
    for x in m.media or []:
        if not isinstance(x, dict):
            continue
        if x.get("url") or x.get("type") == "scenario":
            items.append(
                MediaItem(
                    url=str(x.get("url") or ""),
                    type=str(x.get("type") or "file"),
                    name=x.get("name"),
                    code=x.get("code"),
                    state=x.get("state"),
                )
            )
    return MessageOut(
        id=m.id,
        sender=m.sender,
        admin_user_id=m.admin_user_id,
        kind=m.kind,
        text=m.text,
        media=items,
        created_at=m.created_at,
    )


async def _load(session: AsyncSession, thread_id: int) -> tuple[ConsultThread, Client]:
    row = await session.get(ConsultThread, thread_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог не найден")
    client = await session.get(Client, row.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return row, client


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(
    _: AdminOnly,
    session: Session,
    tab: Annotated[FilterTab, Query()] = "all",
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> list[ThreadOut]:
    stmt = (
        select(ConsultThread, Client)
        .join(Client, Client.id == ConsultThread.client_id)
        .where(Client.deleted_at.is_(None))
    )
    if tab == "waiting":
        stmt = stmt.where(
            ConsultThread.status == ConsultStatus.OPEN,
            ConsultThread.unread_admin > 0,
        )
    elif tab == "open":
        stmt = stmt.where(ConsultThread.status == ConsultStatus.OPEN)
    elif tab == "closed":
        stmt = stmt.where(ConsultThread.status == ConsultStatus.CLOSED)
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                Client.nickname.ilike(like),
                Client.phone.ilike(like),
                ConsultThread.last_preview.ilike(like),
            )
        )
    stmt = stmt.order_by(
        ConsultThread.unread_admin.desc(),
        ConsultThread.last_message_at.desc().nullslast(),
        ConsultThread.id.desc(),
    )
    rows = (await session.execute(stmt)).all()
    return [_thread_out(t, c) for t, c in rows]


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: int, _: AdminOnly, session: Session) -> ThreadDetail:
    row, client = await _load(session, thread_id)
    msgs = (
        await session.scalars(
            select(ConsultMessage)
            .where(ConsultMessage.thread_id == thread_id)
            .order_by(ConsultMessage.id)
        )
    ).all()
    return ThreadDetail(thread=_thread_out(row, client), messages=[_msg_out(m) for m in msgs])


@router.post("/threads/{thread_id}/read")
async def mark_read(thread_id: int, _: AdminOnly, session: Session) -> dict:
    row, _client = await _load(session, thread_id)
    row.unread_admin = 0
    await session.commit()
    return {"ok": True}


@router.post("/threads/{thread_id}/close", response_model=ThreadOut)
async def close_thread(thread_id: int, admin: AdminOnly, session: Session) -> ThreadOut:
    row, client = await _load(session, thread_id)
    if client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    await consult.close_with_notify(
        session, thread=row, client=client, admin_user_id=admin.id
    )
    await session.commit()
    await session.refresh(row)
    return _thread_out(row, client)


@router.post("/threads/{thread_id}/reopen", response_model=ThreadOut)
async def reopen_thread(thread_id: int, _: AdminOnly, session: Session) -> ThreadOut:
    row, client = await _load(session, thread_id)
    row.status = ConsultStatus.OPEN
    row.closed_at = None
    await session.commit()
    await session.refresh(row)
    return _thread_out(row, client)


@router.post("/threads/{thread_id}/scenario", response_model=MessageOut)
async def send_scenario(
    thread_id: int, body: ScenarioIn, admin: AdminOnly, session: Session
) -> MessageOut:
    row, client = await _load(session, thread_id)
    if client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    if row.status == ConsultStatus.CLOSED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Диалог закрыт — откройте снова")
    code = body.code.strip()
    try:
        msg = await consult.send_scenario(
            session, thread=row, client=client, code=code, admin_user_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    await session.refresh(msg)
    return _msg_out(msg)


@router.post("/threads/{thread_id}/messages", response_model=MessageOut)
async def reply(thread_id: int, body: ReplyIn, admin: AdminOnly, session: Session) -> MessageOut:
    row, client = await _load(session, thread_id)
    if client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    text = (body.text or "").strip() or None
    items = [m.model_dump() for m in body.media if m.url]
    if not text and not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")
    msg = await consult.add_message(
        session,
        thread=row,
        sender=ConsultSender.ADMIN,
        text=text,
        media=items,
        admin_user_id=admin.id,
    )
    await consult.enqueue_admin_reply(session, client, msg)
    await session.commit()
    await session.refresh(msg)
    return _msg_out(msg)


@router.post("/media")
async def upload_reply_media(file: UploadFile, _: AdminOnly) -> dict[str, str]:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")
    ext, kind = media.consult_kind(file.content_type, file.filename)
    if kind == "file" and ext == "bin":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Формат не поддерживается. Фото, видео или PDF.",
        )
    limit = media.MAX_VIDEO_BYTES if kind in ("video", "audio") else media.MAX_BYTES
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Файл больше {limit // (1024 * 1024)} МБ.",
        )
    return {"url": media.save_bytes(data, ext, "consult"), "type": kind, "name": file.filename or ""}


@router.get("/unread-count")
async def unread_count(_: AdminOnly, session: Session) -> dict:
    n = int(
        await session.scalar(
            select(func.coalesce(func.sum(ConsultThread.unread_admin), 0)).where(
                ConsultThread.status == ConsultStatus.OPEN
            )
        )
        or 0
    )
    waiting = int(
        await session.scalar(
            select(func.count()).select_from(ConsultThread).where(
                ConsultThread.status == ConsultStatus.OPEN,
                ConsultThread.unread_admin > 0,
            )
        )
        or 0
    )
    return {"unread": n, "waiting": waiting}
