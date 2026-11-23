"""Режим «клиент говорит с человеком» поверх прерванного шага сценария.

«Позвать человека» посреди заказа не меняет FSM — шаг (доставка, материалы…) нужно
сохранить, чтобы клиент мог вернуться. Но пока он пишет менеджеру, следующие реплики
не должны попадать в этот шаг: вопрос принимался за город/адрес/описание, а в админке
сообщения клиента не появлялись.

Флаг human_chat живёт в данных FSM. Он выставляется кнопкой «Позвать человека»,
а снимается нажатием любой inline-кнопки сценария, действием админа, меняющим FSM
(сценарий/закрытие диалога), новым заказом или /start.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bots.tg.promo_guard import _MENU_TEXTS
from bots.tg.states import OrderFlow

HUMAN_CHAT_KEY = "human_chat"

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]
Relay = Callable[[Message, Any], Awaitable[None]]


def is_relayable(msg: Message) -> bool:
    """Реплика клиента для менеджера: текст (не меню/команда) или вложение."""
    if msg.contact or msg.web_app_data:
        return False
    if msg.text:
        return msg.text not in _MENU_TEXTS and not msg.text.startswith("/")
    return bool(
        msg.caption or msg.photo or msg.document or msg.voice or msg.video or msg.video_note or msg.audio
    )


class HumanChatGuard(BaseMiddleware):
    """Пока флаг human_chat стоит, реплики клиента уходят менеджеру, минуя хендлеры шага."""

    def __init__(self, relay: Relay) -> None:
        self._relay = relay

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        state = data.get("state")
        if isinstance(event, Message) and state is not None and is_relayable(event):
            current = await state.get_state()
            # Без шага (None) и в consulting реплики и так идут менеджеру штатными хендлерами.
            if current not in (None, OrderFlow.consulting.state) and (await state.get_data()).get(
                HUMAN_CHAT_KEY
            ):
                await self._relay(event, state)
                return None
        return await handler(event, data)


class HumanChatReset(BaseMiddleware):
    """Нажатие inline-кнопки сценария = клиент вернулся к заказу."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        state = data.get("state")
        if (
            isinstance(event, CallbackQuery)
            and state is not None
            and (await state.get_data()).get(HUMAN_CHAT_KEY)
        ):
            await state.update_data(**{HUMAN_CHAT_KEY: False})
        return await handler(event, data)
