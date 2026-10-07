"""Нормализация телефона РФ — общая для Telegram и MAX."""

from __future__ import annotations

import re

_PHONE_RE = re.compile(
    r"(?:\+?7|8)?\s*\(?(\d{3})\)?\s*(\d{3})[\s-]?(\d{2})[\s-]?(\d{2})"
)


def normalize_phone(text: str | None) -> str | None:
    """Извлечь +7XXXXXXXXXX из свободного текста или vCard-фрагмента."""
    if not text:
        return None
    m = _PHONE_RE.search(text)
    if not m:
        return None
    return "+7" + "".join(m.groups())
