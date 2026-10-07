"""Нормализация телефона: MAX vCard не должен портить номер цифрами VERSION."""

from bots.core.phone import normalize_phone


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
