"""Карта scenario outbox → pending payload для FSM бота."""

from bots.core.scenario import (
    STATE_CLEAR,
    STATE_WAITING_NAME,
    meta_from_outbox,
    pending_payload,
)


def test_meta_from_outbox() -> None:
    item = {
        "kind": "scenario",
        "text": "Напишите имя",
        "order_id": 42,
        "media": [{"type": "scenario", "code": "msg_006а", "state": STATE_WAITING_NAME}],
    }
    meta = meta_from_outbox(item)
    assert meta["code"] == "msg_006а"
    assert meta["state"] == STATE_WAITING_NAME


def test_pending_payload() -> None:
    item = {
        "order_id": 7,
        "media": [{"type": "scenario", "code": "msg_help_close", "state": STATE_CLEAR}],
    }
    p = pending_payload(item)
    assert p == {"state": STATE_CLEAR, "code": "msg_help_close", "order_id": 7}


def test_pending_payload_text_only() -> None:
    assert pending_payload({"media": None, "text": "hi"}) == {}
