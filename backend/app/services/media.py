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
MAX_BYTES = 12 * 1024 * 1024  # 12 МБ


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
