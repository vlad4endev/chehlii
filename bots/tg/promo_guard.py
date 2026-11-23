"""Outer middleware: не держать клиента в режиме ввода промокода.

Режим включается кнопкой «Моя скидочная программа». Любое другое действие
(пункт меню, команда, контакт, фото, выбор из мини-приложения) — выход из него,
иначе следующая реплика клиента уходила бы в проверку как «промокод».
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bots.tg.keyboards import (
    BTN_CATALOG,
    BTN_DELIVERIES,
    BTN_DISCOUNT,
    BTN_HELP,
    BTN_PAYMENTS,
)
from bots.tg.states import OrderFlow

_MENU_TEXTS = {BTN_HELP, BTN_CATALOG, BTN_DISCOUNT, BTN_PAYMENTS, BTN_DELIVERIES}


def is_plain_text(msg: Message) -> bool:
    """Обычная текстовая реплика: не меню, не команда, не контакт/вложение/WebApp."""
    text = msg.text
    if not text or text in _MENU_TEXTS or text.startswith("/"):
        return False
    return not (msg.contact or msg.web_app_data)


class PromoStateGuard(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if (
            isinstance(event, Message)
            and state is not None
            and await state.get_state() == OrderFlow.entering_promo.state
            and not is_plain_text(event)
        ):
            await state.set_state(None)  # данные FSM (заказы, паузы) не трогаем
            data["raw_state"] = None  # фильтры хендлеров берут state из кэша data
        return await handler(event, data)
