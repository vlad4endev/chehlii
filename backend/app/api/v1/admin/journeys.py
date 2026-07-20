"""Клиентские пути (AdminUI, только Админ): кто где остановился в диалоге бота."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.enums import Channel, OrderStatus
from app.models.client import Client
from app.models.order import Order

router = APIRouter()

# Заказ считается успешным, если дошёл до доставки/отзыва.
_SUCCESS = {OrderStatus.DELIVERED, OrderStatus.REVIEW_OFFERED, OrderStatus.REVIEW_RECEIVED}


class JourneyRow(BaseModel):
    client_id: int
    nickname: str | None
    phone: str | None
    channel: Channel
    first_msg_at: datetime | None
    last_msg_at: datetime | None
    last_msg_code: str | None
    master_code: str | None  # промокод, введённый клиентом
    successful_orders: int


async def _load(session: AsyncSession) -> list[JourneyRow]:
    clients = (
        await session.scalars(
            select(Client)
            .where(Client.deleted_at.is_(None), Client.last_msg_at.is_not(None))
            .order_by(Client.last_msg_at.desc())
        )
    ).all()
    counts = dict(
        (
            await session.execute(
                select(Order.client_id, func.count(Order.id))
                .where(Order.status.in_(_SUCCESS), Order.deleted_at.is_(None))
                .group_by(Order.client_id)
            )
        ).all()
    )
    return [
        JourneyRow(
            client_id=c.id,
            nickname=c.nickname,
            phone=c.phone,
            channel=c.channel,
            first_msg_at=c.date_start,
            last_msg_at=c.last_msg_at,
            last_msg_code=c.last_msg_code,
            master_code=c.master_code,
            successful_orders=int(counts.get(c.id, 0)),
        )
        for c in clients
    ]


@router.get("", response_model=list[JourneyRow])
async def list_journeys(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[JourneyRow]:
    return await _load(session)


@router.get("/export.xlsx")
async def export_journeys(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    from openpyxl import Workbook

    rows = await _load(session)
    wb = Workbook()
    ws = wb.active
    ws.title = "Клиентские пути"
    ws.append(
        [
            "Клиент",
            "Телефон",
            "Канал",
            "Первое сообщение",
            "Последнее сообщение",
            "Код сообщения",
            "Промокод",
            "Успешных заказов",
        ]
    )
    for r in rows:
        ws.append(
            [
                r.nickname or "",
                r.phone or "",
                r.channel,
                r.first_msg_at.strftime("%d.%m.%Y %H:%M") if r.first_msg_at else "",
                r.last_msg_at.strftime("%d.%m.%Y %H:%M") if r.last_msg_at else "",
                r.last_msg_code or "",
                r.master_code or "",
                r.successful_orders,
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="journeys.xlsx"'},
    )
