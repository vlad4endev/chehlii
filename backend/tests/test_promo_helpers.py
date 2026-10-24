"""Юнит-проверки скидочной программы друзей (без БД)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.promo import _recalc


def test_recalc_sums_three_components():
    c = SimpleNamespace(
        loyal_discount=5,
        discount_for_slave=3,
        discount_master_code=2,
        total_discount=0,
    )
    _recalc(c)
    assert float(c.total_discount) == 10.0
