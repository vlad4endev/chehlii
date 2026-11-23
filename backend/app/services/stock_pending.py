"""Оплаченные заказы, по которым склад ещё не списан (не хватило остатка в момент оплаты).

Заказ оплачен, а балванки или пластины на складе не было: списание честно пропускается,
но заказ остаётся «должен складу». Здесь — как такие заказы найти и списать вручную
после прихода, без дублей (повторное списание защищено Order.stock_deducted).
Коммит — на вызывающей стороне.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CaseBranch, OrderStatus, StockKind
from app.models.catalog import CaseType
from app.models.order import Order
from app.services import warehouse as wh
from app.services.stock_keys import stock_key

_S = OrderStatus

# Стандарт списывается с PREPAYMENT_PAID (это 100% одной ссылкой), кастом — с POSTPAYMENT_PAID.
# Дальше по воронке заказ всё ещё «должен складу», если не списан. Отменённые не в счёт.
_AFTER_FULL_PAYMENT = (
    _S.HANDED_TO_DESIGN,
    _S.DESIGN_IN_PROGRESS,
    _S.MOCKUP_SENT,
    _S.MOCKUP_APPROVAL,
    _S.MOCKUP_REVISION,
    _S.POSTPAYMENT_ISSUED,
)
_DELIVERY_AND_AFTER = (
    _S.POSTPAYMENT_PAID,
    _S.DELIVERY_SERVICE_SELECTION,
    _S.DELIVERY_ADDRESS_SELECTION,
    _S.DELIVERY_PAYMENT,
    _S.SHIPPED,
    _S.DELIVERED,
    _S.REVIEW_OFFERED,
    _S.REVIEW_RECEIVED,
)
STANDARD_PAID = frozenset((_S.PREPAYMENT_PAID, *_AFTER_FULL_PAYMENT, *_DELIVERY_AND_AFTER))
CUSTOM_PAID = frozenset(_DELIVERY_AND_AFTER)


def is_awaiting_deduction(order: Order) -> bool:
    """Оплачен по правилам списания, но склад не списан (и списать есть что)."""
    if order.stock_deducted or order.deleted_at is not None or order.is_test:
        return False
    if order.case_type_id is None or not order.model_name:
        return False
    paid = CUSTOM_PAID if order.branch == CaseBranch.CUSTOM else STANDARD_PAID
    return order.status in paid


async def _awaiting_orders(session: AsyncSession) -> list[tuple[Order, CaseType]]:
    rows = (
        await session.execute(
            select(Order, CaseType)
            .join(CaseType, CaseType.id == Order.case_type_id)
            .where(
                Order.stock_deducted.is_(False),
                Order.deleted_at.is_(None),
                Order.is_test.is_(False),
                Order.model_name.is_not(None),
            )
            .order_by(Order.id)
        )
    ).all()
    return [(o, ct) for o, ct in rows if is_awaiting_deduction(o)]


async def pending_count(session: AsyncSession) -> int:
    return len(await _awaiting_orders(session))


async def list_pending(session: AsyncSession) -> list[dict]:
    """Заказы, ждущие списания, самые давние первыми; can_deduct — хватает ли остатка сейчас.

    Остаток учитывается по очереди: два заказа на последнюю пару не получат оба «можно»."""
    out: list[dict] = []
    reserved: dict[tuple[str, str], int] = {}
    for order, case_type in await _awaiting_orders(session):
        plate = wh._normalize_plate(case_type.plate_type)
        base_key = await stock_key(session, StockKind.BASE, order.model_name)
        plate_key = await stock_key(session, StockKind.PLATE, order.model_name)
        enough = await wh.has_stock(session, order.model_name, case_type.plate_type)
        if enough:
            # Сколько пар уже «отдано» более ранним заказам с теми же позициями.
            used = max(reserved.get((base_key, "base"), 0), reserved.get((plate_key, plate), 0))
            base = await wh.get_component(session, StockKind.BASE, order.model_name, create=False)
            plate_row = await wh.get_component(
                session, StockKind.PLATE, order.model_name, plate, create=False
            )
            enough = used < min(base.qty, plate_row.qty)
            if enough:
                reserved[(base_key, "base")] = reserved.get((base_key, "base"), 0) + 1
                reserved[(plate_key, plate)] = reserved.get((plate_key, plate), 0) + 1
        out.append(
            {
                "order_id": order.id,
                "status": order.status,
                "model_name": order.model_name,
                "case_name": case_type.name,
                "plate_type": plate,
                "is_custom": order.branch == CaseBranch.CUSTOM,
                "created_at": order.created_at,
                "can_deduct": enough,
            }
        )
    return out


async def deduct_one(session: AsyncSession, order_id: int) -> None:
    """Списать склад по одному заказу вручную; 409, если по-прежнему не хватает."""
    order = await session.get(Order, order_id)
    if order is None or order.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    if order.stock_deducted:
        raise HTTPException(status.HTTP_409_CONFLICT, "По этому заказу склад уже списан")
    if not is_awaiting_deduction(order):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Заказ ещё не оплачен или отменён — списывать нечего"
        )
    if not await wh.deduct_for_order(session, order):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Не хватает остатка для заказа #{order.id} ({order.model_name}). Сначала оприходуйте.",
        )


async def deduct_available(session: AsyncSession) -> dict[str, int]:
    """Списать всё, на что хватает остатка, по порядку заказов. Остальное остаётся в очереди."""
    done = 0
    for order, _ in await _awaiting_orders(session):
        if await wh.deduct_for_order(session, order):
            done += 1
    return {"deducted": done, "remaining": await pending_count(session)}
