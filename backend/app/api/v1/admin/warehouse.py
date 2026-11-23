"""Склад (AdminUI): компоненты, поставки, брак, движения, расчёт закупки.

Доступ: Админ и Печатник — остатки, движения, поставки и брак.
Только Админ: создание позиции, ручная корректировка остатка, расчёт закупки.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.api.v1.admin.deps import AdminOnly, WarehouseStaff
from app.core.database import get_session
from app.enums import PlateType, StockGroupScope, StockKind, StockMovementReason
from app.models.warehouse import StockComponent, StockMovement
from app.services import iphone_models as im
from app.services import stock_availability as sa
from app.services import stock_groups as sg
from app.services import stock_pending as sp
from app.services import warehouse as wh

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


class ComponentOut(BaseModel):
    id: int
    kind: str
    model_name: str
    plate_type: str | None
    qty: int
    # Для UI: «доступно» = текущий qty компонента (available считается на паре base×plate).
    available: int
    # Модели, которые делят этот остаток («универсальная» группа); у обычной модели пусто.
    members: list[str] = []


class InventoryItemIn(BaseModel):
    component_id: int = Field(ge=1)
    qty: int = Field(ge=0, le=wh.MAX_QTY)


class InventoryIn(BaseModel):
    items: list[InventoryItemIn] = Field(min_length=1, max_length=wh.MAX_INVENTORY_ITEMS)
    comment: str | None = Field(default=None, max_length=200)


class InventoryChangeOut(BaseModel):
    component_id: int
    before: int
    after: int


class InventoryOut(BaseModel):
    changed: int
    unchanged: int
    items: list[InventoryChangeOut]


class ReverseIn(BaseModel):
    comment: str | None = Field(default=None, max_length=200)


class PendingOrderOut(BaseModel):
    order_id: int
    status: str
    model_name: str
    case_name: str
    plate_type: str
    is_custom: bool
    created_at: datetime
    can_deduct: bool


class DeductAllOut(BaseModel):
    deducted: int
    remaining: int


class AvailabilityRow(BaseModel):
    model_name: str
    group_name: str | None
    black: int
    silver: int
    used_plates: list[str]
    low: bool
    out: bool


class AvailabilityOut(BaseModel):
    threshold: int
    models: list[AvailabilityRow]
    low: int
    out: int


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: StockGroupScope = StockGroupScope.BOTH
    models: list[str]


class GroupOut(BaseModel):
    id: int
    name: str
    scope: StockGroupScope
    models: list[str]


class SupplyIn(BaseModel):
    kind: StockKind
    model_name: str = Field(min_length=1, max_length=64)
    plate_type: PlateType | None = None
    qty: int = Field(gt=0, le=wh.MAX_QTY)
    comment: str | None = None


class DefectIn(BaseModel):
    kind: StockKind
    model_name: str = Field(min_length=1, max_length=64)
    plate_type: PlateType | None = None
    qty: int = Field(gt=0, le=wh.MAX_QTY)
    reason: StockMovementReason
    comment: str | None = None


class ComponentCreateIn(BaseModel):
    kind: StockKind
    model_name: str = Field(min_length=1, max_length=64)
    plate_type: PlateType | None = None
    qty: int = Field(default=0, ge=0, le=wh.MAX_QTY)
    comment: str | None = None
    # Если модели нет в каноне — добавить (без авто-включения во все типы).
    register_canon: bool = True


class ComponentAdjustIn(BaseModel):
    qty: int = Field(ge=0, le=wh.MAX_QTY)
    comment: str | None = None


class MovementOut(BaseModel):
    id: int
    component_id: int
    kind: str
    model_name: str
    plate_type: str | None
    delta: int
    reason: str
    comment: str | None
    order_id: int | None
    admin_user_id: int | None
    admin_name: str | None = None
    # Эта запись отменяет запись с таким id (сторно)
    reverses_id: int | None = None
    # Эту запись отменила запись с таким id — в журнале помечается «отменено»
    reversed_by_id: int | None = None
    created_at: datetime


class MovementsPage(BaseModel):
    items: list[MovementOut]
    total: int
    limit: int
    offset: int


class PurchaseRow(BaseModel):
    component_id: int
    kind: str
    model_name: str
    plate_type: str | None
    stock: int
    spent_lookback: int
    spend_per_day: float
    recommend: int
    lookback_days: int
    lead_days: int
    safety_days: int


class PurchaseOut(BaseModel):
    settings: dict[str, int]
    items: list[PurchaseRow]


def _component_out(c: dict) -> ComponentOut:
    return ComponentOut(
        id=c["id"],
        kind=c["kind"],
        model_name=c["model_name"],
        plate_type=c["plate_type"],
        qty=c["qty"],
        available=c["qty"],
        members=c.get("members", []),
    )


@router.get("/models", response_model=list[str])
async def list_models(_: WarehouseStaff, session: Session) -> list[str]:
    """Модели iPhone для форм склада. Свой эндпоинт: каталожный закрыт для печатника."""
    return await im.list_model_names(session)


@router.get("/components", response_model=list[ComponentOut])
async def list_components(_: WarehouseStaff, session: Session) -> list[ComponentOut]:
    rows = await wh.list_components(session)
    await session.commit()
    return [_component_out(r) for r in rows]


@router.post("/components", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
async def create_component(
    body: ComponentCreateIn,
    admin: AdminOnly,
    session: Session,
) -> ComponentOut:
    c = await wh.create_position(
        session,
        kind=body.kind,
        model_name=body.model_name,
        plate_type=body.plate_type,
        qty=body.qty,
        comment=body.comment,
        admin_user_id=admin.id,
        register_canon=body.register_canon,
    )
    await session.commit()
    await session.refresh(c)
    return ComponentOut(
        id=c.id,
        kind=c.kind,
        model_name=c.model_name,
        plate_type=c.plate_type,
        qty=c.qty,
        available=c.qty,
    )


@router.patch("/components/{component_id}", response_model=ComponentOut)
async def adjust_component(
    component_id: int,
    body: ComponentAdjustIn,
    admin: AdminOnly,
    session: Session,
) -> ComponentOut:
    await wh.set_qty(
        session,
        component_id,
        body.qty,
        comment=body.comment,
        admin_user_id=admin.id,
    )
    await session.commit()
    c = await session.get(StockComponent, component_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    return ComponentOut(
        id=c.id,
        kind=c.kind,
        model_name=c.model_name,
        plate_type=c.plate_type,
        qty=c.qty,
        available=c.qty,
    )


@router.post("/supply", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
async def post_supply(body: SupplyIn, admin: WarehouseStaff, session: Session) -> MovementOut:
    mov = await wh.supply(
        session,
        kind=body.kind,
        model_name=body.model_name,
        qty=body.qty,
        plate_type=body.plate_type,
        comment=body.comment,
        admin_user_id=admin.id,
    )
    await session.commit()
    return await _movement_out(session, mov.id)


@router.post("/defect", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
async def post_defect(body: DefectIn, admin: WarehouseStaff, session: Session) -> MovementOut:
    mov = await wh.write_off_defect(
        session,
        kind=body.kind,
        model_name=body.model_name,
        qty=body.qty,
        reason=body.reason,
        plate_type=body.plate_type,
        comment=body.comment,
        admin_user_id=admin.id,
    )
    await session.commit()
    return await _movement_out(session, mov.id)


def _movement_filter(
    model: str | None,
    kind: StockKind | None,
    reason: StockMovementReason | None,
    order_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> wh.MovementFilter:
    return wh.MovementFilter(
        model=(model or "").strip() or None,
        kind=kind,
        reason=reason,
        order_id=order_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/movements", response_model=MovementsPage)
async def get_movements(
    _: WarehouseStaff,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    model: Annotated[str | None, Query(max_length=64)] = None,
    kind: StockKind | None = None,
    reason: StockMovementReason | None = None,
    order_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> MovementsPage:
    """Журнал движений: новые первыми, с фильтрами и автором операции."""
    flt = _movement_filter(model, kind, reason, order_id, date_from, date_to)
    rows, total = await wh.list_movements(session, limit=limit, offset=offset, flt=flt)
    return MovementsPage(
        items=[MovementOut(**r) for r in rows], total=total, limit=limit, offset=offset
    )


MAX_EXPORT_ROWS = 20_000


@router.get("/movements/export.xlsx")
async def export_movements(
    _: WarehouseStaff,
    session: Session,
    model: Annotated[str | None, Query(max_length=64)] = None,
    kind: StockKind | None = None,
    reason: StockMovementReason | None = None,
    order_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    """Журнал в Excel — с теми же фильтрами, что на экране (не больше 20 000 строк)."""
    from openpyxl import Workbook

    flt = _movement_filter(model, kind, reason, order_id, date_from, date_to)
    rows, total = await wh.list_movements(session, limit=MAX_EXPORT_ROWS, offset=0, flt=flt)
    wb = Workbook()
    ws = wb.active
    ws.title = "Движения"
    ws.append(
        ["Когда (UTC)", "Вид", "Модель", "Пластина", "Δ", "Причина", "Кто", "Заказ", "Комментарий"]
    )
    kind_label = {StockKind.BASE: "Балванка", StockKind.PLATE: "Пластина"}
    plate_label = {PlateType.SILVER: "серебро", PlateType.BLACK: "чёрная"}
    reason_label = {
        StockMovementReason.SUPPLY: "Поставка",
        StockMovementReason.DEFECT_SUPPLIER: "Брак поставщика",
        StockMovementReason.DEFECT_PRINT: "Брак печати",
        StockMovementReason.DEFECT_GLUE: "Брак склейки",
        StockMovementReason.ORDER: "Заказ",
        StockMovementReason.ADJUST: "Корректировка",
    }
    for r in rows:
        ws.append(
            [
                r["created_at"].astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
                kind_label.get(r["kind"], r["kind"]),
                r["model_name"],
                plate_label.get(r["plate_type"], "—"),
                r["delta"],
                reason_label.get(r["reason"], r["reason"]),
                r["admin_name"] or "—",
                r["order_id"] or "",
                r["comment"] or "",
            ]
        )
    if total > len(rows):
        ws.append([])
        ws.append(
            [f"Показаны первые {len(rows)} из {total}: сузьте фильтры, чтобы выгрузить остальное."]
        )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="stock-movements.xlsx"'},
    )


@router.get("/purchase-suggestion", response_model=PurchaseOut)
async def get_purchase(_: AdminOnly, session: Session) -> PurchaseOut:
    items = await wh.purchase_suggestion(session)
    settings = await wh.purchase_settings(session)
    await session.commit()
    return PurchaseOut(settings=settings, items=[PurchaseRow(**i) for i in items])


@router.get("/purchase-suggestion/export.xlsx")
async def export_purchase(_: AdminOnly, session: Session) -> StreamingResponse:
    from openpyxl import Workbook

    items = await wh.purchase_suggestion(session)
    await session.commit()
    wb = Workbook()
    ws = wb.active
    ws.title = "Закупка"
    ws.append(
        [
            "Вид",
            "Модель",
            "Пластина",
            "Остаток",
            "Расход за N дн.",
            "В день",
            "Рекомендация",
            "N",
            "Lead",
            "Safety",
        ]
    )
    kind_label = {StockKind.BASE: "Балванка", StockKind.PLATE: "Пластина"}
    plate_label = {PlateType.SILVER: "серебро", PlateType.BLACK: "чёрная", None: "—"}
    for i in items:
        ws.append(
            [
                kind_label.get(i["kind"], i["kind"]),
                i["model_name"],
                plate_label.get(i["plate_type"], i["plate_type"] or "—"),
                i["stock"],
                i["spent_lookback"],
                i["spend_per_day"],
                i["recommend"],
                i["lookback_days"],
                i["lead_days"],
                i["safety_days"],
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="purchase.xlsx"'},
    )


async def _movement_out(session: AsyncSession, movement_id: int) -> MovementOut:
    mov = await session.scalar(
        select(StockMovement)
        .options(selectinload(StockMovement.component))
        .where(StockMovement.id == movement_id)
    )
    assert mov is not None
    c = mov.component
    return MovementOut(
        id=mov.id,
        component_id=mov.component_id,
        kind=c.kind,
        model_name=c.model_name,
        plate_type=c.plate_type,
        delta=mov.delta,
        reason=mov.reason,
        comment=mov.comment,
        order_id=mov.order_id,
        admin_user_id=mov.admin_user_id,
        created_at=mov.created_at,
    )


@router.get("/groups", response_model=list[GroupOut])
async def get_groups(_: AdminOnly, session: Session) -> list[dict]:
    return await sg.list_groups(session)


@router.post("/groups", response_model=GroupOut)
async def post_group(body: GroupIn, admin: AdminOnly, session: Session) -> dict:
    """Создать группу «универсальных» моделей или обновить состав существующей (по имени)."""
    out = await sg.save_group(
        session,
        name=body.name,
        scope=body.scope,
        models=body.models,
        admin_user_id=admin.id,
    )
    await session.commit()
    return out


@router.delete("/groups/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group(name: str, admin: AdminOnly, session: Session) -> None:
    """Распустить группу: остаток целиком достаётся первой модели группы."""
    await sg.delete_group(session, name, admin_user_id=admin.id)
    await session.commit()


@router.get("/pending-deductions", response_model=list[PendingOrderOut])
async def get_pending_deductions(_: WarehouseStaff, session: Session) -> list[dict]:
    """Оплаченные заказы, по которым склад не списан (не хватало остатка в момент оплаты)."""
    return await sp.list_pending(session)


@router.post("/pending-deductions/deduct-available", response_model=DeductAllOut)
async def post_deduct_available(_: WarehouseStaff, session: Session) -> dict[str, int]:
    """Списать все ожидающие заказы, на которые теперь хватает остатка."""
    out = await sp.deduct_available(session)
    await session.commit()
    return out


@router.post("/pending-deductions/{order_id}/deduct", response_model=DeductAllOut)
async def post_deduct_one(order_id: int, _: WarehouseStaff, session: Session) -> dict[str, int]:
    await sp.deduct_one(session, order_id)
    await session.commit()
    return {"deducted": 1, "remaining": await sp.pending_count(session)}


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(_: WarehouseStaff, session: Session) -> dict:
    """Сколько чехлов можно собрать по моделям и что заканчивается (порог — в Настройках)."""
    return await sa.availability(session)


@router.post("/movements/{movement_id}/reverse", response_model=MovementOut, status_code=201)
async def post_reverse_movement(
    movement_id: int, body: ReverseIn, admin: AdminOnly, session: Session
) -> MovementOut:
    """Отменить ошибочную запись журнала встречным движением (только админ)."""
    mov = await wh.reverse_movement(
        session, movement_id, admin_user_id=admin.id, comment=body.comment
    )
    await session.commit()
    rows, _ = await wh.list_movements(session, limit=1, flt=wh.MovementFilter(), only_id=mov.id)
    return MovementOut(**rows[0])


@router.post("/inventory", response_model=InventoryOut)
async def post_inventory(body: InventoryIn, admin: AdminOnly, session: Session) -> dict:
    """Инвентаризация: фактические остатки по многим позициям за один раз (только админ).

    Либо применяется всё, либо ничего; меняются только расходящиеся позиции."""
    out = await wh.apply_inventory(
        session,
        [(i.component_id, i.qty) for i in body.items],
        note=body.comment,
        admin_user_id=admin.id,
    )
    await session.commit()
    return out
