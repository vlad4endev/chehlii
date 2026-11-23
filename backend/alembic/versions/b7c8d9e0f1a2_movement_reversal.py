"""Склад: отмена движения (сторно) — связь «запись отменяет запись».

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
Create Date: 2026-11-23 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stock_movements",
        sa.Column(
            "reverses_id",
            sa.BigInteger(),
            sa.ForeignKey("stock_movements.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Одну запись можно отменить только раз — даже если два человека нажали одновременно.
    op.create_index(
        "uq_stock_movements_reverses_id",
        "stock_movements",
        ["reverses_id"],
        unique=True,
        postgresql_where=sa.text("reverses_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_stock_movements_reverses_id", table_name="stock_movements")
    op.drop_column("stock_movements", "reverses_id")
