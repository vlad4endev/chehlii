"""Списание со склада при полной оплате заказа.

Единый идемпотентный хелпер: `Order.stock_deducted` защищает от повторного
вычета (webhook-ретрай, ручной откат→возврат статуса). Делегирует в warehouse:
1 балванка + 1 пластина case_type.plate_type; кэш case_type_models.stock синхронизируется.

Правило приёмки 23.10:
- стандарт — списание на PREPAYMENT_PAID (это уже 100% одной ссылкой);
- кастом — списание на POSTPAYMENT_PAID (полная оплата), не на частичной предоплате.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CaseBranch, OrderStatus
from app.models.order import Order
from app.services import warehouse


def should_deduct_stock(order: Order, new_status: OrderStatus | str) -> bool:
    """Нужно ли списывать склад при переходе в new_status."""
    status = OrderStatus(new_status) if not isinstance(new_status, OrderStatus) else new_status
    is_custom = order.branch == CaseBranch.CUSTOM
    if is_custom:
        return status == OrderStatus.POSTPAYMENT_PAID
    return status == OrderStatus.PREPAYMENT_PAID


async def maybe_deduct_for_order(
    session: AsyncSession, order: Order, new_status: OrderStatus | str
) -> None:
    """Списать, если статус — момент полной оплаты для ветки заказа."""
    if should_deduct_stock(order, new_status):
        await warehouse.deduct_for_order(session, order)


async def deduct_for_order(session: AsyncSession, order: Order) -> None:
    """Списать 1 base + 1 plate для (order.case_type_id, order.model_name) один раз."""
    await warehouse.deduct_for_order(session, order)


async def restore_for_order(session: AsyncSession, order: Order) -> None:
    """Вернуть 1 base + 1 plate при отмене — только если раньше списали."""
    await warehouse.restore_for_order(session, order)
