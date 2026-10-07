"""Реестр медиафайлов: локальный путь + архив на Яндекс.Диске + целостность."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MediaAsset(Base, TimestampMixin):
    """Одна запись = один загруженный файл (каталог, материалы, макет, консультация).

    Байты лежат на диске VPS (`local_url` → MEDIA_ROOT) и по возможности
    дублируются на Яндекс.Диск (`disk_url`). SHA-256 позволяет проверить
    целостность и восстановить файл с Диска, если локальная копия пропала.
    """

    __tablename__ = "media_assets"
    __table_args__ = (
        Index("ix_media_assets_local_url", "local_url", unique=True),
        Index("ix_media_assets_sha256", "sha256"),
        Index("ix_media_assets_owner", "owner_type", "owner_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Относительный ключ внутри MEDIA_ROOT, напр. catalog/abc.png
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    local_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    disk_url: Mapped[str | None] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # image | video | audio | file
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="file")
    # catalog | order_material | order_mockup | consult | broadcast | other
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    owner_id: Mapped[str | None] = mapped_column(String(64))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    # Ошибка последней попытки архивации (для мониторинга), NULL если ок.
    archive_error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
