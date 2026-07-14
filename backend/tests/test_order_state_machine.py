"""Тесты машины статусов заказа."""

import pytest

from app.enums import OrderStatus as S
from app.services.order_state_machine import (
    InvalidTransition,
    assert_transition,
    can_transition,
)


def test_standard_branch_skips_design():
    # Стандарт: после предоплаты сразу выставляется постоплата.
    assert can_transition(S.PREPAYMENT_PAID, S.POSTPAYMENT_ISSUED)


def test_custom_branch_goes_to_design():
    assert can_transition(S.PREPAYMENT_PAID, S.HANDED_TO_DESIGN)
    assert can_transition(S.DESIGN_IN_PROGRESS, S.MOCKUP_SENT)


def test_mockup_revision_loops_back_to_sent():
    assert can_transition(S.MOCKUP_SENT, S.MOCKUP_REVISION)
    assert can_transition(S.MOCKUP_REVISION, S.MOCKUP_SENT)


def test_cancel_from_payment_issued():
    assert can_transition(S.PREPAYMENT_ISSUED, S.CANCELLED)
    assert can_transition(S.POSTPAYMENT_ISSUED, S.CANCELLED)


def test_terminal_statuses_have_no_exits():
    assert not can_transition(S.CANCELLED, S.PREPAYMENT_PAID)
    assert not can_transition(S.REVIEW_RECEIVED, S.DELIVERED)


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        assert_transition(S.CASE_TYPE_SELECTED, S.DELIVERED)


def test_happy_path_delivery_chain():
    chain = [
        S.POSTPAYMENT_PAID,
        S.DELIVERY_SERVICE_SELECTION,
        S.DELIVERY_ADDRESS_SELECTION,
        S.DELIVERY_PAYMENT,
        S.SHIPPED,
        S.DELIVERED,
        S.REVIEW_OFFERED,
        S.REVIEW_RECEIVED,
    ]
    for src, dst in zip(chain, chain[1:], strict=False):
        assert can_transition(src, dst), f"{src} → {dst}"
