"""Каталог типов чехлов (чтение). Общий источник данных для мини-приложения и лендинга.

Финансовые поля (cost/margin) не отдаются публично — наружу идёт только client_price.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.models.catalog import CaseType

router = APIRouter()


class CaseModelOut(BaseModel):
    model_name: str
    is_available: bool
    photo_url: str | None
    in_stock: bool  # stock > 0 — гейт на выбор модели в мини-аппе


class CaseTypeOut(BaseModel):
    id: int
    name: str
    is_custom: bool
    description: str | None
    photo_url: str | None
    client_price: float
    models: list[CaseModelOut]


@router.get("", response_model=list[CaseTypeOut])
async def list_case_types(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CaseTypeOut]:
    result = await session.execute(
        select(CaseType)
        .where(CaseType.is_active.is_(True))
        .options(selectinload(CaseType.models))
        .order_by(CaseType.id)
    )
    items = result.scalars().all()
    return [
        CaseTypeOut(
            id=ct.id,
            name=ct.name,
            is_custom=ct.is_custom,
            description=ct.description,
            photo_url=ct.photo_url,
            client_price=ct.client_price,
            models=[
                CaseModelOut(
                    model_name=m.model_name,
                    is_available=m.is_available,
                    photo_url=m.photo_url,
                    in_stock=m.stock > 0,
                )
                for m in ct.models
            ],
        )
        for ct in items
    ]
