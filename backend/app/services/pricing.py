"""Движок цены и скидок (ТЗ v2.0).

Скидки задаются вручную администратором; автоматического расчёта нет.
Все три компонента просто складываются, максимума нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def total_discount(
    loyal_discount: Decimal | float,
    discount_for_slave: Decimal | float,
    discount_master_code: Decimal | float,
) -> Decimal:
    """Total_discount = loyal_discount + discount_for_slave + discount_master_code (в %)."""
    return (
        Decimal(str(loyal_discount))
        + Decimal(str(discount_for_slave))
        + Decimal(str(discount_master_code))
    )


def case_price(cost: Decimal | float, margin: Decimal | float) -> Decimal:
    """Цена чехла = Себес + Маржа. Единая для типа, не зависит от модели iPhone."""
    return Decimal(str(cost)) + Decimal(str(margin))


def price_with_discount(price: Decimal, total_discount_pct: Decimal | float) -> Decimal:
    """Цена со скидкой = Цена чехла × (1 − Total_discount / 100)."""
    factor = Decimal(1) - Decimal(str(total_discount_pct)) / Decimal(100)
    return (price * factor).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class PriceBreakdown:
    case_price: Decimal
    discount_pct: Decimal
    price_with_discount: Decimal
    delivery_cost: Decimal
    final_price: Decimal


def compute(
    cost: Decimal | float,
    margin: Decimal | float,
    total_discount_pct: Decimal | float,
    delivery_cost: Decimal | float = 0,
) -> PriceBreakdown:
    """Конечная стоимость = Цена со скидкой + Стоимость доставки (ТЗ v2.0)."""
    price = case_price(cost, margin)
    discounted = price_with_discount(price, total_discount_pct)
    delivery = Decimal(str(delivery_cost))
    final = (discounted + delivery).quantize(Decimal("0.01"))
    return PriceBreakdown(
        case_price=price,
        discount_pct=Decimal(str(total_discount_pct)),
        price_with_discount=discounted,
        delivery_cost=delivery,
        final_price=final,
    )
