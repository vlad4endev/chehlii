"""Активация промокода друга (внутренний API для ботов)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.client import Client
from app.services import promo

router = APIRouter()


class ActivateIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    client_id: int


class ActivateOut(BaseModel):
    ok: bool
    discount_master_code: float
    total_discount: float
    master_code: str


@router.post("/activate", response_model=ActivateOut)
async def activate_promo(
    body: ActivateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActivateOut:
    client = await session.get(Client, body.client_id)
    if client is None or client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    try:
        await promo.activate(session, client, body.code)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.commit()
    await session.refresh(client)
    return ActivateOut(
        ok=True,
        discount_master_code=float(client.discount_master_code or 0),
        total_discount=float(client.total_discount or 0),
        master_code=client.master_code or body.code.strip().upper(),
    )
