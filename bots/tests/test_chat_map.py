"""Кэш chat_id для MAX typing."""

from bots.max.chat_map import chat_for, remember


def test_chat_map_remember_and_fallback() -> None:
    remember(100, 9001)
    assert chat_for(100) == 9001
    assert chat_for(999) == 999  # unknown → user_id
