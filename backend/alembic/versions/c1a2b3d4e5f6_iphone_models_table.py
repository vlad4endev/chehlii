"""Таблица канона моделей iPhone (админ может добавлять).

Revision ID: c1a2b3d4e5f6
Revises: b9e2c4a7f103
Create Date: 2026-10-24 22:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "b9e2c4a7f103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Посев из app.constants.IPHONE_MODELS на момент миграции.
_SEED = [
    "iPhone 11",
    "iPhone 12",
    "iPhone 12 Pro",
    "iPhone 12 Pro Max",
    "iPhone 13",
    "iPhone 13 Pro",
    "iPhone 13 Pro Max",
    "iPhone 14",
    "iPhone 14 Plus",
    "iPhone 14 Pro",
    "iPhone 14 Pro Max",
    "iPhone 15",
    "iPhone 15 Plus",
    "iPhone 15 Pro",
    "iPhone 15 Pro Max",
    "iPhone 16",
    "iPhone 16 Plus",
    "iPhone 16 Pro",
    "iPhone 16 Pro Max",
    "iPhone 17",
    "iPhone 17 Air",
    "iPhone 17 Pro",
    "iPhone 17 Pro Max",
    "iPhone 18",
    "iPhone 18 Pro",
    "iPhone 18 Pro Max",
]


def upgrade() -> None:
    op.create_table(
        "iphone_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_iphone_models_name"),
    )
    op.create_index("ix_iphone_models_sort_order", "iphone_models", ["sort_order"])

    models = sa.table(
        "iphone_models",
        sa.column("name", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        models,
        [{"name": n, "sort_order": i} for i, n in enumerate(_SEED)],
    )


def downgrade() -> None:
    op.drop_index("ix_iphone_models_sort_order", table_name="iphone_models")
    op.drop_table("iphone_models")
