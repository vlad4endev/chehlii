"""Локальное хранилище медиа (фото каталога, материалы клиента).

Файлы кладём в settings.media_root атомарно (tmp → rename), считаем SHA-256,
отдаём статикой по пути /media. Возвращаем прямой URL (`/media/<subdir>/<uuid>.<ext>`)
— годный для <img src> в админке и мини-аппе. Метаданные и архив на Яндекс.Диске
ведёт `services.media_assets`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)

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
AUDIO_EXT = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/x-wav": "wav",
}
MAX_BYTES = 12 * 1024 * 1024  # 12 МБ (фото/док)
MAX_VIDEO_BYTES = 45 * 1024 * 1024  # 45 МБ (видео)


@dataclass(frozen=True, slots=True)
class SavedFile:
    """Результат надёжной записи на локальный диск."""

    url: str
    storage_key: str
    sha256: str
    size_bytes: int
    mime: str
    path: Path


def media_kind(content_type: str | None, filename: str | None) -> tuple[str, str] | None:
    """Вернуть (расширение, тип) для изображения/видео, иначе None. тип = image|video."""
    ct = (content_type or "").lower()
    if ct in IMAGE_EXT:
        return IMAGE_EXT[ct], "image"
    if ct in VIDEO_EXT:
        return VIDEO_EXT[ct], "video"
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[1].lower()
        img = {
            "jpg": "jpg",
            "jpeg": "jpg",
            "png": "png",
            "webp": "webp",
            "gif": "gif",
            "heic": "heic",
            "heif": "heif",
        }
        vid = {"mp4": "mp4", "m4v": "mp4", "mov": "mov", "webm": "webm"}
        if tail in img:
            return img[tail], "image"
        if tail in vid:
            return vid[tail], "video"
    return None


def consult_kind(content_type: str | None, filename: str | None) -> tuple[str, str]:
    """(расширение, тип) для консультации. тип = image|video|audio|file."""
    known = media_kind(content_type, filename)
    if known:
        return known
    ct = (content_type or "").lower()
    if ct in AUDIO_EXT:
        return AUDIO_EXT[ct], "audio"
    if ct in DOC_EXT:
        return DOC_EXT[ct], "file"
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[1].lower()
        audio = {"ogg": "ogg", "oga": "ogg", "mp3": "mp3", "m4a": "m4a", "aac": "aac", "wav": "wav"}
        if tail in audio:
            return audio[tail], "audio"
        if tail == "pdf":
            return "pdf", "file"
        if tail:
            return tail[:8], "file"
    return "bin", "file"


def ext_for(
    content_type: str | None, filename: str | None, *, allow_docs: bool = False
) -> str | None:
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


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_bytes(content: bytes, ext: str, subdir: str) -> str:
    """Сохранить байты в media/<subdir>/ и вернуть прямой URL (/media/...)."""
    return persist_bytes(content, ext, subdir).url


def persist_bytes(content: bytes, ext: str, subdir: str) -> SavedFile:
    """Атомарно записать файл, проверить размер, вернуть метаданные + SHA-256."""
    if not content:
        raise ValueError("пустой файл")
    root = Path(settings.media_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(
            f"MEDIA_ROOT недоступен ({root}): {e}. "
            "На сервере проверьте том infra/media и что rsync не удалил его (--exclude infra/media)."
        ) from e
    folder = root / subdir
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext.lstrip('.')}"
    storage_key = f"{subdir.strip('/')}/{name}"
    final = folder / name
    tmp = folder / f".{name}.{uuid.uuid4().hex}.tmp"
    digest = sha256_hex(content)
    try:
        with open(tmp, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        if tmp.stat().st_size != len(content):
            raise OSError("размер после записи не совпал")
        os.replace(tmp, final)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    # fsync каталога — чтобы rename пережил краш FS.
    try:
        dir_fd = os.open(str(folder), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as e:
        log.warning("media: fsync каталога %s не удался: %s", folder, e)

    mime = sniff_mime(content, name=name)
    url = f"/media/{storage_key}"
    return SavedFile(
        url=url,
        storage_key=storage_key,
        sha256=digest,
        size_bytes=len(content),
        mime=mime,
        path=final,
    )


def verify_local(url: str, *, expected_sha256: str | None = None) -> bool:
    """Файл на месте и (опционально) хеш совпадает."""
    path = resolve_local(url)
    if path is None:
        return False
    if not expected_sha256 or expected_sha256 == "0" * 64:
        return True
    try:
        return sha256_hex(path.read_bytes()) == expected_sha256
    except OSError:
        return False


def resolve_local(url: str) -> Path | None:
    """Путь на диске для `/media/...`. Посторонние URL и `..` — None."""
    path = (url or "").split("?", 1)[0].strip()
    if not path.startswith("/media/"):
        return None
    rel = path[len("/media/") :].lstrip("/")
    if not rel or ".." in Path(rel).parts:
        return None
    root = Path(settings.media_root).resolve()
    full = (root / rel).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full if full.is_file() else None


def sniff_mime(data: bytes, *, name: str = "") -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "pdf": "application/pdf",
        "heic": "image/heic",
        "heif": "image/heif",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "ogg": "audio/ogg",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
    }.get(ext, "application/octet-stream")


async def bytes_for_url(url: str) -> tuple[bytes, str] | None:
    """Байты локального `/media` или публичного файла Яндекс.Диска.

    Если локальный файл пропал — пробуем восстановить из реестра media_assets
    (disk_url) и положить обратно на диск.
    """
    local = resolve_local(url)
    if local is not None:
        data = local.read_bytes()
        return data, sniff_mime(data, name=local.name)

    # Восстановление из архива по реестру.
    try:
        from app.services import media_assets as assets

        restored = await assets.restore_local(url)
        if restored:
            return restored
    except Exception as e:  # noqa: BLE001
        log.warning("media: restore %s failed: %s", url, e)

    from app.services import yandex_disk

    if yandex_disk.is_public_url(url):
        try:
            data = await yandex_disk.download_public(url)
        except yandex_disk.YandexDiskError:
            return None
        if data:
            return data, sniff_mime(data)
    return None
