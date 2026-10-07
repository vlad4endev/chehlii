"""Кэш user_id → chat_id для MAX (send_action и FSM из outbox ждут chat_id диалога).

In-memory + опционально Redis — переживает рестарт бота.
"""

from __future__ import annotations

import logging
from typing import Any

_CHAT_BY_USER: dict[int, int] = {}
_redis: Any = None  # redis.asyncio.Redis | None
_KEY = "maxbot:chat:{uid}"
log = logging.getLogger(__name__)


def bind_redis(client: Any) -> None:
    """Подключить Redis для персистентного chat_map (вызывать из run_max)."""
    global _redis
    _redis = client


def remember(user_id: int | str | None, chat_id: int | str | None) -> None:
    """Запомнить пару в памяти процесса."""
    if user_id is None or chat_id is None:
        return
    try:
        _CHAT_BY_USER[int(user_id)] = int(chat_id)
    except (TypeError, ValueError):
        return


async def remember_async(user_id: int | str | None, chat_id: int | str | None) -> None:
    """Запомнить пару в памяти и в Redis."""
    remember(user_id, chat_id)
    if user_id is None or chat_id is None or _redis is None:
        return
    try:
        uid, cid = int(user_id), int(chat_id)
        await _redis.set(_KEY.format(uid=uid), str(cid))
    except Exception:  # noqa: BLE001
        log.debug("chat_map: redis write failed", exc_info=True)


def chat_for(user_id: int) -> int:
    """Вернуть известный chat_id или сам user_id как fallback."""
    return _CHAT_BY_USER.get(user_id, user_id)


async def chat_for_async(user_id: int) -> int:
    """chat_id из памяти или Redis; fallback — user_id."""
    known = await known_chat_async(user_id)
    return known if known is not None else user_id


async def known_chat_async(user_id: int) -> int | None:
    """chat_id из памяти/Redis или None, если диалог ещё не встречали."""
    if user_id in _CHAT_BY_USER:
        return _CHAT_BY_USER[user_id]
    if _redis is None:
        return None
    try:
        raw = await _redis.get(_KEY.format(uid=user_id))
        if raw is None:
            return None
        cid = int(raw if not isinstance(raw, bytes) else raw.decode())
        _CHAT_BY_USER[user_id] = cid
        return cid
    except Exception:  # noqa: BLE001
        log.debug("chat_map: redis read failed", exc_info=True)
        return None
