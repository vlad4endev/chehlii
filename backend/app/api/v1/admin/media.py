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
    res = media.media_kind(file.content_type, file.filename)
    if res is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Формат не поддерживается. Фото: JPG/PNG/WEBP/GIF; видео: MP4/MOV/WEBM.",
        )
    ext, kind = res
    data = await file.read()
    limit = media.MAX_VIDEO_BYTES if kind == "video" else media.MAX_BYTES
    if len(data) > limit:
        mb = limit // (1024 * 1024)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Файл больше {mb} МБ.")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл.")
    return {"url": media.save_bytes(data, ext, "catalog"), "type": kind}
