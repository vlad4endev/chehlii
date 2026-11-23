"""Склад балванок и пластин: поставки, брак, списание под заказ, закупка.

Доступно к продаже (тип × модель) = min(base для модели, plate для модели+plate_type).
`case_type_models.stock` — денормализованный кэш available (мини-апп/боты без переписывания).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PlateType, StockKind, StockMovementReason
from app.models.admin_user import AdminUser
from app.models.catalog import CaseType, CaseTypeModel, IphoneModel
from app.models.order import Order
from app.models.warehouse import StockComponent, StockGroup, StockMovement
from app.services import integrations
from app.services.stock_keys import (
    members_by_group_name,
    models_for_key,
    scope_applies,
    stock_key,
)

# Предел одной операции: больше не нужно складу и безопасно для колонки INTEGER.
MAX_QTY = 1_000_000

log = logging.getLogger(__name__)

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


async def ensure_components_for_model(session: AsyncSession, model: str) -> None:
    """Идемпотентно создать base + silver/black plate для одной модели (qty 0).

    Для модели из группы «универсальных» создаются позиции группы, а не модели."""
    base_key = await stock_key(session, StockKind.BASE, model)
    plate_key = await stock_key(session, StockKind.PLATE, model)
    existing = {
        (c.kind, c.model_name, c.plate_type)
        for c in (
            await session.scalars(
                select(StockComponent).where(StockComponent.model_name.in_({base_key, plate_key}))
            )
        ).all()
    }
    if (StockKind.BASE, base_key, None) not in existing:
        session.add(
            StockComponent(kind=StockKind.BASE, model_name=base_key, plate_type=None, qty=0)
        )
    for plate in (PlateType.SILVER, PlateType.BLACK):
        if (StockKind.PLATE, plate_key, plate) not in existing:
            session.add(
                StockComponent(kind=StockKind.PLATE, model_name=plate_key, plate_type=plate, qty=0)
            )
    await session.flush()


async def ensure_components(session: AsyncSession) -> None:
    """Идемпотентно создать недостающие base + silver/black plate для всех моделей из канона.

    Один проход вместо запросов на каждую модель: читаем модели с группами и все позиции
    разом, недостающие добавляем одним INSERT … ON CONFLICT DO NOTHING (qty 0).
    У модели из «универсальной» группы нужна позиция группы, а не модели."""
    # Локальный импорт: iphone_models → warehouse, избегаем цикла на уровне модуля.
    from app.services import iphone_models as im

    await im.ensure_seeded(session)
    models = (
        await session.execute(
            select(IphoneModel.name, StockGroup.name, StockGroup.scope)
            .outerjoin(StockGroup, StockGroup.id == IphoneModel.stock_group_id)
        )
    ).all()
    wanted: set[tuple[str, str, str | None]] = set()
    for name, group, scope in models:
        base_key = group if group and scope_applies(scope, StockKind.BASE) else name
        plate_key = group if group and scope_applies(scope, StockKind.PLATE) else name
        wanted.add((StockKind.BASE, base_key, None))
        wanted.add((StockKind.PLATE, plate_key, PlateType.SILVER))
        wanted.add((StockKind.PLATE, plate_key, PlateType.BLACK))

    existing = {
        (c.kind, c.model_name, c.plate_type)
        for c in (await session.scalars(select(StockComponent))).all()
    }
    missing = wanted - existing
    if missing:
        await session.execute(
            pg_insert(StockComponent)
            .values([
                {"kind": k, "model_name": m, "plate_type": p, "qty": 0}
                for k, m, p in sorted(missing, key=lambda t: (t[1], t[0], t[2] or ""))
            ])
            .on_conflict_do_nothing()
        )


async def get_component(
    session: AsyncSession,
    kind: str,
    model_name: str,
    plate_type: str | None = None,
    *,
    create: bool = True,
) -> StockComponent:
    """Найти компонент; при create — создать с qty=0.

    model_name — модель или ключ группы: для модели из группы остаток общий."""
    model_name = await stock_key(session, kind, model_name)
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
    # Два запроса могут создавать одну позицию одновременно: уникальный индекс не даст
    # дубль, а «проигравший» просто читает созданную победителем строку.
    await session.execute(
        pg_insert(StockComponent)
        .values(kind=kind, model_name=model_name, plate_type=plate, qty=0)
        .on_conflict_do_nothing()
    )
    return await session.scalar(stmt.execution_options(populate_existing=True))


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
    """Обновить case_type_models.stock для всех типов с этой моделью.

    model_name — модель или ключ группы: у группы остаток общий, поэтому обновляем все её модели."""
    for model in await models_for_key(session, model_name):
        rows = (
            await session.execute(
                select(CaseTypeModel, CaseType.plate_type)
                .join(CaseType, CaseType.id == CaseTypeModel.case_type_id)
                .where(CaseTypeModel.model_name == model)
            )
        ).all()
        for ctm, plate_type in rows:
            ctm.stock = await available_for_sale(session, model_name=model, plate_type=plate_type)


async def _ensure_known_model(session: AsyncSession, model_name: str) -> None:
    """Приход и брак принимают только модель из справочника или имя группы — без «Nokia 3310»."""
    known = await session.scalar(select(IphoneModel.id).where(IphoneModel.name == model_name))
    if known is None:
        known = await session.scalar(select(StockGroup.id).where(StockGroup.name == model_name))
    if known is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Такой модели нет в справочнике: {model_name}. Добавьте её через «+ Позиция».",
        )


_KIND_RU = {StockKind.BASE: "Балванка", StockKind.PLATE: "Пластина"}
_PLATE_RU = {PlateType.SILVER: "серебро", PlateType.BLACK: "чёрная"}


def position_label(component: StockComponent) -> str:
    """«Пластина · iPhone 15 · чёрная» — для сообщений пользователю (без base/plate)."""
    parts = [_KIND_RU.get(component.kind, component.kind), component.model_name]
    if component.plate_type:
        parts.append(_PLATE_RU.get(component.plate_type, component.plate_type))
    return " · ".join(parts)


def _check_qty(qty: int, *, allow_zero: bool = False) -> None:
    if qty < (0 if allow_zero else 1):
        text = "не может быть отрицательным" if allow_zero else "должно быть больше 0"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Количество {text}")
    if qty > MAX_QTY:
        limit = f"{MAX_QTY:,}".replace(",", " ")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Слишком большое количество (максимум {limit})"
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
    """Изменить остаток и записать движение.

    Остаток меняется одним UPDATE «qty = qty + delta» с условием «не уйти в минус»: строка
    блокируется до конца транзакции, параллельные операции встают в очередь и считают от
    актуального значения. Чтение остатка в Python и запись готового числа теряли операции."""
    result = await session.execute(
        update(StockComponent)
        .where(StockComponent.id == component.id, StockComponent.qty + delta >= 0)
        .values(qty=StockComponent.qty + delta)
        .returning(StockComponent.qty)
    )
    if result.first() is None:
        await session.refresh(component, ["qty"])
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Недостаточно на складе: {position_label(component)} — "
            f"есть {component.qty}, нужно {abs(delta)}",
        )
    # Подтянуть актуальное значение в объект, не помечая его изменённым (иначе flush
    # записал бы старое число поверх чужого обновления).
    await session.refresh(component, ["qty"])
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
    _check_qty(qty)
    if kind not in (StockKind.BASE, StockKind.PLATE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind: base|plate")
    await _ensure_known_model(session, model_name)
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
    _check_qty(qty)
    if reason not in DEFECT_REASONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "reason: defect_supplier|defect_print|defect_glue",
        )
    if kind not in (StockKind.BASE, StockKind.PLATE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind: base|plate")
    await _ensure_known_model(session, model_name)
    component = await get_component(session, kind, model_name, plate_type, create=True)
    return await _apply_delta(
        session,
        component,
        -qty,
        reason,
        comment=comment,
        admin_user_id=admin_user_id,
    )


async def set_qty(
    session: AsyncSession,
    component_id: int,
    qty: int,
    *,
    comment: str | None = None,
    admin_user_id: int | None = None,
) -> StockMovement | None:
    """Выставить абсолютный остаток (инвентаризация). Пишет движение reason=adjust."""
    _check_qty(qty, allow_zero=True)
    # Блокируем строку: разница считается от актуального остатка, а не от прочитанного ранее.
    component = await session.get(
        StockComponent, component_id, with_for_update=True, populate_existing=True
    )
    if component is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    delta = qty - component.qty
    if delta == 0:
        return None
    return await _apply_delta(
        session,
        component,
        delta,
        StockMovementReason.ADJUST,
        comment=comment or f"Корректировка → {qty}",
        admin_user_id=admin_user_id,
    )


async def create_position(
    session: AsyncSession,
    *,
    kind: str,
    model_name: str,
    plate_type: str | None = None,
    qty: int = 0,
    comment: str | None = None,
    admin_user_id: int | None = None,
    register_canon: bool = True,
) -> StockComponent:
    """Создать складскую позицию (если ещё нет). Опционально — в канон моделей iPhone."""
    from app.services import iphone_models as im

    if kind not in (StockKind.BASE, StockKind.PLATE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind: base|plate")
    _check_qty(qty, allow_zero=True)

    name = im.normalize_iphone_model_name(model_name)
    if kind == StockKind.PLATE:
        plate = _normalize_plate(plate_type)
    else:
        plate = None

    if register_canon:
        canon = await im.list_model_names(session)
        if name not in canon:
            # Без enable_on_all: только канон + склад; в типах чехлов — вручную.
            await im.add_model(session, name, enable_on_all=False)
        else:
            await ensure_components_for_model(session, name)
    else:
        await ensure_components_for_model(session, name)

    # После ensure у модели уже есть base + обе пластины; берём нужную.
    try:
        component = await get_component(session, kind, name, plate, create=False)
    except HTTPException:
        component = await get_component(session, kind, name, plate, create=True)

    if qty > 0 and component.qty != qty:
        await set_qty(
            session,
            component.id,
            qty,
            comment=comment or "Начальный остаток",
            admin_user_id=admin_user_id,
        )
        await session.refresh(component)
    return component


async def deduct_for_order(session: AsyncSession, order: Order) -> bool:
    """Списать 1 балванку + 1 пластину типа чехла. Идемпотентность — Order.stock_deducted.

    True — склад списан (сейчас или раньше); False — не хватило остатка или нечего списывать.
    Пара списывается целиком: если не хватило любой из двух, не списывается ни одна."""
    if order.stock_deducted:
        return True
    if order.case_type_id is None or not order.model_name:
        return False
    case_type = await session.get(CaseType, order.case_type_id)
    if case_type is None:
        return False
    plate = _normalize_plate(case_type.plate_type)
    base = await get_component(session, StockKind.BASE, order.model_name, create=True)
    plate_row = await get_component(
        session, StockKind.PLATE, order.model_name, plate, create=True
    )
    try:
        # Две проверки «хватает ли» делает сам UPDATE; savepoint откатывает первую, если
        # вторая не прошла, и не трогает остальную транзакцию (платёж, статус заказа).
        async with session.begin_nested():
            for component in (base, plate_row):
                await _apply_delta(
                    session,
                    component,
                    -1,
                    StockMovementReason.ORDER,
                    order_id=order.id,
                    comment=f"Заказ #{order.id}",
                )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_409_CONFLICT:
            raise
        log.warning("Заказ #%s оплачен, но на складе не хватило остатка для списания", order.id)
        return False
    order.stock_deducted = True
    return True


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
    members = await members_by_group_name(session)
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "model_name": c.model_name,
            "plate_type": c.plate_type,
            "qty": c.qty,
            # Пусто у обычной модели; у группы — какие модели делят этот остаток.
            "members": members.get(c.model_name, []),
        }
        for c in rows
    ]


@dataclass(frozen=True)
class MovementFilter:
    """Условия отбора журнала движений; пустое условие не ограничивает выдачу."""

    model: str | None = None  # часть названия модели или группы
    kind: str | None = None
    reason: str | None = None
    order_id: int | None = None
    date_from: date | None = None  # включительно, по UTC
    date_to: date | None = None  # включительно, по UTC


def _movement_query(flt: MovementFilter):
    stmt = (
        select(
            StockMovement,
            StockComponent,
            AdminUser.full_name,
            AdminUser.email,
        )
        .join(StockComponent, StockComponent.id == StockMovement.component_id)
        .outerjoin(AdminUser, AdminUser.id == StockMovement.admin_user_id)
    )
    if flt.model:
        needle = flt.model.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        # Модель из «универсальной» группы лежит в журнале под именем группы — ищем и по ней.
        in_group = (
            select(StockGroup.name)
            .join(IphoneModel, IphoneModel.stock_group_id == StockGroup.id)
            .where(IphoneModel.name.ilike(pattern, escape="\\"))
        )
        stmt = stmt.where(
            or_(
                StockComponent.model_name.ilike(pattern, escape="\\"),
                StockComponent.model_name.in_(in_group),
            )
        )
    if flt.kind:
        stmt = stmt.where(StockComponent.kind == flt.kind)
    if flt.reason:
        stmt = stmt.where(StockMovement.reason == flt.reason)
    if flt.order_id is not None:
        stmt = stmt.where(StockMovement.order_id == flt.order_id)
    if flt.date_from:
        start = datetime.combine(flt.date_from, time.min, tzinfo=UTC)
        stmt = stmt.where(StockMovement.created_at >= start)
    if flt.date_to:
        end = datetime.combine(flt.date_to, time.min, tzinfo=UTC) + timedelta(days=1)
        stmt = stmt.where(StockMovement.created_at < end)
    return stmt


def _movement_row(movement, component, full_name, email) -> dict:
    return {
        "id": movement.id,
        "component_id": movement.component_id,
        "kind": component.kind,
        "model_name": component.model_name,
        "plate_type": component.plate_type,
        "delta": movement.delta,
        "reason": movement.reason,
        "comment": movement.comment,
        "order_id": movement.order_id,
        "admin_user_id": movement.admin_user_id,
        # Кто сделал: имя, а если не заполнено — почта; пусто у системных операций (заказ).
        "admin_name": (full_name or email) if movement.admin_user_id else None,
        "created_at": movement.created_at,
    }


async def list_movements(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    flt: MovementFilter | None = None,
) -> tuple[list[dict], int]:
    """Журнал движений с позицией и автором; новые первыми. total — под тем же отбором."""
    stmt = _movement_query(flt or MovementFilter())
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (
        await session.execute(
            stmt.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_movement_row(*r) for r in rows], int(total or 0)


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
    since = datetime.now(UTC) - timedelta(days=n)
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
