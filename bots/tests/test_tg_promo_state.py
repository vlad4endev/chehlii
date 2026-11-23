"""Telegram: режим ввода промокода не должен «залипать» (баг «застрял на промокоде»)."""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message

from bots.core.promo import MAX_PROMO_ATTEMPTS, looks_like_promo_code
from bots.tg import handlers
from bots.tg.keyboards import BTN_HELP, BTN_PAYMENTS
from bots.tg.promo_guard import PromoStateGuard
from bots.tg.states import OrderFlow


def _state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


def _fake_msg(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, answer=AsyncMock(), from_user=SimpleNamespace(id=1, username="u", full_name="U")
    )


def _real_msg(text: str | None = None, **extra) -> Message:
    return Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"), text=text, **extra)


@pytest.fixture(autouse=True)
def backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake = SimpleNamespace(
        upsert_client=AsyncMock(return_value={"id": 7, "master_code": None}),
        activate_promo=AsyncMock(side_effect=ValueError("Промокод не найден")),
    )
    monkeypatch.setattr(handlers, "backend", fake)
    monkeypatch.setattr(handlers, "on_fallback", AsyncMock())
    return fake


@pytest.mark.parametrize("text", ["CHL1A2B3C", "friend-2024", "  chl1a2b3c  "])
def test_code_like_text(text: str) -> None:
    assert looks_like_promo_code(text)


@pytest.mark.parametrize("text", ["как оформить заказ?", "привет", "два слова", "abc", "x" * 40, "", None])
def test_not_code_like_text(text: str | None) -> None:
    assert not looks_like_promo_code(text)


async def test_phrase_leaves_promo_mode_and_goes_to_fallback(backend: SimpleNamespace) -> None:
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    msg = _fake_msg("как оформить заказ?")
    await handlers.on_promo_code(msg, state)
    assert await state.get_state() is None
    backend.activate_promo.assert_not_awaited()
    handlers.on_fallback.assert_awaited_once_with(msg, state)


async def test_wrong_codes_exit_after_limit(backend: SimpleNamespace) -> None:
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    for attempt in range(1, MAX_PROMO_ATTEMPTS + 1):
        await handlers.on_promo_code(_fake_msg("WRONG123"), state)
        expected = None if attempt == MAX_PROMO_ATTEMPTS else OrderFlow.entering_promo.state
        assert await state.get_state() == expected
    assert backend.activate_promo.await_count == MAX_PROMO_ATTEMPTS


async def test_valid_code_clears_state(backend: SimpleNamespace) -> None:
    backend.activate_promo = AsyncMock(return_value={"discount_master_code": 10, "total_discount": 10})
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    await handlers.on_promo_code(_fake_msg("CHL1A2B3C"), state)
    assert await state.get_state() is None


async def _through_guard(state: FSMContext, event: Message) -> None:
    handler = AsyncMock()
    await PromoStateGuard()(handler, event, {"state": state})
    handler.assert_awaited_once()


@pytest.mark.parametrize("text", [BTN_PAYMENTS, BTN_HELP, "/start", "/human"])
async def test_menu_and_commands_leave_promo_mode(text: str) -> None:
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    await state.update_data(order_id=5)
    await _through_guard(state, _real_msg(text))
    assert await state.get_state() is None
    assert (await state.get_data())["order_id"] == 5  # данные заказа не потеряны


async def test_plain_text_keeps_promo_mode_for_the_handler() -> None:
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    await _through_guard(state, _real_msg("CHL1A2B3C"))
    assert await state.get_state() == OrderFlow.entering_promo.state


async def test_attachment_without_text_leaves_promo_mode() -> None:
    state = _state()
    await state.set_state(OrderFlow.entering_promo)
    await _through_guard(state, _real_msg(None))
    assert await state.get_state() is None


async def test_guard_does_not_touch_other_states() -> None:
    state = _state()
    await state.set_state(OrderFlow.waiting_contact)
    await _through_guard(state, _real_msg(BTN_PAYMENTS))
    assert await state.get_state() == OrderFlow.waiting_contact.state
