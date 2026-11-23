"""Бренд: логотип, который админ может заменить без разработчика."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import IntegrationSetting
from app.services import integrations

LOGO_KEY = "brand.logo_url"
MAX_LOGO_URL_LEN = 500


def clean_logo_url(raw: str | None) -> str | None:
    """Путь загруженного файла (/media/…) или http(s)-ссылка; пустое — «вернуть стандартный»."""
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > MAX_LOGO_URL_LEN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка на логотип слишком длинная")
    # Любое другое значение (javascript:, data: …) попало бы в src публичных страниц.
    if not (value.startswith("/media/") or value.startswith(("https://", "http://"))):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Логотип нужно загрузить файлом или указать ссылку http(s)",
        )
    return value


async def get_logo_url(session: AsyncSession) -> str | None:
    return await integrations.get(session, LOGO_KEY)


async def set_logo_url(session: AsyncSession, raw: str | None) -> str | None:
    """Сохранить логотип; None — сбросить на стандартный. Коммит — на вызывающей стороне."""
    value = clean_logo_url(raw)
    row = await session.get(IntegrationSetting, LOGO_KEY)
    if row is None:
        session.add(IntegrationSetting(key=LOGO_KEY, value=value or ""))
    else:
        row.value = value or ""
    return value
