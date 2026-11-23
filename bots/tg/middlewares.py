"""Порядок подключения outer middleware Telegram-бота (общий для запуска и тестов)."""

from __future__ import annotations

from aiogram import Dispatcher

from bots.tg import handlers
from bots.tg.human_chat import HumanChatGuard, HumanChatReset
from bots.tg.pending_fsm import PendingFsmMiddleware
from bots.tg.promo_guard import PromoStateGuard


def install(dp: Dispatcher) -> None:
    """Сначала применяем FSM из админки, затем выходим из режимов, которые клиент покинул."""
    dp.message.outer_middleware(PendingFsmMiddleware())
    dp.message.outer_middleware(PromoStateGuard())
    dp.message.outer_middleware(HumanChatGuard(handlers.relay_human_chat))
    dp.callback_query.outer_middleware(HumanChatReset())
