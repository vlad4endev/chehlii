"""Кэш user_id → chat_id для MAX (send_action ждёт chat_id диалога)."""

from __future__ import annotations

_CHAT_BY_USER: dict[int, int] = {}


def remember(user_id: int | str | None, chat_id: int | str | None) -> None:
    if user_id is None or chat_id is None:
        return
    try:
        _CHAT_BY_USER[int(user_id)] = int(chat_id)
    except (TypeError, ValueError):
        return


def chat_for(user_id: int) -> int:
    """Вернуть известный chat_id или сам user_id как fallback."""
    return _CHAT_BY_USER.get(user_id, user_id)
