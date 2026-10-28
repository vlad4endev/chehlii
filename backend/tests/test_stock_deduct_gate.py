"""Правило списания склада: стандарт на предоплате 100%, кастом на постоплате."""

from __future__ import annotations

from app.enums import CaseBranch, OrderStatus
from app.services.stock import should_deduct_stock


class _O:
    def __init__(self, branch: str) -> None:
        self.branch = branch


def test_standard_deducts_on_prepayment() -> None:
    assert should_deduct_stock(_O(CaseBranch.STANDARD), OrderStatus.PREPAYMENT_PAID)
    assert not should_deduct_stock(_O(CaseBranch.STANDARD), OrderStatus.POSTPAYMENT_PAID)


def test_custom_deducts_on_postpayment_only() -> None:
    assert not should_deduct_stock(_O(CaseBranch.CUSTOM), OrderStatus.PREPAYMENT_PAID)
    assert should_deduct_stock(_O(CaseBranch.CUSTOM), OrderStatus.POSTPAYMENT_PAID)
