"""MAX: после «Позвать человека» сообщения идут менеджеру, а не в прерванный шаг (паритет с TG)."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from maxapi.context import MemoryContext  # noqa: E402
from maxapi.types import MessageCallback, MessageCreated  # noqa: E402

from bots.max import handlers  # noqa: E402
from bots.max.human_chat import HumanChatGuard, HumanChatReset, is_relayable  # noqa: E402
from bots.max.states import OrderFlow  # noqa: E402


def _context() -> MemoryContext:
    return MemoryContext(chat_id=1, user_id=1)


def _event(text: str | None, attachments: list | None = None) -> MessageCreated:
    message = SimpleNamespace(
        body=SimpleNamespace(text=text, attachments=attachments or []),
        recipient=SimpleNamespace(chat_id=1),
        sender=SimpleNamespace(user_id=1, username="u", full_name="U"),
        answer=AsyncMock(),
    )
    return MessageCreated.model_construct(message=message, bot=SimpleNamespace())


def _callback(payload: str) -> MessageCallback:
    return MessageCallback.model_construct(callback=SimpleNamespace(payload=payload))


@pytest.fixture(autouse=True)
def backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake = SimpleNamespace(
        upsert_client=AsyncMock(return_value={"id": 7, "phone": "+79001234567"}),
        mark_journey=AsyncMock(),
    )
    monkeypatch.setattr(handlers, "backend", fake)
    monkeypatch.setattr(handlers.consult, "ingest", AsyncMock(return_value=True))
    monkeypatch.setattr(handlers, "_relay_review", AsyncMock(return_value=False))
    monkeypatch.setattr(handlers, "_consult_files_max", AsyncMock(return_value=[]))
    monkeypatch.setattr(handlers, "remember_async", AsyncMock())
    monkeypatch.setattr(handlers, "_send_menu", AsyncMock())
    monkeypatch.setattr(handlers, "texts", SimpleNamespace(get=lambda code, **kw: code))
    return fake


async def _call_human(ctx: MemoryContext) -> None:
    await handlers._call_human(SimpleNamespace(), 1, 1, "u", ctx)


async def test_call_human_mid_scenario_sets_flag_and_keeps_step() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.delivery_city)
    await ctx.update_data(order_id=5)
    await _call_human(ctx)
    assert (await ctx.get_data())["human_chat"] is True
    assert await ctx.get_state() is not None
    assert (await ctx.get_data())["order_id"] == 5


async def test_call_human_without_step_goes_to_consulting_without_flag() -> None:
    ctx = _context()
    await _call_human(ctx)
    assert await ctx.get_state() is not None
    assert not (await ctx.get_data()).get("human_chat")


async def _through_guard(ctx: MemoryContext, event) -> AsyncMock:
    handler = AsyncMock()
    await HumanChatGuard(handlers.relay_human_chat)(handler, event, {"context": ctx})
    return handler


async def test_guard_relays_question_to_manager_instead_of_step() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.delivery_city)
    await ctx.update_data(order_id=5, human_chat=True)
    handler = await _through_guard(ctx, _event("Хочу уточнить, можно ли поменять модель?"))
    handler.assert_not_awaited()  # шаг доставки не получил вопрос как «город»
    sent = handlers.consult.ingest.await_args.args[1]
    assert "поменять модель" in sent and "[Заказ #5]" in sent
    assert await ctx.get_state() is not None  # шаг сохранён для возврата


async def test_guard_passes_everything_without_flag() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.delivery_city)
    handler = await _through_guard(ctx, _event("Москва"))
    handler.assert_awaited_once()
    handlers.consult.ingest.assert_not_awaited()


async def test_guard_ignores_contact_and_commands() -> None:
    contact = SimpleNamespace(type="contact")
    assert not is_relayable(_event(None, [contact]))
    assert not is_relayable(_event("/start"))
    assert is_relayable(_event(None, [SimpleNamespace(type="image")]))
    assert is_relayable(_event("вопрос"))


async def test_scenario_button_returns_client_to_the_order_but_menu_does_not() -> None:
    ctx = _context()
    await ctx.set_state(OrderFlow.delivery_city)
    await ctx.update_data(human_chat=True)
    handler = AsyncMock()
    await HumanChatReset()(handler, _callback("menu:payments"), {"context": ctx})
    assert (await ctx.get_data())["human_chat"] is True  # меню — не возврат к заказу
    await HumanChatReset()(handler, _callback("delivery:go:5"), {"context": ctx})
    assert (await ctx.get_data())["human_chat"] is False
