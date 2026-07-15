"""Загрузка медиа для каталога (только Админ).

Файл сохраняется в settings.media_root и отдаётся статикой по пути /media.
Возвращается прямой URL (`/media/catalog/<uuid>.<ext>`) — годный для <img src>
в мини-аппе и админке (тот же домен). Используется для обложки типа и фото
под конкретную модель iPhone.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.v1.admin.deps import AdminOnly
from app.core.config import settings

router = APIRouter()

# Разрешённые типы и расширение выходного файла.
_ALLOWED = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
_MAX_BYTES = 8 * 1024 * 1024  # 8 МБ на файл


@router.post("")
async def upload_media(file: UploadFile, _: AdminOnly) -> dict[str, str]:
    ext = _ALLOWED.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Формат не поддерживается. Загрузите JPG, PNG, WEBP или GIF.",
        )
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 8 МБ.")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")

    folder = Path(settings.media_root) / "catalog"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    return {"url": f"/media/catalog/{name}"}
