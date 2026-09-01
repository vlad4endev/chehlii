"""Защита внутренних эндпоинтов (бот → backend) общим секретом.

Браузер-мини-приложение читает только публичные GET (catalog/hero/reviews) и не
передаёт identity — заказы/клиенты/оплату шлют только боты по внутренней сети.
Один заголовок X-Internal-Token закрывает и открытый доступ к API, и подмену
client_id: бот проставляет клиента от аутентифицированного Telegram/MAX-юзера.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_internal(
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    # ponytail: fail-open, когда токен не задан (dev/тесты). Прод задаёт токен в
    # .env → проверка включается. Сравнение постоянного времени против таймингов.
    expected = settings.internal_api_token
    if expected and not (x_internal_token and secrets.compare_digest(x_internal_token, expected)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный внутренний токен")
