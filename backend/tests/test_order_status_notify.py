"""Карта уведомлений при ручной смене статуса."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.enums import CaseBranch, Channel, OrderStatus, PaymentKind
from app.services.order_status_notify import (
    MOCKUP_STATUSES,
    NotifyResult,
    continue_after_paid,
    notify_after_manual_status,
)


def _run(coro):
    return asyncio.run(coro)


def _order(**kw):
    defaults = {
        "id": 1,
        "client_id": 10,
        "branch": CaseBranch.CUSTOM,
        "status": OrderStatus.DESIGN_IN_PROGRESS,
        "tracking_code": None,
        "cost": 100,
        "margin": 50,
        "total_discount": 0,
        "delivery_cost": 0,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _client():
    return SimpleNamespace(id=10, channel=Channel.TG, channel_user_id="123")


def test_mockup_statuses_excluded_from_manual_notify():
    assert OrderStatus.MOCKUP_SENT in MOCKUP_STATUSES
    assert OrderStatus.MOCKUP_APPROVAL in MOCKUP_STATUSES
    assert OrderStatus.MOCKUP_REVISION in MOCKUP_STATUSES
    assert OrderStatus.SHIPPED not in MOCKUP_STATUSES
    assert OrderStatus.CANCELLED not in MOCKUP_STATUSES


def test_manual_mockup_status_does_not_enqueue():
    session = AsyncMock()
    order = _order(status=OrderStatus.MOCKUP_SENT)
    result = _run(
        notify_after_manual_status(
            session, order, OrderStatus.DESIGN_IN_PROGRESS, OrderStatus.MOCKUP_SENT
        )
    )
    assert result == NotifyResult()
    session.add.assert_not_called()
    session.get.assert_not_called()


def test_manual_shipped_enqueues_msg_014():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_client())
    order = _order(status=OrderStatus.SHIPPED, tracking_code="TRACK-1")
    with patch(
        "app.services.order_status_notify.scenario_text",
        AsyncMock(return_value="Заказ отправлен. Трек: {tracking}."),
    ):
        result = _run(
            notify_after_manual_status(
                session, order, OrderStatus.DELIVERY_PAYMENT, OrderStatus.SHIPPED
            )
        )
    assert result.notified is True
    assert result.code == "msg_014аб"
    assert session.add.call_count == 1
    msg = session.add.call_args[0][0]
    assert "TRACK-1" in msg.text
    assert msg.kind == "text"


def test_manual_delivery_service_selection_enqueues_delivery_block():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_client())
    order = _order(status=OrderStatus.DELIVERY_SERVICE_SELECTION)
    with patch(
        "app.services.order_status_notify.scenario_text",
        AsyncMock(return_value="Выберите службу доставки."),
    ):
        result = _run(
            notify_after_manual_status(
                session,
                order,
                OrderStatus.POSTPAYMENT_PAID,
                OrderStatus.DELIVERY_SERVICE_SELECTION,
            )
        )
    assert result == NotifyResult(True, "msg_011аб")
    msg = session.add.call_args[0][0]
    assert msg.kind == "delivery"
    assert msg.text == "Выберите службу доставки."


def test_manual_cancelled_enqueues_msg_cancel():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_client())
    order = _order(status=OrderStatus.CANCELLED)
    with patch(
        "app.services.order_status_notify.scenario_text",
        AsyncMock(return_value="Заказ отменён."),
    ):
        result = _run(
            notify_after_manual_status(
                session, order, OrderStatus.PREPAYMENT_ISSUED, OrderStatus.CANCELLED
            )
        )
    assert result == NotifyResult(True, "msg_cancel")
    msg = session.add.call_args[0][0]
    assert msg.text == "Заказ отменён."


def test_manual_prepayment_issued_custom_is_pay_kind():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_client())
    order = _order(branch=CaseBranch.CUSTOM, status=OrderStatus.PREPAYMENT_ISSUED)
    with patch(
        "app.services.order_status_notify.scenario_text",
        AsyncMock(return_value="Внесите предоплату"),
    ):
        result = _run(
            notify_after_manual_status(
                session, order, OrderStatus.MATERIALS_SUBMITTED, OrderStatus.PREPAYMENT_ISSUED
            )
        )
    assert result == NotifyResult(True, "msg_007б")
    msg = session.add.call_args[0][0]
    assert msg.kind == "pay"
    assert msg.media == [{"type": "pay", "kind": "prepayment"}]


def test_continue_after_paid_custom_wait_mockup():
    session = MagicMock()
    session.add = MagicMock()
    order = _order(branch=CaseBranch.CUSTOM, status=OrderStatus.PREPAYMENT_PAID)
    with (
        patch(
            "app.services.order_status_notify.integrations.get",
            AsyncMock(return_value="50"),
        ),
        patch(
            "app.services.order_status_notify.scenario_text",
            AsyncMock(return_value="Ждите макет"),
        ),
    ):
        result = _run(
            continue_after_paid(session, order, _client(), kind=PaymentKind.PREPAYMENT)
        )
    assert result == NotifyResult(True, "msg_008б")
    msg = session.add.call_args[0][0]
    assert msg.kind == "text"
    assert msg.text == "Ждите макет"


def test_manual_delivered_offers_review():
    session = AsyncMock()
    session.get = AsyncMock(return_value=_client())
    order = _order(status=OrderStatus.DELIVERED)
    with (
        patch(
            "app.services.order_status_notify.scenario_text",
            AsyncMock(return_value="Заказ получен"),
        ),
        patch(
            "app.services.order_status_notify.review_offer.enqueue",
            AsyncMock(),
        ) as enqueue,
    ):
        result = _run(
            notify_after_manual_status(
                session, order, OrderStatus.SHIPPED, OrderStatus.DELIVERED
            )
        )
    assert result.notified is True
    assert order.status == OrderStatus.REVIEW_OFFERED
    enqueue.assert_awaited_once()
