"""Нормализация телефона: MAX vCard не должен портить номер цифрами VERSION."""

from bots.core.phone import (
    format_phone,
    is_russian_mobile,
    normalize_any_phone,
    normalize_phone,
)


def test_normalize_accepts_russian_mobile_formats():
    for raw in (
        "+79001234567",
        "89001234567",
        "8 (900) 123-45-67",
        "9001234567",
        "+7 900 123 45 67",
    ):
        assert normalize_phone(raw) == "+79001234567"


def test_normalize_ignores_vcard_version_digits():
    # Старый баг MAX: склеивали весь vCard → «30» из VERSION:3.0 + 8900… → +73089…
    scrubbed = "3089001234567"
    assert normalize_phone(scrubbed) == "+79001234567"


def test_normalize_tel_line_from_vcard():
    assert normalize_phone("89001234567") == "+79001234567"
    assert normalize_phone("+7 900 123-45-67") == "+79001234567"


def test_normalize_rejects_landline_like_garbage():
    assert normalize_phone("+73089001234") is None
    assert normalize_phone("123") is None
    assert normalize_phone(None) is None


def test_any_phone_keeps_russian_normalization():
    for raw in ("+79001234567", "89001234567", "8 (900) 123-45-67", "9001234567"):
        assert normalize_any_phone(raw) == "+79001234567"


def test_any_phone_accepts_foreign_with_country_code():
    assert normalize_any_phone("+380 50 123 45 67") == "+380501234567"
    assert normalize_any_phone("00 380 50 123 45 67") == "+380501234567"
    assert normalize_any_phone("+49 1590 1234567") == "+4915901234567"  # не путать с РФ +7915…
    assert normalize_any_phone("+375 29 123-45-67") == "+375291234567"


def test_any_phone_bare_digits_only_from_trusted_source():
    assert normalize_any_phone("380501234567") is None
    assert normalize_any_phone("380501234567", trusted_digits=True) == "+380501234567"


def test_any_phone_rejects_garbage():
    for raw in (None, "", "abc", "123", "+1234567", "+7 495 123-45-67", "+0501234567", "+" + "9" * 16):
        assert normalize_any_phone(raw) is None, raw


def test_is_russian_mobile_and_format():
    assert is_russian_mobile("+79001234567")
    assert not is_russian_mobile("+380501234567")
    assert not is_russian_mobile(None)
    assert format_phone("+79001234567") == "+7 900 123-45-67"
    assert format_phone("+380501234567") == "+380501234567"
