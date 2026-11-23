"""Группы «универсальных» моделей: одна балванка/пластина на несколько моделей iPhone.

Остаток группы лежит в stock_components под именем группы (см. services/stock_keys.py).
Операции здесь переносят остатки без потерь и сохраняют историю движений.
Коммит — на вызывающей стороне.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PlateType, StockGroupScope, StockKind, StockMovementReason
from app.models.catalog import IphoneModel
from app.models.warehouse import StockComponent, StockGroup, StockMovement
from app.services import warehouse as wh
from app.services.stock_keys import group_members, scope_applies

MAX_NAME_LEN = 64
MIN_MODELS = 2


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


def _kinds_for(scope: str) -> list[str]:
    return [k for k in (StockKind.BASE, StockKind.PLATE) if scope_applies(scope, k)]


def _plates_for(kind: str) -> list[str | None]:
    if kind == StockKind.BASE:
        return [None]
    return [PlateType.SILVER, PlateType.BLACK]


async def _find(
    session: AsyncSession, kind: str, key: str, plate: str | None
) -> StockComponent | None:
    stmt = select(StockComponent).where(
        StockComponent.kind == kind, StockComponent.model_name == key
    )
    stmt = stmt.where(
        StockComponent.plate_type.is_(None) if plate is None else StockComponent.plate_type == plate
    )
    return await session.scalar(stmt)


async def _get_or_create(
    session: AsyncSession, kind: str, key: str, plate: str | None
) -> StockComponent:
    row = await _find(session, kind, key, plate)
    if row is None:
        row = StockComponent(kind=kind, model_name=key, plate_type=plate, qty=0)
        session.add(row)
        await session.flush()
    return row


async def _move_stock(
    session: AsyncSession,
    source: StockComponent,
    target: StockComponent,
    *,
    comment: str,
    admin_user_id: int | None,
) -> None:
    """Перенести остаток и историю с source на target, source удалить (итог не меняется)."""
    qty = source.qty
    # История позиции переезжает вместе с ней — иначе удаление source стёрло бы её (CASCADE).
    await session.execute(
        update(StockMovement)
        .where(StockMovement.component_id == source.id)
        .values(component_id=target.id)
    )
    await session.execute(delete(StockComponent).where(StockComponent.id == source.id))
    session.expunge(source)  # строка удалена запросом — убрать из сессии
    if qty:
        await wh._apply_delta(
            session,
            target,
            qty,
            StockMovementReason.ADJUST,
            comment=comment,
            admin_user_id=admin_user_id,
        )


async def _models_by_name(session: AsyncSession, names: list[str]) -> dict[str, IphoneModel]:
    rows = (await session.scalars(select(IphoneModel).where(IphoneModel.name.in_(names)))).all()
    return {m.name: m for m in rows}


async def _sync_models(session: AsyncSession, models: list[str]) -> None:
    for name in models:
        await wh.sync_legacy_stock(session, name)


def group_out(group: StockGroup, members: list[str]) -> dict:
    return {"id": group.id, "name": group.name, "scope": group.scope, "models": members}


async def list_groups(session: AsyncSession) -> list[dict]:
    groups = (await session.scalars(select(StockGroup).order_by(StockGroup.name))).all()
    return [group_out(g, await group_members(session, g.id)) for g in groups]


async def _leave_group(session: AsyncSession, model: IphoneModel, group: StockGroup) -> None:
    """Модель выходит из группы: общий остаток остаётся группе, у модели свои позиции с нуля."""
    model.stock_group_id = None
    await session.flush()
    await wh.ensure_components_for_model(session, model.name)


async def _join_group(
    session: AsyncSession,
    model: IphoneModel,
    group: StockGroup,
    admin_user_id: int | None,
) -> None:
    """Модель входит в группу: её собственные остатки (по общим видам) добавляются к группе."""
    model.stock_group_id = group.id
    await session.flush()
    for kind in _kinds_for(group.scope):
        for plate in _plates_for(kind):
            own = await _find(session, kind, model.name, plate)
            if own is None:
                continue
            target = await _get_or_create(session, kind, group.name, plate)
            await _move_stock(
                session,
                own,
                target,
                comment=f"Объединение: {model.name} → «{group.name}»",
                admin_user_id=admin_user_id,
            )


async def save_group(
    session: AsyncSession,
    *,
    name: str,
    scope: str,
    models: list[str],
    admin_user_id: int | None = None,
) -> dict:
    """Создать группу или обновить состав существующей (по имени)."""
    name = " ".join((name or "").split())
    if not name:
        raise _bad_request("Укажите название группы")
    if len(name) > MAX_NAME_LEN:
        raise _bad_request(f"Название группы слишком длинное (макс. {MAX_NAME_LEN})")
    if scope not in {s.value for s in StockGroupScope}:
        raise _bad_request("scope: both|base|plate")
    wanted = list(dict.fromkeys(models))  # без дублей, порядок сохраняем
    if len(wanted) < MIN_MODELS:
        raise _bad_request("В группе должно быть минимум две модели")

    by_name = await _models_by_name(session, [*wanted, name])
    if name in by_name:
        raise _bad_request("Название группы совпадает с названием модели — выберите другое")
    unknown = [m for m in wanted if m not in by_name]
    if unknown:
        raise _bad_request(f"Нет таких моделей в справочнике: {', '.join(unknown)}")

    group = await session.scalar(select(StockGroup).where(StockGroup.name == name))
    if group is None:
        group = StockGroup(name=name, scope=scope)
        session.add(group)
        await session.flush()
    elif group.scope != scope:
        raise _bad_request("Область группы изменить нельзя — создайте новую группу")

    current = await group_members(session, group.id)
    leaving = [m for m in current if m not in wanted]
    if leaving:
        leaving_models = await _models_by_name(session, leaving)
        for member in leaving:
            await _leave_group(session, leaving_models[member], group)

    for model_name in wanted:
        model = by_name[model_name]
        if model.stock_group_id == group.id:
            continue
        if model.stock_group_id is not None:
            # Был в другой группе: выходит оттуда (остаток остаётся той группе) и входит сюда.
            other = await session.get(StockGroup, model.stock_group_id)
            await _leave_group(session, model, other)
        await _join_group(session, model, group, admin_user_id)

    await wh.ensure_components(session)
    await _sync_models(session, [*wanted, *leaving])
    return group_out(group, await group_members(session, group.id))


async def delete_group(session: AsyncSession, name: str, admin_user_id: int | None = None) -> None:
    """Распустить группу: остаток целиком уходит первой модели группы, история сохраняется."""
    group = await session.scalar(select(StockGroup).where(StockGroup.name == name))
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    members = await group_members(session, group.id)
    if not members:
        await session.delete(group)
        return
    models = await _models_by_name(session, members)
    heir = models[members[0]]

    # Сначала модели выходят из группы, чтобы их ключи снова стали их именами.
    for member in members:
        models[member].stock_group_id = None
    await session.flush()

    group_components = (
        await session.scalars(select(StockComponent).where(StockComponent.model_name == group.name))
    ).all()
    for component in group_components:
        target = await _get_or_create(session, component.kind, heir.name, component.plate_type)
        await _move_stock(
            session,
            component,
            target,
            comment=f"Группа «{group.name}» распущена → {heir.name}",
            admin_user_id=admin_user_id,
        )
    await session.delete(group)
    await session.flush()
    for member in members:
        await wh.ensure_components_for_model(session, member)
    await _sync_models(session, members)
