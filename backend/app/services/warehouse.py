"""Склад балванок и пластин: поставки, брак, списание под заказ, закупка.

Доступно к продаже (тип × модель) = min(base для модели, plate для модели+plate_type).
`case_type_models.stock` — денормализованный кэш available (мини-апп/боты без переписывания).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import IPHONE_MODELS
from app.enums import PlateType, StockKind, StockMovementReason
from app.models.catalog import CaseType, CaseTypeModel
from app.models.order import Order
from app.models.warehouse import StockComponent, StockMovement
from app.services import integrations

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_LEAD_DAYS = 14
DEFAULT_SAFETY_DAYS = 7

DEFECT_REASONS = frozenset(
    {
        StockMovementReason.DEFECT_SUPPLIER,
        StockMovementReason.DEFECT_PRINT,
        StockMovementReason.DEFECT_GLUE,
    }
)


def _normalize_plate(plate_type: str | None) -> str:
    """Тип пластины чехла: пустое → black."""
    if not plate_type:
        return PlateType.BLACK
    return plate_type


async def ensure_components(session: AsyncSession) -> None:
    """Идемпотентно создать base + silver/black plate для всех IPHONE_MODELS (qty 0)."""
    existing = {
        (c.kind, c.model_name, c.plate_type)
        for c in (
            await session.scalars(select(StockComponent))
        ).all()
    }
    for model in IPHONE_MODELS:
        if (StockKind.BASE, model, None) not in existing:
            session.add(
                StockComponent(kind=StockKind.BASE, model_name=model, plate_type=None, qty=0)
            )
        for plate in (PlateType.SILVER, PlateType.BLACK):
            if (StockKind.PLATE, model, plate) not in existing:
                session.add(
                    StockComponent(
                        kind=StockKind.PLATE, model_name=model, plate_type=plate, qty=0
                    )
                )
    await session.flush()


async def get_component(
    session: AsyncSession,
    kind: str,
    model_name: str,
    plate_type: str | None = None,
    *,
    create: bool = True,
) -> StockComponent:
    """Найти компонент; при create — создать с qty=0."""
    plate = None if kind == StockKind.BASE else plate_type
    if kind == StockKind.PLATE and plate not in (PlateType.SILVER, PlateType.BLACK):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для пластины укажите plate_type: silver|black")
    if kind == StockKind.BASE:
        plate = None

    stmt = select(StockComponent).where(
        StockComponent.kind == kind,
        StockComponent.model_name == model_name,
    )
    if plate is None:
        stmt = stmt.where(StockComponent.plate_type.is_(None))
    else:
        stmt = stmt.where(StockComponent.plate_type == plate)

    row = await session.scalar(stmt)
    if row is not None:
        return row
    if not create:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компонент не найден")
    row = StockComponent(kind=kind, model_name=model_name, plate_type=plate, qty=0)
    session.add(row)
    await session.flush()
    return row


async def available_for_sale(
    session: AsyncSession,
    *,
    model_name: str,
    plate_type: str | None,
) -> int:
    """min(base qty, plate qty для plate_type чехла)."""
    plate = _normalize_plate(plate_type)
    base = await get_component(session, StockKind.BASE, model_name, create=True)
    plate_row = await get_component(session, StockKind.PLATE, model_name, plate, create=True)
    return max(0, min(base.qty, plate_row.qty))


async def sync_legacy_stock(session: AsyncSession, model_name: str) -> None:
    """Обновить case_type_models.stock для всех типов с этой моделью."""
    rows = (
        await session.execute(
            select(CaseTypeModel, CaseType.plate_type)
            .join(CaseType, CaseType.id == CaseTypeModel.case_type_id)
            .where(CaseTypeModel.model_name == model_name)
        )
    ).all()
    for ctm, plate_type in rows:
        ctm.stock = await available_for_sale(
            session, model_name=model_name, plate_type=plate_type
        )


async def _apply_delta(
    session: AsyncSession,
    component: StockComponent,
    delta: int,
    reason: str,
    *,
    comment: str | None = None,
    order_id: int | None = None,
    admin_user_id: int | None = None,
) -> StockMovement:
    new_qty = component.qty + delta
    if new_qty < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Недостаточно на складе ({component.kind} {component.model_name}"
            f"{'/' + component.plate_type if component.plate_type else ''}): "
            f"есть {component.qty}, нужно {abs(delta)}",
        )
    component.qty = new_qty
    mov = StockMovement(
        component_id=component.id,
        delta=delta,
        reason=reason,
        comment=comment,
        order_id=order_id,
        admin_user_id=admin_user_id,
    )
    session.add(mov)
    await session.flush()
    await sync_legacy_stock(session, component.model_name)
    return mov


async def supply(
    session: AsyncSession,
    *,
    kind: str,
    model_name: str,
    qty: int,
    plate_type: str | None = None,
    comment: str | None = None,
    admin_user_id: int | None = None,
) -> StockMovement:
    if qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "qty должен быть > 0")
    if kind not in (StockKind.BASE, StockKind.PLATE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind: base|plate")
    component = await get_component(session, kind, model_name, plate_type, create=True)
    return await _apply_delta(
        session,
        component,
        qty,
        StockMovementReason.SUPPLY,
        comment=comment,
        admin_user_id=admin_user_id,
    )


async def write_off_defect(
    session: AsyncSession,
    *,
    kind: str,
    model_name: str,
    qty: int,
    reason: str,
    plate_type: str | None = None,
    comment: str | None = None,
    admin_user_id: int | None = None,
) -> StockMovement:
    if qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "qty должен быть > 0")
    if reason not in DEFECT_REASONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "reason: defect_supplier|defect_print|defect_glue",
        )
    if kind not in (StockKind.BASE, StockKind.PLATE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind: base|plate")
    component = await get_component(session, kind, model_name, plate_type, create=True)
    return await _apply_delta(
        session,
        component,
        -qty,
        reason,
        comment=comment,
        admin_user_id=admin_user_id,
    )


async def deduct_for_order(session: AsyncSession, order: Order) -> None:
    """Списать 1 балванку + 1 пластину типа чехла. Идемпотентность — Order.stock_deducted."""
    if order.stock_deducted:
        return
    if order.case_type_id is None or not order.model_name:
        return
    case_type = await session.get(CaseType, order.case_type_id)
    if case_type is None:
        return
    plate = _normalize_plate(case_type.plate_type)
    base = await get_component(session, StockKind.BASE, order.model_name, create=True)
    plate_row = await get_component(
        session, StockKind.PLATE, order.model_name, plate, create=True
    )
    # Не уходим в минус: как раньше при stock > 0 — тихо пропускаем, если нет остатка.
    if base.qty < 1 or plate_row.qty < 1:
        return
    await _apply_delta(
        session,
        base,
        -1,
        StockMovementReason.ORDER,
        order_id=order.id,
        comment=f"Заказ #{order.id}",
    )
    await _apply_delta(
        session,
        plate_row,
        -1,
        StockMovementReason.ORDER,
        order_id=order.id,
        comment=f"Заказ #{order.id}",
    )
    order.stock_deducted = True


async def restore_for_order(session: AsyncSession, order: Order) -> None:
    """Вернуть 1 base + 1 plate, если ранее списали."""
    if not order.stock_deducted:
        return
    if order.case_type_id is None or not order.model_name:
        return
    case_type = await session.get(CaseType, order.case_type_id)
    if case_type is None:
        return
    plate = _normalize_plate(case_type.plate_type)
    base = await get_component(session, StockKind.BASE, order.model_name, create=True)
    plate_row = await get_component(
        session, StockKind.PLATE, order.model_name, plate, create=True
    )
    await _apply_delta(
        session,
        base,
        1,
        StockMovementReason.ORDER,
        order_id=order.id,
        comment=f"Отмена заказа #{order.id}",
    )
    await _apply_delta(
        session,
        plate_row,
        1,
        StockMovementReason.ORDER,
        order_id=order.id,
        comment=f"Отмена заказа #{order.id}",
    )
    order.stock_deducted = False


async def list_components(session: AsyncSession) -> list[dict]:
    """Список компонентов с available (для base — min с каждой пластиной не нужен; qty сам)."""
    await ensure_components(session)
    rows = (
        await session.scalars(
            select(StockComponent).order_by(
                StockComponent.model_name, StockComponent.kind, StockComponent.plate_type
            )
        )
    ).all()
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "model_name": c.model_name,
            "plate_type": c.plate_type,
            "qty": c.qty,
        }
        for c in rows
    ]


async def list_movements(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[StockMovement], int]:
    total = await session.scalar(select(func.count(StockMovement.id))) or 0
    rows = (
        await session.scalars(
            select(StockMovement)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), total


async def _setting_int(session: AsyncSession, key: str, default: int) -> int:
    raw = await integrations.get(session, key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


async def purchase_settings(session: AsyncSession) -> dict[str, int]:
    return {
        "lookback_days": await _setting_int(
            session, "warehouse.lookback_days", DEFAULT_LOOKBACK_DAYS
        ),
        "lead_days": await _setting_int(session, "warehouse.lead_days", DEFAULT_LEAD_DAYS),
        "safety_days": await _setting_int(
            session, "warehouse.safety_days", DEFAULT_SAFETY_DAYS
        ),
    }


async def purchase_suggestion(session: AsyncSession) -> list[dict]:
    """spend_per_day = (sold + defect) / N; recommend = max(0, ceil(spd*(lead+safety)) - stock)."""
    await ensure_components(session)
    cfg = await purchase_settings(session)
    n = max(1, cfg["lookback_days"])
    since = datetime.now(timezone.utc) - timedelta(days=n)
    horizon = cfg["lead_days"] + cfg["safety_days"]

    # Расход: отрицательные дельты по order + defect_* за период.
    spent_rows = (
        await session.execute(
            select(
                StockComponent.id,
                StockComponent.kind,
                StockComponent.model_name,
                StockComponent.plate_type,
                StockComponent.qty,
                func.coalesce(func.sum(-StockMovement.delta), 0),
            )
            .outerjoin(
                StockMovement,
                and_(
                    StockMovement.component_id == StockComponent.id,
                    StockMovement.created_at >= since,
                    StockMovement.delta < 0,
                    or_(
                        StockMovement.reason == StockMovementReason.ORDER,
                        StockMovement.reason.in_(list(DEFECT_REASONS)),
                    ),
                ),
            )
            .group_by(
                StockComponent.id,
                StockComponent.kind,
                StockComponent.model_name,
                StockComponent.plate_type,
                StockComponent.qty,
            )
            .order_by(StockComponent.model_name, StockComponent.kind, StockComponent.plate_type)
        )
    ).all()

    out: list[dict] = []
    for cid, kind, model, plate, qty, spent in spent_rows:
        spend_per_day = float(spent) / n
        recommend = max(0, math.ceil(spend_per_day * horizon) - int(qty))
        out.append(
            {
                "component_id": cid,
                "kind": kind,
                "model_name": model,
                "plate_type": plate,
                "stock": int(qty),
                "spent_lookback": int(spent),
                "spend_per_day": round(spend_per_day, 4),
                "recommend": recommend,
                "lookback_days": n,
                "lead_days": cfg["lead_days"],
                "safety_days": cfg["safety_days"],
            }
        )
    return out
