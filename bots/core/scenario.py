"""Карта сценариев из админки → FSM бота (TG / MAX).

Backend кладёт pending_fsm и outbox kind=scenario; бот применяет состояние
через outer middleware (до выбора хендлера) и/или сразу из outbox (TG Redis).
"""

from __future__ import annotations

from typing import Any

# Канал-агностичные имена из backend (services.consult.GUIDE_SCENARIOS).
STATE_WAITING_CONTACT = "waiting_contact"
STATE_WAITING_NAME = "waiting_name"
STATE_WAITING_MATERIALS = "waiting_materials"
STATE_CONSULTING = "consulting"
STATE_CLEAR = "clear"


def meta_from_outbox(item: dict) -> dict[str, Any]:
    """Достать code/state из media outbox (kind=scenario)."""
    for m in item.get("media") or []:
        if isinstance(m, dict) and m.get("type") == "scenario":
            return m
    return {}


def pending_payload(item: dict) -> dict[str, Any]:
    """Единый вид pending для apply: state, order_id, code."""
    meta = meta_from_outbox(item)
    state = meta.get("state") or (item.get("pending") or {}).get("state")
    out: dict[str, Any] = {}
    if state:
        out["state"] = state
    code = meta.get("code")
    if code:
        out["code"] = code
    oid = item.get("order_id")
    if oid is not None:
        out["order_id"] = oid
    return out
