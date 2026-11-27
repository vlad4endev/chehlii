"""Канонический список моделей iPhone (БД) + добавление новых из админки."""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import IPHONE_MODELS
from app.models.catalog import CaseType, CaseTypeModel, IphoneModel
from app.models.order import Order
from app.models.warehouse import StockComponent, StockGroup, StockMovement
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
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Название модели слишком длинное (макс. 64)"
        )
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


async def _require_model(session: AsyncSession, name: str) -> IphoneModel:
    model = await session.scalar(select(IphoneModel).where(IphoneModel.name == name))
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Модели «{name}» нет")
    return model


async def model_details(session: AsyncSession) -> list[dict]:
    """Список моделей со сводкой для управления: заказы, остаток, группа, можно ли удалить."""
    await ensure_seeded(session)
    models = (
        await session.execute(
            select(IphoneModel.name, StockGroup.name)
            .outerjoin(StockGroup, IphoneModel.stock_group_id == StockGroup.id)
            .order_by(IphoneModel.sort_order, IphoneModel.id)
        )
    ).all()
    orders = dict(
        (
            await session.execute(
                select(Order.model_name, func.count(Order.id))
                .where(Order.model_name.is_not(None))
                .group_by(Order.model_name)
            )
        ).all()
    )
    stock = dict(
        (
            await session.execute(
                select(
                    StockComponent.model_name, func.coalesce(func.sum(StockComponent.qty), 0)
                ).group_by(StockComponent.model_name)
            )
        ).all()
    )
    out: list[dict] = []
    for name, group_name in models:
        n_orders = int(orders.get(name, 0))
        qty = int(stock.get(name, 0))
        reason = _delete_blocker(name, n_orders, qty, group_name)
        out.append(
            {
                "name": name,
                "orders": n_orders,
                "stock_qty": qty,
                "group_name": group_name,
                "can_delete": reason is None,
                "delete_blocker": reason,
            }
        )
    return out


def _delete_blocker(name: str, orders: int, qty: int, group_name: str | None) -> str | None:
    """Почему модель нельзя удалить (None — можно). Тексты показываются работнику как есть."""
    if orders:
        return (
            f"По модели есть заказы ({orders}) — удаление сломало бы историю. "
            "Отключите её в типах чехлов, чтобы клиенты её не видели."
        )
    if group_name:
        return (
            f"Модель входит в старую группу «{group_name}». "
            "Сначала расформируйте группу в окне «Модели iPhone»."
        )
    if qty:
        return f"На складе остаток {qty} шт. Сначала спишите или обнулите его."
    return None


async def rename_model(session: AsyncSession, old_name: str, raw_new_name: str) -> str:
    """Переименовать модель везде одной транзакцией: канон, типы чехлов, склад, заказы."""
    new_name = normalize_iphone_model_name(raw_new_name)
    model = await _require_model(session, old_name)
    if new_name == old_name:
        return new_name

    if await session.scalar(select(IphoneModel.id).where(IphoneModel.name == new_name)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Модель «{new_name}» уже есть")
    # Имя группы — тоже ключ складского остатка: совпадение смешало бы остатки.
    if await session.scalar(select(StockGroup.id).where(StockGroup.name == new_name)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Название «{new_name}» уже занято группой моделей"
        )

    model.name = new_name
    await session.execute(
        update(CaseTypeModel)
        .where(CaseTypeModel.model_name == old_name)
        .values(model_name=new_name)
    )
    await session.execute(
        update(StockComponent)
        .where(StockComponent.model_name == old_name)
        .values(model_name=new_name)
    )
    await session.execute(
        update(Order).where(Order.model_name == old_name).values(model_name=new_name)
    )
    await session.flush()
    return new_name


async def delete_model(session: AsyncSession, name: str) -> None:
    """Удалить модель, которой ещё не пользовались: нет заказов, группы и остатка."""
    model = await _require_model(session, name)
    details = next((d for d in await model_details(session) if d["name"] == name), None)
    if details is not None and details["delete_blocker"]:
        raise HTTPException(status.HTTP_409_CONFLICT, details["delete_blocker"])

    component_ids = list(
        await session.scalars(select(StockComponent.id).where(StockComponent.model_name == name))
    )
    if component_ids:
        # Остаток нулевой, но история движений могла остаться — она относится к этой модели.
        await session.execute(
            delete(StockMovement).where(StockMovement.component_id.in_(component_ids))
        )
        await session.execute(delete(StockComponent).where(StockComponent.id.in_(component_ids)))
    await session.execute(delete(CaseTypeModel).where(CaseTypeModel.model_name == name))
    await session.delete(model)
    await session.flush()
