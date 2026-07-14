"""Заказы: создание из выбора в мини-приложении и приём имени/материалов от клиента.

Цена считается со скидкой конкретного клиента (ТЗ 3.1.3). История статусов пишется
при каждом переходе. Оплата/доставка — отдельные спринты (после выбора шлюза).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.enums import CaseBranch, OrderStatus
from app.models.catalog import CaseType
from app.models.client import Client
from app.models.order import Order, OrderStatusHistory
from app.services import pricing

router = APIRouter()


class OrderCreateIn(BaseModel):
    client_id: int
    case_type_id: int
    branch: CaseBranch
    model_name: str


class OrderUpdateIn(BaseModel):
    custom_text: str | None = None
    materials_text: str | None = None
    materials_files: list | None = None


class OrderOut(BaseModel):
    id: int
    status: OrderStatus
    branch: CaseBranch | None
    model_name: str | None
    case_name: str
    is_custom: bool
    base_price: float
    total_discount: float
    client_price: float  # цена со скидкой клиента


async def _record_status(
    session: AsyncSession, order: Order, status: OrderStatus, trigger: str
) -> None:
    order.status = status
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=status,
            changed_by="system",
            trigger=trigger,
            created_at=datetime.now(UTC),
        )
    )


async def _to_out(session: AsyncSession, order: Order) -> OrderOut:
    ct = await session.get(CaseType, order.case_type_id)
    disc = float(order.total_discount or 0)
    breakdown = pricing.compute(order.cost or 0, order.margin or 0, disc)
    return OrderOut(
        id=order.id,
        status=order.status,
        branch=order.branch,
        model_name=order.model_name,
        case_name=ct.name if ct else "",
        is_custom=ct.is_custom if ct else False,
        base_price=float(breakdown.case_price),
        total_discount=disc,
        client_price=float(breakdown.price_with_discount),
    )


@router.post("", response_model=OrderOut)
async def create_order(
    payload: OrderCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderOut:
    ct = await session.get(CaseType, payload.case_type_id)
    if ct is None:
        raise HTTPException(status_code=404, detail="Тип чехла не найден")
    client = await session.get(Client, payload.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")

    order = Order(
        client_id=client.id,
        case_type_id=ct.id,
        branch=payload.branch,
        model_name=payload.model_name,
        status=OrderStatus.CASE_CONFIRMED,
        cost=ct.cost,
        margin=ct.margin,
        total_discount=client.total_discount,
    )
    session.add(order)
    await session.flush()
    await _record_status(session, order, OrderStatus.CASE_CONFIRMED, "Выбор из мини-приложения")
    await session.commit()
    await session.refresh(order)
    return await _to_out(session, order)


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: int,
    payload: OrderUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderOut:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    if payload.custom_text is not None:
        # Стандарт: имя/буква → выставляем предоплату.
        order.custom_text = payload.custom_text
        await _record_status(
            session, order, OrderStatus.PREPAYMENT_ISSUED, "Получены имя/буква"
        )
    if payload.materials_text is not None or payload.materials_files is not None:
        # Кастом: материалы получены → выставляем предоплату.
        if payload.materials_text is not None:
            order.materials_text = payload.materials_text
        if payload.materials_files is not None:
            order.materials_files = payload.materials_files
        await _record_status(
            session, order, OrderStatus.MATERIALS_SUBMITTED, "Получены материалы"
        )
        await _record_status(
            session, order, OrderStatus.PREPAYMENT_ISSUED, "Бот выставил ссылку предоплаты"
        )
        order.payment_link_issued_at = datetime.now(UTC)

    if payload.custom_text is not None:
        order.payment_link_issued_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(order)
    return await _to_out(session, order)
