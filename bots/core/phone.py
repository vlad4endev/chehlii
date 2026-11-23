"""Нормализация телефона РФ — общая для Telegram и MAX."""

from __future__ import annotations

import re

# Мобильный РФ внутри произвольной цифровой строки (в т.ч. после мусора VERSION:3.0).
_MOBILE_DIGITS = re.compile(r"9\d{9}")
# Форматированный ввод: +7/8 (900) 123-45-67.
_PHONE_RE = re.compile(
    r"(?:\+?7|8)?\s*\(?([9]\d{2})\)?\s*(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})"
)


def normalize_phone(text: str | None) -> str | None:
    """Извлечь +79XXXXXXXXX из текста, номера или значения TEL в vCard.

    Нельзя склеивать весь vCard в одну строку и брать «первый» 10-значный кусок:
    VERSION:3.0 даёт префикс «30», и 8900… превращается в +73089… — Яндекс
    отвечает «Recipient's phone is invalid».
    """
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    m = _MOBILE_DIGITS.search(digits)
    if m:
        return "+7" + m.group(0)
    m = _PHONE_RE.search(text)
    if m:
        return "+7" + "".join(m.groups())
    return None


# Строгий мобильный РФ: +79XXXXXXXXX (для служб доставки).
_RU_MOBILE_E164 = re.compile(r"\+79\d{9}")
_MIN_INTL_DIGITS = 8
_MAX_INTL_DIGITS = 15  # E.164


def is_russian_mobile(phone: str | None) -> bool:
    """Номер в формате +79XXXXXXXXX — только такой принимают Яндекс Доставка и Ozon."""
    return bool(phone and _RU_MOBILE_E164.fullmatch(phone))


def normalize_any_phone(text: str | None, *, trusted_digits: bool = False) -> str | None:
    """Номер любой страны в формате E.164 (+код…) или None.

    Российские номера (+7/8/9XXXXXXXXX) приводятся к +79XXXXXXXXX. Остальные
    принимаются только с явным кодом страны: «+380…» или «00380…». Голые цифры
    без «+» допустимы лишь для доверенного источника (контакт Telegram/MAX отдаёт
    полный международный номер без плюса), иначе «4915…» легко спутать с мусором.
    Мобильность и валидность для служб доставки проверяет is_russian_mobile().
    """
    if not text:
        return None
    raw = text.strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    # Строго РФ: 10 цифр на 9… или 11 цифр на 7/8 + 9…
    if len(digits) == 10 and digits.startswith("9"):
        return "+7" + digits
    if len(digits) == 11 and digits[0] in "78" and digits[1] == "9":
        return "+7" + digits[1:]

    explicit = raw.startswith(("+", "00"))
    if raw.startswith("00"):
        digits = digits[2:]
    if not (explicit or trusted_digits):
        return None
    if not _MIN_INTL_DIGITS <= len(digits) <= _MAX_INTL_DIGITS:
        return None
    if digits.startswith("0"):  # кода страны с нуля не бывает
        return None
    if digits.startswith("7"):  # +7 без мобильного 9XX — городской/мусор, для заказа не годится
        return None
    return "+" + digits


def format_phone(phone: str) -> str:
    """Для показа клиенту: +7 900 123-45-67; иностранные — как есть."""
    if is_russian_mobile(phone):
        return f"+7 {phone[2:5]} {phone[5:8]}-{phone[8:10]}-{phone[10:12]}"
    return phone
