"""Ввод промокода друга: что считаем кодом и сколько раз даём ошибиться."""

from __future__ import annotations

import re

# Коды генерирует backend («CHL» + 6 hex), но админ может задать свой: латиница,
# цифры, дефис, подчёркивание. Фраза с пробелами или кириллицей — не код.
_PROMO_RE = re.compile(r"[A-Za-z0-9_\-]{4,32}")

# После стольких неверных кодов выходим из режима ввода, чтобы клиент не «застрял».
MAX_PROMO_ATTEMPTS = 3


def looks_like_promo_code(text: str | None) -> bool:
    return bool(text and _PROMO_RE.fullmatch(text.strip()))
