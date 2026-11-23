"""Сколько чехлов можно собрать по каждой модели и что на складе заканчивается.

Чехол собирается из балванки модели и пластины нужного цвета, поэтому «можно собрать» —
минимум из двух остатков (с учётом «универсальных» групп, где остаток общий).
Модель «заканчивается» или «закончилась» только для тех цветов пластины, которые
используют активные типы чехлов с этой моделью. Только чтение — ничего не создаётся.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PlateType, StockKind
from app.models.catalog import CaseType, CaseTypeModel, IphoneModel
from app.models.warehouse import StockComponent, StockGroup
from app.services import integrations
from app.services.stock_keys import scope_applies

LOW_STOCK_KEY = "warehouse.low_stock"
DEFAULT_LOW_STOCK = 3
MAX_LOW_STOCK = 1000


async def low_stock_threshold(session: AsyncSession) -> int:
    """Порог «мало», шт. Мусор или отрицательное в настройках — значение по умолчанию."""
    raw = await integrations.get(session, LOW_STOCK_KEY)
    try:
        value = int((raw or "").strip())
    except ValueError:
        return DEFAULT_LOW_STOCK
    return value if 0 <= value <= MAX_LOW_STOCK else DEFAULT_LOW_STOCK


def classify(sellable: dict[str, int], used: list[str], threshold: int) -> tuple[bool, bool]:
    """(low, out) по тем цветам пластины, что реально продаются. Без продаж — не помечаем."""
    if not used:
        return False, False
    counts = [sellable[p] for p in used]
    out = any(c == 0 for c in counts)
    low = (not out) and any(c <= threshold for c in counts)
    return low, out


async def availability(session: AsyncSession) -> dict:
    threshold = await low_stock_threshold(session)

    qty: dict[tuple[str, str, str | None], int] = {
        (c.kind, c.model_name, c.plate_type): c.qty
        for c in (await session.scalars(select(StockComponent))).all()
    }
    models = (
        await session.execute(
            select(IphoneModel.name, StockGroup.name, StockGroup.scope)
            .outerjoin(StockGroup, StockGroup.id == IphoneModel.stock_group_id)
            .order_by(IphoneModel.sort_order, IphoneModel.id)
        )
    ).all()
    plates_used: dict[str, set[str]] = {}
    for model_name, plate in (
        await session.execute(
            select(CaseTypeModel.model_name, CaseType.plate_type)
            .join(CaseType, CaseType.id == CaseTypeModel.case_type_id)
            .where(CaseType.is_active.is_(True), CaseTypeModel.is_available.is_(True))
        )
    ).all():
        plates_used.setdefault(model_name, set()).add(plate or PlateType.BLACK)

    out_models: list[dict] = []
    low_count = out_count = 0
    for name, group, scope in models:
        def key(kind: str, name=name, group=group, scope=scope) -> str:
            return group if group and scope_applies(scope, kind) else name

        base = qty.get((StockKind.BASE, key(StockKind.BASE), None), 0)
        sellable = {
            plate: min(base, qty.get((StockKind.PLATE, key(StockKind.PLATE), plate), 0))
            for plate in (PlateType.BLACK, PlateType.SILVER)
        }
        used = sorted(plates_used.get(name, set()))
        low, out = classify(sellable, used, threshold)
        low_count += low
        out_count += out
        out_models.append(
            {
                "model_name": name,
                "group_name": group,
                "black": sellable[PlateType.BLACK],
                "silver": sellable[PlateType.SILVER],
                "used_plates": used,
                "low": low,
                "out": out,
            }
        )
    return {"threshold": threshold, "models": out_models, "low": low_count, "out": out_count}
