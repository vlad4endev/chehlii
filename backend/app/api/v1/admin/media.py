"""Загрузка медиа для каталога (только Админ).

Файл атомарно сохраняется в MEDIA_ROOT, регистрируется в media_assets (SHA-256)
и архивируется на Яндекс.Диск. Возвращается прямой URL (`/media/catalog/...`)
для <img src> в мини-аппе и админке.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly, CurrentAdmin
from app.core.database import get_session
from app.services import media, media_assets, yandex_disk

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
async def upload_media(
    file: UploadFile,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
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

    root = await media_assets.disk_root(session)
    remote = yandex_disk.catalog_path(root, file.filename or f"catalog.{ext}")
    saved, asset, disk_url = await media_assets.persist(
        session,
        data,
        ext=ext,
        subdir="catalog",
        kind=kind,
        owner_type="catalog",
        original_filename=file.filename,
        disk_remote_path=remote,
        require_disk=False,
    )
    await session.commit()

    out: dict[str, str] = {"url": saved.url, "type": kind, "sha256": saved.sha256}
    if disk_url:
        out["disk_url"] = disk_url
    elif asset.archive_error:
        out["archive_warning"] = asset.archive_error
    return out
