"""Загрузка медиа для каталога (только Админ).

Файл сохраняется в settings.media_root и отдаётся статикой по пути /media.
Возвращается прямой URL (`/media/catalog/<uuid>.<ext>`) — годный для <img src>
в мини-аппе и админке (тот же домен). Используется для обложки типа и фото
под конкретную модель iPhone.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.v1.admin.deps import AdminOnly
from app.services import media

router = APIRouter()


@router.post("")
async def upload_media(file: UploadFile, _: AdminOnly) -> dict[str, str]:
    ext = media.ext_for(file.content_type, file.filename)
    if ext is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Формат не поддерживается. Загрузите JPG, PNG, WEBP или GIF.",
        )
    data = await file.read()
    if len(data) > media.MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 12 МБ.")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")
    return {"url": media.save_bytes(data, ext, "catalog")}
