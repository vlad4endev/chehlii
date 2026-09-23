"""Outer middleware: применить pending_fsm из админки до выбора хендлера."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bots.core.backend import backend
from bots.core.scenario import (
    STATE_CLEAR,
    STATE_CONSULTING,
    STATE_WAITING_CONTACT,
    STATE_WAITING_MATERIALS,
    STATE_WAITING_NAME,
)
from bots.tg.states import OrderFlow

CHANNEL = "tg"

_STATE_MAP = {
    STATE_WAITING_CONTACT: OrderFlow.waiting_contact,
    STATE_WAITING_NAME: OrderFlow.waiting_name,
    STATE_WAITING_MATERIALS: OrderFlow.waiting_materials,
    STATE_CONSULTING: OrderFlow.consulting,
}


async def apply_pending_fsm(state: FSMContext, pending: dict[str, Any]) -> None:
    """Выставить FSM и order_id из pending_fsm / outbox scenario."""
    name = pending.get("state")
    if not name:
        return
    if name == STATE_CLEAR:
        await state.clear()
        return
    mapped = _STATE_MAP.get(name)
    if mapped is None:
        return
    data: dict[str, Any] = {}
    oid = pending.get("order_id")
    if oid is not None:
        data["order_id"] = oid
    await state.set_state(mapped)
    if data:
        await state.update_data(**data)


class PendingFsmMiddleware(BaseMiddleware):
    """Снимает pending_fsm с backend и ставит Redis FSM до фильтров хендлеров."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user is not None:
            state: FSMContext | None = data.get("state")
            if state is not None:
                pending = await backend.consult_take_pending(
                    channel=CHANNEL,
                    channel_user_id=str(event.from_user.id),
                )
                if pending:
                    await apply_pending_fsm(state, pending)
        return await handler(event, data)
