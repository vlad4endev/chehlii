"""Кэш chat_id для MAX typing / outbox FSM."""

import pytest

from bots.max import chat_map


@pytest.fixture(autouse=True)
def _reset_chat_map():
    chat_map._CHAT_BY_USER.clear()
    chat_map.bind_redis(None)
    yield
    chat_map._CHAT_BY_USER.clear()
    chat_map.bind_redis(None)


def test_chat_map_remember_and_fallback() -> None:
    chat_map.remember(100, 9001)
    assert chat_map.chat_for(100) == 9001
    assert chat_map.chat_for(999) == 999  # unknown → user_id


@pytest.mark.asyncio
async def test_known_chat_async_none_until_remembered() -> None:
    assert await chat_map.known_chat_async(55) is None
    await chat_map.remember_async(55, 7700)
    assert await chat_map.known_chat_async(55) == 7700
    assert await chat_map.chat_for_async(55) == 7700
