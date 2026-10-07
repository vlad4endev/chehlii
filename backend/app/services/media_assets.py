"""Реестр медиа в PostgreSQL + архивация на Яндекс.Диск.

Каждая загрузка:
1) атомарно пишется на локальный диск (SHA-256);
2) регистрируется в media_assets;
3) по возможности копируется на Яндекс.Диск (disk_url).

Если локальный файл пропал, `restore_local` скачивает архив с Диска
и восстанавливает копию под тем же `/media/...` путём.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.media import MediaAsset
from app.services import integrations, media, yandex_disk

log = logging.getLogger(__name__)


async def register(
    session: AsyncSession,
    saved: media.SavedFile,
    *,
    kind: str,
    owner_type: str,
    owner_id: str | int | None = None,
    original_filename: str | None = None,
    disk_url: str | None = None,
) -> MediaAsset:
    """Создать или обновить запись реестра по local_url."""
    existing = await session.scalar(
        select(MediaAsset).where(MediaAsset.local_url == saved.url)
    )
    now_archived = datetime.now(UTC) if disk_url else None
    if existing is not None:
        existing.storage_key = saved.storage_key
        existing.sha256 = saved.sha256
        existing.mime = saved.mime
        existing.size_bytes = saved.size_bytes
        existing.kind = kind
        existing.owner_type = owner_type
        existing.owner_id = str(owner_id) if owner_id is not None else existing.owner_id
        if original_filename:
            existing.original_filename = original_filename
        if disk_url:
            existing.disk_url = disk_url
            existing.archived_at = now_archived
            existing.archive_error = None
        existing.deleted_at = None
        await session.flush()
        return existing

    asset = MediaAsset(
        storage_key=saved.storage_key,
        local_url=saved.url,
        disk_url=disk_url,
        sha256=saved.sha256,
        mime=saved.mime,
        size_bytes=saved.size_bytes,
        kind=kind,
        owner_type=owner_type,
        owner_id=str(owner_id) if owner_id is not None else None,
        original_filename=original_filename,
        archived_at=now_archived,
    )
    session.add(asset)
    await session.flush()
    return asset


async def archive_best_effort(
    session: AsyncSession,
    asset: MediaAsset,
    content: bytes,
    remote_path: str,
) -> str | None:
    """Загрузить на Яндекс.Диск; ошибку пишем в asset, загрузку не валим."""
    token = await integrations.get(session, "yandex_disk.oauth_token")
    if not token:
        asset.archive_error = "Яндекс.Диск не настроен"
        await session.flush()
        return None
    try:
        disk_url = await yandex_disk.upload(remote_path, content, token=token)
    except yandex_disk.YandexDiskError as e:
        asset.archive_error = str(e)[:500]
        log.warning("media_assets: archive %s failed: %s", asset.local_url, e)
        await session.flush()
        return None
    asset.disk_url = disk_url
    asset.archived_at = datetime.now(UTC)
    asset.archive_error = None
    await session.flush()
    return disk_url


async def archive_required(
    session: AsyncSession,
    asset: MediaAsset,
    content: bytes,
    remote_path: str,
) -> str:
    """Как archive_best_effort, но без токена / при ошибке — исключение."""
    token = await integrations.get(session, "yandex_disk.oauth_token")
    if not token:
        raise yandex_disk.YandexDiskError(
            "Яндекс.Диск не настроен — задайте OAuth-токен в разделе «Настройки → Интеграции»."
        )
    try:
        disk_url = await yandex_disk.upload(remote_path, content, token=token)
    except yandex_disk.YandexDiskError as e:
        asset.archive_error = str(e)[:500]
        await session.flush()
        raise
    asset.disk_url = disk_url
    asset.archived_at = datetime.now(UTC)
    asset.archive_error = None
    await session.flush()
    return disk_url


async def persist(
    session: AsyncSession,
    content: bytes,
    *,
    ext: str,
    subdir: str,
    kind: str,
    owner_type: str,
    owner_id: str | int | None = None,
    original_filename: str | None = None,
    disk_remote_path: str | None = None,
    require_disk: bool = False,
) -> tuple[media.SavedFile, MediaAsset, str | None]:
    """Записать локально → реестр → опциональный архив на Диск.

    Возвращает (saved, asset, disk_url).
    """
    saved = media.persist_bytes(content, ext, subdir)
    asset = await register(
        session,
        saved,
        kind=kind,
        owner_type=owner_type,
        owner_id=owner_id,
        original_filename=original_filename,
    )
    disk_url: str | None = None
    if disk_remote_path:
        if require_disk:
            disk_url = await archive_required(session, asset, content, disk_remote_path)
        else:
            disk_url = await archive_best_effort(session, asset, content, disk_remote_path)
    return saved, asset, disk_url


def file_ref(
    local_url: str,
    *,
    disk_url: str | None = None,
    sha256: str | None = None,
    asset_id: int | None = None,
) -> dict:
    """Структура для JSON-полей (materials_files и т.п.) — совместима с админкой."""
    ref: dict = {"url": local_url}
    if disk_url:
        ref["disk_url"] = disk_url
    if sha256:
        ref["sha256"] = sha256
    if asset_id is not None:
        ref["asset_id"] = asset_id
    return ref


async def get_by_local_url(session: AsyncSession, url: str) -> MediaAsset | None:
    return await session.scalar(
        select(MediaAsset).where(
            MediaAsset.local_url == url,
            MediaAsset.deleted_at.is_(None),
        )
    )


async def disk_root(session: AsyncSession) -> str:
    return await integrations.get(session, "yandex_disk.root", "/chechlii/orders")


async def restore_local(url: str) -> tuple[bytes, str] | None:
    """Если `/media/...` пропал — скачать с Диска по реестру и восстановить файл."""
    if not (url or "").startswith("/media/"):
        return None
    # Ленивый импорт: не поднимать async-engine при обычных загрузках/тестах.
    from app.core.database import SessionLocal

    async with SessionLocal() as session:
        asset = await get_by_local_url(session, url)
        if asset is None or not asset.disk_url:
            return None
        if not yandex_disk.is_public_url(asset.disk_url):
            return None
        try:
            data = await yandex_disk.download_public(asset.disk_url)
        except yandex_disk.YandexDiskError as e:
            log.warning("media_assets: download archive for %s: %s", url, e)
            return None
        if not data:
            return None
        if asset.sha256 and asset.sha256 != "0" * 64:
            got = media.sha256_hex(data)
            if got != asset.sha256:
                log.error(
                    "media_assets: sha256 mismatch on restore %s (want %s got %s)",
                    url,
                    asset.sha256,
                    got,
                )
                return None
        # Восстановить по storage_key / local_url.
        rel = asset.storage_key or url[len("/media/") :]
        target = Path(settings.media_root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".restore.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        except OSError as e:
            log.warning("media_assets: rewrite local %s: %s", target, e)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            # Даже если запись не удалась — отдаём байты вызывающему.
            return data, asset.mime or media.sniff_mime(data)
        return data, asset.mime or media.sniff_mime(data, name=target.name)
