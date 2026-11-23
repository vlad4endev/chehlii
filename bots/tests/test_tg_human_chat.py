"""Telegram: после «Позвать человека» сообщения идут менеджеру, а не в прерванный шаг сценария.

Баг заказчика: бот «помнил прошлый запрос» (шаг доставки/материалов), хотя клиент уже
говорил с человеком, а в админке реплик клиента не было.
"""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

from bots.tg import handlers
from bots.tg.keyboards import BTN_HELP
from bots.tg.middlewares import install
from bots.tg.states import OrderFlow

BOT = Bot("123456:test")
DP = Dispatcher(storage=MemoryStorage())
install(DP)
DP.include_router(handlers.router)
_counter = iter(range(1000, 100000))


class Chat_:
    """Один клиент: свой chat_id, отправка апдейтов через настоящий Dispatcher."""

    def __init__(self) -> None:
        self.uid = next(_counter)
        self.key = StorageKey(bot_id=BOT.id, chat_id=self.uid, user_id=self.uid)
        self.update_id = 0

    async def seed(self, state, **data) -> None:
        await DP.storage.set_state(self.key, state.state if state else None)
        await DP.storage.set_data(self.key, data)

    async def say(self, text: str) -> None:
        self.update_id += 1
        message = Message(
            message_id=self.update_id,
            date=datetime.now(),
            chat=Chat(id=self.uid, type="private"),
            from_user=User(id=self.uid, is_bot=False, first_name="Клиент", username="client"),
            text=text,
        )
        await DP.feed_update(BOT, Update(update_id=self.update_id, message=message))

    async def state(self) -> str | None:
        return await DP.storage.get_state(self.key)

    async def data(self) -> dict:
        return await DP.storage.get_data(self.key)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    sent: list[str] = []

    async def fake_call(self, method, request_timeout=None):
        sent.append(getattr(method, "text", "") or "")

    monkeypatch.setattr(Bot, "__call__", fake_call)
    backend = SimpleNamespace(
        consult_take_pending=AsyncMock(return_value=None),
        upsert_client=AsyncMock(return_value={"id": 7, "phone": "+79001234567", "master_code": None}),
        mark_journey=AsyncMock(),
        client_orders=AsyncMock(return_value=[]),
        consult_is_open=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(handlers, "backend", backend)
    monkeypatch.setattr("bots.tg.pending_fsm.backend", backend)
    monkeypatch.setattr(handlers.consult, "ingest", AsyncMock(return_value=True))
    monkeypatch.setattr(handlers.review, "has_pending", AsyncMock(return_value=False))
    monkeypatch.setattr(handlers.delivery, "pickup_points", AsyncMock(return_value=[]))
    monkeypatch.setattr(handlers.delivery, "resolve_service", AsyncMock(return_value="yandex"))
    monkeypatch.setattr(handlers, "texts", SimpleNamespace(get=lambda code, **kw: code))
    return SimpleNamespace(sent=sent, backend=backend, ingest=handlers.consult.ingest)


def _ingested_texts(world) -> list[str]:
    return [c.args[1] or "" for c in world.ingest.await_args_list]


async def test_delivery_step_after_calling_human_goes_to_manager(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5, delivery_mode="pvz")
    await chat.say(BTN_HELP)
    await chat.say("Хочу уточнить, можно ли поменять модель?")
    assert any("поменять модель" in t for t in _ingested_texts(world))
    handlers.delivery.pickup_points.assert_not_awaited()  # вопрос не принят за город


async def test_materials_description_after_calling_human_goes_to_manager(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.waiting_materials_desc, order_id=5, is_custom=True)
    await chat.say(BTN_HELP)
    await chat.say("А сколько стоит срочная печать?")
    assert any("срочная печать" in t for t in _ingested_texts(world))
    assert "materials_text" not in await chat.data()  # реплика не записана как описание


async def test_human_chat_flag_is_set_only_mid_scenario(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5)
    await chat.say(BTN_HELP)
    assert (await chat.data()).get("human_chat") is True
    assert await chat.state() == OrderFlow.delivery_city.state  # шаг сохранён для возврата

    idle = Chat_()
    await idle.seed(None)
    await idle.say(BTN_HELP)
    assert await idle.state() == OrderFlow.consulting.state
    assert not (await idle.data()).get("human_chat")


async def test_admin_closing_dialog_ends_human_chat(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5, human_chat=True)
    world.backend.consult_take_pending.return_value = {"state": "clear"}
    await chat.say("спасибо")
    # Закрытый шаг не срабатывает на «стёртых» данных; реплика идёт обычным путём к менеджеру.
    assert await chat.state() != OrderFlow.delivery_city.state
    assert "human_chat" not in await chat.data()
    assert any("спасибо" in t for t in _ingested_texts(world))
    handlers.delivery.pickup_points.assert_not_awaited()


async def test_admin_scenario_ends_human_chat(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5, human_chat=True)
    world.backend.consult_take_pending.return_value = {"state": "waiting_materials", "order_id": 5}
    await chat.say("ок")
    assert await chat.state() == OrderFlow.waiting_materials.state
    assert (await chat.data())["human_chat"] is False


async def test_inline_button_returns_client_to_the_order() -> None:
    from aiogram.types import CallbackQuery

    from bots.tg.human_chat import HumanChatReset

    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5, human_chat=True)
    state = DP.fsm.get_context(BOT, chat_id=chat.uid, user_id=chat.uid)
    handler = AsyncMock()
    event = CallbackQuery.model_construct(id="1", data="delivery:go:5")
    await HumanChatReset()(handler, event, {"state": state})
    handler.assert_awaited_once()
    assert (await chat.data())["human_chat"] is False


async def test_without_flag_step_handlers_still_receive_text(world) -> None:
    chat = Chat_()
    await chat.seed(OrderFlow.delivery_city, order_id=5, delivery_mode="pvz")
    await chat.say("Москва")
    handlers.delivery.pickup_points.assert_awaited_once()


async def test_promo_mode_is_left_for_the_same_update(world) -> None:
    """Через настоящий Dispatcher: «Позвать человека» в режиме промокода выводит из него сразу."""
    chat = Chat_()
    await chat.seed(OrderFlow.entering_promo)
    await chat.say(BTN_HELP)
    assert await chat.state() == OrderFlow.consulting.state  # а не остался entering_promo
