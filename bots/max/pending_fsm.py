"""Outer middleware MAX: pending_fsm до выбора хендлера (MemoryContext)."""

from __future__ import annotations

from typing import Any

from maxapi.context import MemoryContext
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types import MessageCreated

from bots.core.backend import backend
from bots.core.scenario import (
    STATE_CLEAR,
    STATE_CONSULTING,
    STATE_WAITING_CONTACT,
    STATE_WAITING_MATERIALS,
    STATE_WAITING_NAME,
)
from bots.max.chat_map import remember
from bots.max.states import OrderFlow

CHANNEL = "max"

_STATE_MAP = {
    STATE_WAITING_CONTACT: OrderFlow.waiting_phone,
    STATE_WAITING_NAME: OrderFlow.waiting_name,
    STATE_WAITING_MATERIALS: OrderFlow.waiting_materials,
    STATE_CONSULTING: OrderFlow.consulting,
}


async def apply_pending_fsm(context: MemoryContext, pending: dict[str, Any]) -> None:
    name = pending.get("state")
    if not name:
        return
    if name == STATE_CLEAR:
        await context.clear()
        return
    mapped = _STATE_MAP.get(name)
    if mapped is None:
        return
    await context.set_state(mapped)
    data: dict[str, Any] = {}
    oid = pending.get("order_id")
    if oid is not None:
        data["order_id"] = oid
    if data:
        await context.update_data(**data)


def _user_id_from_event(event_object: Any) -> str | None:
    if isinstance(event_object, MessageCreated):
        body = getattr(event_object, "message", None)
        sender = getattr(body, "sender", None) if body else None
        uid = getattr(sender, "user_id", None)
        recipient = getattr(body, "recipient", None) if body else None
        chat_id = getattr(recipient, "chat_id", None) if recipient else None
        if uid is not None and chat_id is not None:
            remember(uid, chat_id)
        if uid is not None:
            return str(uid)
        if chat_id is not None:
            return str(chat_id)
    return None


class PendingFsmMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        context = data.get("context")
        uid = _user_id_from_event(event_object)
        if isinstance(context, MemoryContext) and uid:
            pending = await backend.consult_take_pending(
                channel=CHANNEL, channel_user_id=uid
            )
            if pending:
                await apply_pending_fsm(context, pending)
                # maxapi кэширует state до outer middleware — обновляем кэш,
                # иначе фильтры хендлеров увидят старое состояние.
                new_state = await context.get_state()
                data["_current_state"] = new_state
                data["raw_state"] = new_state
        return await handler(event_object, data)
