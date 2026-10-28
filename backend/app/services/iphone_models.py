"""Канонический список моделей iPhone (БД) + добавление новых из админки."""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import IPHONE_MODELS
from app.models.catalog import CaseType, CaseTypeModel, IphoneModel
from app.services import warehouse as wh


def normalize_iphone_model_name(raw: str) -> str:
    """Нормализация имени перед записью в БД.

    - обрезает края и схлопывает пробелы;
    - отклоняет пустое и слишком длинное (>64);
    - не навязывает префикс «iPhone» — админ может ввести как удобно.
    """
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите название модели")
    if len(name) > 64:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Название модели слишком длинное (макс. 64)")
    return name


async def ensure_seeded(session: AsyncSession) -> None:
    """Если таблица пуста (свежий стенд без миграционного bulk) — посеять константу."""
    count = await session.scalar(select(func.count()).select_from(IphoneModel))
    if count:
        return
    for i, name in enumerate(IPHONE_MODELS):
        session.add(IphoneModel(name=name, sort_order=i))
    await session.flush()


async def list_model_names(session: AsyncSession) -> list[str]:
    await ensure_seeded(session)
    rows = await session.scalars(
        select(IphoneModel).order_by(IphoneModel.sort_order, IphoneModel.id)
    )
    return [r.name for r in rows]


async def add_model(
    session: AsyncSession,
    raw_name: str,
    *,
    enable_on_all: bool = False,
) -> str:
    """Добавить модель: канон → складские компоненты → строки у всех типов чехлов."""
    name = normalize_iphone_model_name(raw_name)
    await ensure_seeded(session)

    exists = await session.scalar(select(IphoneModel.id).where(IphoneModel.name == name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Модель «{name}» уже есть")

    max_order = await session.scalar(select(func.max(IphoneModel.sort_order))) or 0
    session.add(IphoneModel(name=name, sort_order=int(max_order) + 1))
    await session.flush()

    await wh.ensure_components_for_model(session, name)

    case_types = (await session.scalars(select(CaseType))).all()
    for ct in case_types:
        already = await session.scalar(
            select(CaseTypeModel.id).where(
                CaseTypeModel.case_type_id == ct.id,
                CaseTypeModel.model_name == name,
            )
        )
        if already:
            continue
        session.add(
            CaseTypeModel(
                case_type_id=ct.id,
                model_name=name,
                is_available=enable_on_all,
                stock=0,
            )
        )
    await session.flush()
    await wh.sync_legacy_stock(session, name)
    return name
