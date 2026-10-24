"""bot_messages media + promo_activations.rewarded_at

Revision ID: d1e2f3a4b5c6
Revises: a7f3c2e1d904
Create Date: 2026-10-24 17:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "a7f3c2e1d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bot_messages",
        sa.Column("media_format", sa.String(length=32), server_default="text", nullable=False),
    )
    op.add_column("bot_messages", sa.Column("media_url", sa.String(length=1024), nullable=True))
    op.add_column(
        "bot_messages", sa.Column("media_file_id_tg", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "bot_messages", sa.Column("media_poster_url", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "promo_activations",
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("promo_activations", "rewarded_at")
    op.drop_column("bot_messages", "media_poster_url")
    op.drop_column("bot_messages", "media_file_id_tg")
    op.drop_column("bot_messages", "media_url")
    op.drop_column("bot_messages", "media_format")
