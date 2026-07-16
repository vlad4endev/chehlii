"""Списание балванки со склада при переходе заказа в prepayment_paid.

Единый идемпотентный хелпер: `Order.stock_deducted` защищает от повторного
вычета (webhook-ретрай, ручной откат→возврат статуса), SQL-условие
`stock > 0` — от ухода в минус.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CaseTypeModel
from app.models.order import Order


async def deduct_for_order(session: AsyncSession, order: Order) -> None:
    """Списать 1 балванку для (order.case_type_id, order.model_name) один раз."""
    if order.stock_deducted:
        return
    if order.case_type_id is None or not order.model_name:
        return
    # ponytail: no row lock, upgrade to SELECT FOR UPDATE if concurrent robokassa callbacks pile up.
    await session.execute(
        update(CaseTypeModel)
        .where(
            CaseTypeModel.case_type_id == order.case_type_id,
            CaseTypeModel.model_name == order.model_name,
            CaseTypeModel.stock > 0,
        )
        .values(stock=CaseTypeModel.stock - 1)
    )
    order.stock_deducted = True
