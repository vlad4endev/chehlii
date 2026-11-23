"""Ключ складского остатка: имя модели или имя группы «универсальных» моделей.

Остаток хранится в stock_components под ключом (model_name). У обычной модели ключ —
её имя; у модели в группе — имя группы (для тех видов, которые группа делит, см. scope).
Модуль не зависит от services.warehouse, чтобы тот мог им пользоваться без циклов.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import StockGroupScope
from app.models.catalog import IphoneModel
from app.models.warehouse import StockGroup


def scope_applies(scope: str, kind: str) -> bool:
    """Делит ли группа с таким scope компоненты вида kind (base|plate)."""
    return scope == StockGroupScope.BOTH or scope == kind


async def stock_key(session: AsyncSession, kind: str, model_name: str) -> str:
    """Под каким именем лежит остаток вида kind для этой модели."""
    row = (
        await session.execute(
            select(StockGroup.name, StockGroup.scope)
            .join(IphoneModel, IphoneModel.stock_group_id == StockGroup.id)
            .where(IphoneModel.name == model_name)
        )
    ).first()
    if row is not None and scope_applies(row.scope, kind):
        return row.name
    return model_name


async def group_members(session: AsyncSession, group_id: int) -> list[str]:
    """Модели группы в порядке справочника."""
    rows = await session.scalars(
        select(IphoneModel.name)
        .where(IphoneModel.stock_group_id == group_id)
        .order_by(IphoneModel.sort_order, IphoneModel.id)
    )
    return list(rows)


async def models_for_key(session: AsyncSession, key: str) -> list[str]:
    """Какие модели используют остаток с этим ключом: члены группы или сама модель."""
    group = await session.scalar(select(StockGroup).where(StockGroup.name == key))
    if group is None:
        return [key]
    return await group_members(session, group.id)


async def members_by_group_name(session: AsyncSession) -> dict[str, list[str]]:
    """{имя группы: модели} — для списка остатков в админке."""
    rows = (
        await session.execute(
            select(StockGroup.name, IphoneModel.name)
            .join(IphoneModel, IphoneModel.stock_group_id == StockGroup.id)
            .order_by(StockGroup.name, IphoneModel.sort_order, IphoneModel.id)
        )
    ).all()
    out: dict[str, list[str]] = {}
    for group_name, model_name in rows:
        out.setdefault(group_name, []).append(model_name)
    return out
