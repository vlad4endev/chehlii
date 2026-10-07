"""Нормализация телефона — общая для TG и MAX."""

from bots.core.phone import normalize_phone


def test_normalize_plus7() -> None:
    assert normalize_phone("+7 999 123-45-67") == "+79991234567"


def test_normalize_8() -> None:
    assert normalize_phone("8 (999) 123 45 67") == "+79991234567"


def test_normalize_digits_only() -> None:
    assert normalize_phone("9991234567") == "+79991234567"


def test_normalize_rejects_short() -> None:
    assert normalize_phone("12345") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None
