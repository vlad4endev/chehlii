"""Списание со склада при переходе заказа в prepayment_paid.

Единый идемпотентный хелпер: `Order.stock_deducted` защищает от повторного
вычета (webhook-ретрай, ручной откат→возврат статуса). Делегирует в warehouse:
1 балванка + 1 пластина case_type.plate_type; кэш case_type_models.stock синхронизируется.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.services import warehouse


async def deduct_for_order(session: AsyncSession, order: Order) -> None:
    """Списать 1 base + 1 plate для (order.case_type_id, order.model_name) один раз."""
    await warehouse.deduct_for_order(session, order)


async def restore_for_order(session: AsyncSession, order: Order) -> None:
    """Вернуть 1 base + 1 plate при отмене — только если раньше списали."""
    await warehouse.restore_for_order(session, order)
