"""Загрузка медиа для каталога (только Админ).

Файл сохраняется в settings.media_root и отдаётся статикой по пути /media.
Возвращается прямой URL (`/media/catalog/<uuid>.<ext>`) — годный для <img src>
в мини-аппе и админке (тот же домен). Используется для обложки типа и фото
под конкретную модель iPhone.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.api.v1.admin.deps import AdminOnly, CurrentAdmin
from app.services import media

router = APIRouter()


@router.get("/preview")
async def preview_media(
    _: CurrentAdmin,
    url: Annotated[str, Query(min_length=1, max_length=1024)],
) -> Response:
    """Превью файла в карточке заказа: локальное /media или публичный Яндекс.Диск."""
    got = await media.bytes_for_url(url)
    if not got:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл недоступен")
    data, mime = got
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=120"},
    )


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
