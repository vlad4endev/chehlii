"""Склад: группы «универсальных» моделей с общим остатком.

Revision ID: f1a2b3c4d5e6
Revises: c1a2b3d4e5f6
Create Date: 2026-11-23 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(8), nullable=False, server_default="both"),
        sa.CheckConstraint("scope IN ('both', 'base', 'plate')", name="ck_stock_groups_scope"),
    )
    op.add_column(
        "iphone_models",
        sa.Column(
            "stock_group_id",
            sa.Integer(),
            sa.ForeignKey("stock_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_iphone_models_stock_group_id", "iphone_models", ["stock_group_id"])


def downgrade() -> None:
    # Остатки группы лежат в stock_components под именем группы, а не под моделями.
    # Без распада групп откат оставил бы «осиротевшие» позиции, поэтому останавливаемся.
    conn = op.get_bind()
    in_use = conn.execute(sa.text("SELECT count(*) FROM stock_groups")).scalar()
    if in_use:
        raise RuntimeError(
            "Есть группы моделей на складе: сначала распустите их в админке "
            "(Склад → Группы моделей), иначе остатки группы потеряются."
        )
    op.drop_index("ix_iphone_models_stock_group_id", table_name="iphone_models")
    op.drop_column("iphone_models", "stock_group_id")
    op.drop_table("stock_groups")
