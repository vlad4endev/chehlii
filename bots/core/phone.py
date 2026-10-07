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
