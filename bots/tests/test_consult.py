"""Правила, когда клиент может писать админу из бота."""

from bots.core.consult import can_write, has_phone


def test_has_phone() -> None:
    assert has_phone({"phone": "+79001112233"})
    assert has_phone({"phone": "  8900  "})
    assert not has_phone({"phone": None})
    assert not has_phone({"phone": ""})
    assert not has_phone({"phone": "   "})
    assert not has_phone({})


def test_can_write_with_phone_even_without_order() -> None:
    assert can_write(phone="+79001112233", thread_open=False)
    assert can_write(phone="  +7  ", thread_open=False)


def test_can_write_without_phone_only_if_thread_open() -> None:
    assert can_write(phone=None, thread_open=True)
    assert can_write(phone="", thread_open=True)
    assert not can_write(phone=None, thread_open=False)
    assert not can_write(phone="   ", thread_open=False)
