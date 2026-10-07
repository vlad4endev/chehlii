"""media_assets: реестр файлов с sha256 и disk_url

Revision ID: c8e4a1b9d702
Revises: b2c3d4e5f6a7
Create Date: 2026-10-07 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e4a1b9d702"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("local_url", sa.String(length=1024), nullable=False),
        sa.Column("disk_url", sa.String(length=1024), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="file"),
        sa.Column("owner_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("archive_error", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_media_assets_local_url", "media_assets", ["local_url"], unique=True)
    op.create_index("ix_media_assets_sha256", "media_assets", ["sha256"])
    op.create_index("ix_media_assets_owner", "media_assets", ["owner_type", "owner_id"])

    # Бэкфилл известных URL из заказов (без sha256 локального файла — placeholder).
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO media_assets (
                storage_key, local_url, disk_url, sha256, mime, size_bytes,
                kind, owner_type, owner_id, archived_at
            )
            SELECT
                CASE
                    WHEN o.mockup_url LIKE '/media/%'
                    THEN substring(o.mockup_url from 8)
                    ELSE o.mockup_url
                END,
                o.mockup_url,
                o.mockup_disk_url,
                repeat('0', 64),
                'application/octet-stream',
                0,
                'image',
                'order_mockup',
                o.id::text,
                CASE WHEN o.mockup_disk_url IS NOT NULL THEN now() ELSE NULL END
            FROM orders o
            WHERE o.mockup_url IS NOT NULL
              AND o.mockup_url <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM media_assets m WHERE m.local_url = o.mockup_url
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_owner", table_name="media_assets")
    op.drop_index("ix_media_assets_sha256", table_name="media_assets")
    op.drop_index("ix_media_assets_local_url", table_name="media_assets")
    op.drop_table("media_assets")
