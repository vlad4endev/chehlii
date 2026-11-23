"""Outer middleware MAX: не держать клиента в режиме ввода промокода.

Режим включается кнопкой «Моя скидочная программа». Любое другое действие
(другая кнопка меню, команда, вложение) — выход из него, иначе следующая реплика
клиента уходила бы в проверку как «промокод».
"""

from __future__ import annotations

from typing import Any

from maxapi.context.base import BaseContext
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types import MessageCallback, MessageCreated

from bots.max.keyboards import CB_DISCOUNT
from bots.max.states import OrderFlow


def _state_name(state: Any) -> Any:
    return getattr(state, "state", state)


def leaves_promo_mode(event_object: Any) -> bool:
    """True, если событие — не обычная текстовая реплика и не повторное открытие скидок."""
    if isinstance(event_object, MessageCallback):
        return getattr(event_object.callback, "payload", None) != CB_DISCOUNT
    if isinstance(event_object, MessageCreated):
        body = event_object.message.body
        text = (getattr(body, "text", None) or "").strip()
        return not text or text.startswith("/")
    return False


class PromoStateGuard(BaseMiddleware):
    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        context = data.get("context")
        if isinstance(context, BaseContext) and leaves_promo_mode(event_object):
            current = await context.get_state()
            if current is not None and _state_name(current) == _state_name(OrderFlow.entering_promo):
                await context.set_state(None)  # данные FSM (заказы, паузы) не трогаем
                # maxapi кэширует state до outer middleware — обновляем кэш,
                # иначе фильтры хендлеров увидят старое состояние.
                data["_current_state"] = None
                data["raw_state"] = None
        return await handler(event_object, data)
