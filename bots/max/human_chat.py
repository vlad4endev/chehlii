"""Режим «клиент говорит с человеком» поверх прерванного шага сценария (MAX).

Паритет с Telegram (bots/tg/human_chat.py): «Позвать человека» посреди заказа
сохраняет шаг, но следующие реплики клиента идут менеджеру, а не в этот шаг.
Флаг human_chat снимается inline-кнопкой сценария (не пунктом меню), действием админа,
меняющим FSM, и новым заказом.
"""

from __future__ import annotations

from typing import Any

from maxapi.context.base import BaseContext
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types import MessageCallback, MessageCreated

from bots.max.states import OrderFlow

HUMAN_CHAT_KEY = "human_chat"
_MENU_PREFIX = "menu:"


def _state_name(state: Any) -> str:
    """maxapi State и строка из Redis приводятся к одному виду: «OrderFlow:шаг»."""
    return str(state)


def is_relayable(event: MessageCreated) -> bool:
    """Реплика клиента для менеджера: текст (не команда) или вложение, кроме контакта."""
    body = event.message.body
    attachments = list(getattr(body, "attachments", None) or [])
    if any("contact" in str(getattr(a, "type", "")).lower() for a in attachments):
        return False
    text = (getattr(body, "text", None) or "").strip()
    if text:
        return not text.startswith("/")
    return bool(attachments)


class HumanChatGuard(BaseMiddleware):
    """Пока флаг human_chat стоит, реплики клиента уходят менеджеру, минуя хендлеры шага."""

    def __init__(self, relay) -> None:
        self._relay = relay

    async def __call__(self, handler: HandlerCallable, event_object: Any, data: dict[str, Any]) -> Any:
        context = data.get("context")
        if (
            isinstance(context, BaseContext)
            and isinstance(event_object, MessageCreated)
            and is_relayable(event_object)
        ):
            current = await context.get_state()
            # Без шага (None) и в consulting реплики и так идут менеджеру штатными хендлерами.
            if (
                current is not None
                and _state_name(current) != _state_name(OrderFlow.consulting)
                and (await context.get_data()).get(HUMAN_CHAT_KEY)
            ):
                await self._relay(event_object, context)
                return None
        return await handler(event_object, data)


class HumanChatReset(BaseMiddleware):
    """Нажатие inline-кнопки сценария (не меню) = клиент вернулся к заказу."""

    async def __call__(self, handler: HandlerCallable, event_object: Any, data: dict[str, Any]) -> Any:
        context = data.get("context")
        if (
            isinstance(context, BaseContext)
            and isinstance(event_object, MessageCallback)
            and not (getattr(event_object.callback, "payload", None) or "").startswith(_MENU_PREFIX)
            and (await context.get_data()).get(HUMAN_CHAT_KEY)
        ):
            await context.update_data(**{HUMAN_CHAT_KEY: False})
        return await handler(event_object, data)
