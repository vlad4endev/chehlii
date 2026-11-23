"""Telegram: ввод телефона вручную с подтверждением, иностранные номера, защита доставки."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from bots.tg import handlers
from bots.tg.keyboards import BTN_PHONE_MANUAL


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def clear(self) -> None:
        self.data.clear()


def _msg(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, answer=AsyncMock(), from_user=SimpleNamespace(id=1, username="client", full_name="Client"))


def _callback_buttons(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


async def test_manual_foreign_number_asks_confirmation() -> None:
    msg, state = _msg("+380 50 123 45 67"), FakeState()
    await handlers.on_waiting_contact_text(msg, state)
    assert state.data["pending_phone"] == "+380501234567"
    text = msg.answer.await_args.args[0]
    assert "+380501234567" in text
    assert _callback_buttons(msg.answer.await_args.kwargs["reply_markup"]) == ["phone:ok", "phone:retry"]


async def test_manual_russian_number_is_formatted_for_confirmation() -> None:
    msg, state = _msg("8 (900) 123-45-67"), FakeState()
    await handlers.on_waiting_contact_text(msg, state)
    assert state.data["pending_phone"] == "+79001234567"
    assert "+7 900 123-45-67" in msg.answer.await_args.args[0]


async def test_manual_button_prompts_for_number_without_saving() -> None:
    msg, state = _msg(BTN_PHONE_MANUAL), FakeState()
    await handlers.on_waiting_contact_text(msg, state)
    assert "pending_phone" not in state.data
    assert "код" in msg.answer.await_args.args[0].lower()


async def test_garbage_is_rejected_with_hint() -> None:
    msg, state = _msg("привет"), FakeState()
    await handlers.on_waiting_contact_text(msg, state)
    assert "pending_phone" not in state.data
    assert "Не разобрал" in msg.answer.await_args.args[0]


async def test_confirm_applies_phone_for_the_clicking_user(monkeypatch: pytest.MonkeyPatch) -> None:
    apply = AsyncMock()
    monkeypatch.setattr(handlers, "_apply_phone", apply)
    client_user = SimpleNamespace(id=42)
    cb = SimpleNamespace(
        answer=AsyncMock(),
        from_user=client_user,
        message=SimpleNamespace(answer=AsyncMock(), edit_reply_markup=AsyncMock()),
    )
    state = FakeState({"pending_phone": "+380501234567"})
    await handlers.on_phone_confirmed(cb, state)
    apply.assert_awaited_once()
    assert apply.await_args.args[2] == "+380501234567"
    assert apply.await_args.kwargs["user"] is client_user
    assert state.data["pending_phone"] is None


async def test_confirm_without_pending_phone_asks_again(monkeypatch: pytest.MonkeyPatch) -> None:
    apply = AsyncMock()
    monkeypatch.setattr(handlers, "_apply_phone", apply)
    cb = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(answer=AsyncMock(), edit_reply_markup=AsyncMock()),
    )
    await handlers.on_phone_confirmed(cb, FakeState())
    apply.assert_not_awaited()
    cb.message.answer.assert_awaited_once()


async def test_delivery_with_foreign_phone_requires_russian_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers.backend, "upsert_client", AsyncMock(return_value={"id": 7, "phone": "+380501234567"}))
    start = AsyncMock()
    monkeypatch.setattr(handlers, "_start_delivery", start)
    msg = _msg("")
    state = FakeState({"pending_delivery_order_id": 5})
    await handlers._apply_phone(msg, state, "+380501234567")
    start.assert_not_awaited()
    assert "российский" in msg.answer.await_args.args[0]


async def test_delivery_with_russian_phone_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers.backend, "upsert_client", AsyncMock(return_value={"id": 7, "phone": "+79001234567"}))
    start = AsyncMock()
    monkeypatch.setattr(handlers, "_start_delivery", start)
    msg = _msg("")
    await handlers._apply_phone(msg, FakeState({"pending_delivery_order_id": 5}), "+79001234567")
    start.assert_awaited_once()
