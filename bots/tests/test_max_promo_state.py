"""MAX: режим ввода промокода не должен «залипать» (паритет с Telegram)."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from maxapi.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from bots.core.promo import MAX_PROMO_ATTEMPTS
from bots.max import handlers
from bots.max.keyboards import CB_DISCOUNT, CB_HELP, CB_PAYMENTS
from bots.max.promo_guard import PromoStateGuard, leaves_promo_mode
from bots.max.states import OrderFlow


def _context() -> MemoryContext:
    return MemoryContext(chat_id=1, user_id=1)


def _text_event(text: str | None) -> MessageCreated:
    message = SimpleNamespace(
        body=SimpleNamespace(text=text),
        recipient=SimpleNamespace(chat_id=1),
        sender=SimpleNamespace(user_id=1, username="u", full_name="U"),
    )
    return MessageCreated.model_construct(message=message, bot=SimpleNamespace())


def _callback_event(payload: str) -> MessageCallback:
    return MessageCallback.model_construct(callback=SimpleNamespace(payload=payload))


@pytest.fixture(autouse=True)
def backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake = SimpleNamespace(
        upsert_client=AsyncMock(return_value={"id": 7, "master_code": None}),
        activate_promo=AsyncMock(side_effect=ValueError("Промокод не найден")),
    )
    monkeypatch.setattr(handlers, "backend", fake)
    monkeypatch.setattr(handlers, "on_fallback", AsyncMock())
    monkeypatch.setattr(handlers, "_send_menu", AsyncMock())
    return fake


async def test_phrase_leaves_promo_mode_and_goes_to_fallback(backend: SimpleNamespace) -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.entering_promo)
    event = _text_event("как оформить заказ?")
    await handlers.on_promo_code(event, ctx)
    assert await ctx.get_state() is None
    backend.activate_promo.assert_not_awaited()
    handlers.on_fallback.assert_awaited_once_with(event, ctx)


async def test_wrong_codes_exit_after_limit(backend: SimpleNamespace) -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.entering_promo)
    for attempt in range(1, MAX_PROMO_ATTEMPTS + 1):
        await handlers.on_promo_code(_text_event("WRONG123"), ctx)
        still_in_promo = await ctx.get_state() is not None
        assert still_in_promo == (attempt < MAX_PROMO_ATTEMPTS)
    assert backend.activate_promo.await_count == MAX_PROMO_ATTEMPTS


async def test_valid_code_clears_state(backend: SimpleNamespace) -> None:
    backend.activate_promo = AsyncMock(return_value={"discount_master_code": 10, "total_discount": 10})
    ctx = _context()
    await ctx.set_state(OrderFlow.entering_promo)
    await handlers.on_promo_code(_text_event("CHL1A2B3C"), ctx)
    assert await ctx.get_state() is None


def test_what_leaves_promo_mode() -> None:
    assert leaves_promo_mode(_callback_event(CB_PAYMENTS))
    assert leaves_promo_mode(_callback_event(CB_HELP))
    assert not leaves_promo_mode(_callback_event(CB_DISCOUNT))
    assert leaves_promo_mode(_text_event("/start"))
    assert leaves_promo_mode(_text_event(None))
    assert not leaves_promo_mode(_text_event("CHL1A2B3C"))


async def _through_guard(ctx: MemoryContext, event) -> dict:
    handler = AsyncMock()
    data = {"context": ctx, "_current_state": "x", "raw_state": "x"}
    await PromoStateGuard()(handler, event, data)
    handler.assert_awaited_once()
    return data


@pytest.mark.parametrize("payload", [CB_PAYMENTS, CB_HELP])
async def test_menu_button_leaves_promo_mode(payload: str) -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.entering_promo)
    await ctx.update_data(order_id=5)
    data = await _through_guard(ctx, _callback_event(payload))
    assert await ctx.get_state() is None
    assert (await ctx.get_data())["order_id"] == 5  # данные заказа не потеряны
    assert data["_current_state"] is None and data["raw_state"] is None


async def test_plain_text_keeps_promo_mode() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.entering_promo)
    await _through_guard(ctx, _text_event("CHL1A2B3C"))
    assert await ctx.get_state() is not None


async def test_guard_does_not_touch_other_states() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.waiting_contact)
    await _through_guard(ctx, _callback_event(CB_PAYMENTS))
    assert await ctx.get_state() is not None
