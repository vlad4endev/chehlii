"""Тесты движка цены и скидок (формулы ТЗ v2.0)."""

from decimal import Decimal

from app.services.pricing import compute, price_with_discount, total_discount


def test_total_discount_is_plain_sum():
    assert total_discount(10, 5, 15) == Decimal("30")


def test_price_with_discount():
    # Цена 1000, скидка 30% → 700.00
    assert price_with_discount(Decimal("1000"), 30) == Decimal("700.00")


def test_zero_discount():
    assert price_with_discount(Decimal("1000"), 0) == Decimal("1000.00")


def test_final_price_includes_delivery():
    # Себес 600 + Маржа 400 = 1000; скидка 20% → 800; доставка 350 → 1150.
    breakdown = compute(cost=600, margin=400, total_discount_pct=20, delivery_cost=350)
    assert breakdown.case_price == Decimal("1000")
    assert breakdown.price_with_discount == Decimal("800.00")
    assert breakdown.final_price == Decimal("1150.00")


def test_final_price_without_delivery_defaults_zero():
    breakdown = compute(cost=600, margin=400, total_discount_pct=0)
    assert breakdown.final_price == Decimal("1000.00")
