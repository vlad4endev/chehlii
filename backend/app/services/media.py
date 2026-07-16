"""Локальное хранилище медиа (фото каталога, материалы клиента).

Файлы кладём в settings.media_root, отдаём статикой по пути /media. Возвращаем
прямой URL (`/media/<subdir>/<uuid>.<ext>`) — годный для <img src> в админке и
мини-аппе (тот же домен, в отличие от страницы-просмотрщика Яндекс.Диска).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import settings

# Тип содержимого → расширение файла.
IMAGE_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
}
DOC_EXT = {"application/pdf": "pdf"}
VIDEO_EXT = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}
MAX_BYTES = 12 * 1024 * 1024  # 12 МБ (фото/док)
MAX_VIDEO_BYTES = 45 * 1024 * 1024  # 45 МБ (видео)


def media_kind(content_type: str | None, filename: str | None) -> tuple[str, str] | None:
    """Вернуть (расширение, тип) для изображения/видео, иначе None. тип = image|video."""
    ct = (content_type or "").lower()
    if ct in IMAGE_EXT:
        return IMAGE_EXT[ct], "image"
    if ct in VIDEO_EXT:
        return VIDEO_EXT[ct], "video"
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[1].lower()
        img = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif", "heic": "heic", "heif": "heif"}
        vid = {"mp4": "mp4", "m4v": "mp4", "mov": "mov", "webm": "webm"}
        if tail in img:
            return img[tail], "image"
        if tail in vid:
            return vid[tail], "video"
    return None


def ext_for(content_type: str | None, filename: str | None, *, allow_docs: bool = False) -> str | None:
    ct = (content_type or "").lower()
    if ct in IMAGE_EXT:
        return IMAGE_EXT[ct]
    if allow_docs and ct in DOC_EXT:
        return DOC_EXT[ct]
    # Фоллбэк по расширению имени файла (мессенджеры не всегда шлют content-type).
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[1].lower()
        known = {"jpg", "jpeg", "png", "webp", "gif", "heic", "heif"}
        if allow_docs:
            known = known | {"pdf"}
        if tail in known:
            return "jpg" if tail == "jpeg" else tail
    return None


def save_bytes(content: bytes, ext: str, subdir: str) -> str:
    """Сохранить байты в media/<subdir>/ и вернуть прямой URL (/media/...)."""
    folder = Path(settings.media_root) / subdir
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(content)
    return f"/media/{subdir}/{name}"
