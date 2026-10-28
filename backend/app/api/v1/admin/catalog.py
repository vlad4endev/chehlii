"""Каталог (AdminUI, только Админ): CRUD типов чехлов + доступность по моделям.

Админ видит финансовые поля (себес, маржа). Цена для клиента = себес + маржа.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.models.catalog import CaseType, CaseTypeModel
from app.models.order import Order
from app.services import iphone_models as im
from app.services import warehouse as wh

router = APIRouter()


class ModelAvailability(BaseModel):
    model_name: str
    is_available: bool = True
    photo_url: str | None = None
    stock: int = Field(default=0, ge=0)


class IphoneModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # True → сразу доступна во всех типах чехлов; False → только в каноне/на складе.
    enable_on_all: bool = False


class CaseTypeIn(BaseModel):
    name: str = Field(min_length=1)
    is_custom: bool = False
    description: str | None = None
    photo_url: str | None = None
    cost: float = 0
    margin: float = 0
    is_active: bool = True
    plate_type: str | None = "black"  # silver|black — пластина на складе
    models: list[ModelAvailability] = Field(default_factory=list)


class CaseTypeAdminOut(BaseModel):
    id: int
    name: str
    is_custom: bool
    description: str | None
    photo_url: str | None
    cost: float
    margin: float
    client_price: float
    is_active: bool
    plate_type: str | None
    orders_count: int
    models: list[ModelAvailability]


def _sorted_models(
    models: list[CaseTypeModel],
    canon: list[str],
) -> list[CaseTypeModel]:
    """Порядок как в каноне; неизвестные модели — в конце."""
    rank = {name: i for i, name in enumerate(canon)}
    return sorted(models, key=lambda m: (rank.get(m.model_name, 10_000), m.model_name))


def _to_out(ct: CaseType, orders_count: int, canon: list[str]) -> CaseTypeAdminOut:
    return CaseTypeAdminOut(
        id=ct.id,
        name=ct.name,
        is_custom=ct.is_custom,
        description=ct.description,
        photo_url=ct.photo_url,
        cost=float(ct.cost),
        margin=float(ct.margin),
        client_price=ct.client_price,
        is_active=ct.is_active,
        plate_type=ct.plate_type or "black",
        orders_count=orders_count,
        models=[
            ModelAvailability(
                model_name=m.model_name,
                is_available=m.is_available,
                photo_url=m.photo_url,
                stock=m.stock,
            )
            for m in _sorted_models(ct.models, canon)
        ],
    )


async def _orders_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(Order.case_type_id, func.count(Order.id)).group_by(Order.case_type_id)
    )
    return {cid: cnt for cid, cnt in rows.all() if cid is not None}


@router.get("/iphone-models", response_model=list[str])
async def iphone_models(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[str]:
    return await im.list_model_names(session)


@router.post("/iphone-models", response_model=list[str], status_code=status.HTTP_201_CREATED)
async def create_iphone_model(
    payload: IphoneModelCreate,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[str]:
    await im.add_model(session, payload.name, enable_on_all=payload.enable_on_all)
    await session.commit()
    return await im.list_model_names(session)


@router.get("", response_model=list[CaseTypeAdminOut])
async def list_case_types(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CaseTypeAdminOut]:
    result = await session.execute(
        select(CaseType).options(selectinload(CaseType.models)).order_by(CaseType.id)
    )
    counts = await _orders_counts(session)
    canon = await im.list_model_names(session)
    return [_to_out(ct, counts.get(ct.id, 0), canon) for ct in result.scalars().all()]


async def _get_or_404(session: AsyncSession, case_type_id: int) -> CaseType:
    ct = await session.scalar(
        select(CaseType).options(selectinload(CaseType.models)).where(CaseType.id == case_type_id)
    )
    if ct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип чехла не найден")
    return ct


@router.get("/{case_type_id}", response_model=CaseTypeAdminOut)
async def get_case_type(
    case_type_id: int,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CaseTypeAdminOut:
    ct = await _get_or_404(session, case_type_id)
    counts = await _orders_counts(session)
    canon = await im.list_model_names(session)
    return _to_out(ct, counts.get(ct.id, 0), canon)


@router.post("", response_model=CaseTypeAdminOut, status_code=status.HTTP_201_CREATED)
async def create_case_type(
    payload: CaseTypeIn,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CaseTypeAdminOut:
    ct = CaseType(
        name=payload.name,
        is_custom=payload.is_custom,
        description=payload.description,
        photo_url=payload.photo_url,
        cost=payload.cost,
        margin=payload.margin,
        is_active=payload.is_active,
        plate_type=payload.plate_type or "black",
    )
    ct.models = [
        CaseTypeModel(
            model_name=m.model_name,
            is_available=m.is_available,
            photo_url=m.photo_url,
            stock=m.stock,
        )
        for m in payload.models
    ]
    session.add(ct)
    await session.flush()
    for m in {row.model_name for row in ct.models}:
        await wh.sync_legacy_stock(session, m)
    await session.commit()
    await session.refresh(ct, ["models"])
    canon = await im.list_model_names(session)
    return _to_out(ct, 0, canon)


@router.patch("/{case_type_id}", response_model=CaseTypeAdminOut)
async def update_case_type(
    case_type_id: int,
    payload: CaseTypeIn,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CaseTypeAdminOut:
    ct = await _get_or_404(session, case_type_id)
    ct.name = payload.name
    ct.is_custom = payload.is_custom
    ct.description = payload.description
    ct.photo_url = payload.photo_url
    ct.cost = payload.cost
    ct.margin = payload.margin
    ct.is_active = payload.is_active
    ct.plate_type = payload.plate_type or "black"
    # Полная замена набора моделей. Сначала удаляем старые и сбрасываем в БД,
    # иначе вставка новых строк с теми же ключами нарушит уникальный индекс.
    ct.models.clear()
    await session.flush()
    ct.models = [
        CaseTypeModel(
            model_name=m.model_name,
            is_available=m.is_available,
            photo_url=m.photo_url,
            stock=m.stock,
        )
        for m in payload.models
    ]
    await session.flush()
    # После смены plate_type пересчитать кэш available из компонентов склада.
    for m in {row.model_name for row in ct.models}:
        await wh.sync_legacy_stock(session, m)
    await session.commit()
    await session.refresh(ct, ["models"])
    counts = await _orders_counts(session)
    canon = await im.list_model_names(session)
    return _to_out(ct, counts.get(ct.id, 0), canon)


@router.delete("/{case_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case_type(
    case_type_id: int,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    ct = await _get_or_404(session, case_type_id)
    used = await session.scalar(
        select(func.count(Order.id)).where(Order.case_type_id == case_type_id)
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Нельзя удалить: по типу есть заказы. Отключите его (снимите «Активен»).",
        )
    await session.delete(ct)
    await session.commit()
