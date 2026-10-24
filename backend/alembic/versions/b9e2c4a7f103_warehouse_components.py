"""warehouse: stock_components, stock_movements, case_types.plate_type

Revision ID: b9e2c4a7f103
Revises: d1e2f3a4b5c6
Create Date: 2026-10-24 17:45:00.000000

Note: a7f3c2e1d904 already has child d1e2f3a4b5c6 (bot message media),
so this revision continues that head to keep a linear chain.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9e2c4a7f103"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Канонический список из app.constants.IPHONE_MODELS (посев компонентов).
IPHONE_MODELS = [
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

WAREHOUSE_SETTINGS = [
    ("warehouse.lookback_days", "30"),
    ("warehouse.lead_days", "14"),
    ("warehouse.safety_days", "7"),
]


def upgrade() -> None:
    op.add_column(
        "case_types",
        sa.Column("plate_type", sa.String(length=16), server_default="black", nullable=True),
    )

    op.create_table(
        "stock_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("plate_type", sa.String(length=16), nullable=True),
        sa.Column("qty", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("qty >= 0", name="ck_stock_components_qty_nonneg"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_stock_components_kind_model_plate "
        "ON stock_components (kind, model_name, coalesce(plate_type, ''))"
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("stock_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "order_id",
            sa.BigInteger(),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_stock_movements_component_id", "stock_movements", ["component_id"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])

    conn = op.get_bind()
    for model in IPHONE_MODELS:
        conn.execute(
            sa.text(
                "INSERT INTO stock_components (kind, model_name, plate_type, qty) "
                "VALUES ('base', :m, NULL, 0)"
            ),
            {"m": model},
        )
        for plate in ("silver", "black"):
            conn.execute(
                sa.text(
                    "INSERT INTO stock_components (kind, model_name, plate_type, qty) "
                    "VALUES ('plate', :m, :p, 0)"
                ),
                {"m": model, "p": plate},
            )

    for key, value in WAREHOUSE_SETTINGS:
        conn.execute(
            sa.text(
                "INSERT INTO integration_settings (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": value},
        )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
    op.drop_index("ix_stock_movements_component_id", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("uq_stock_components_kind_model_plate", table_name="stock_components")
    op.drop_table("stock_components")
    op.drop_column("case_types", "plate_type")
    conn = op.get_bind()
    for key, _ in WAREHOUSE_SETTINGS:
        conn.execute(
            sa.text("DELETE FROM integration_settings WHERE key = :k"),
            {"k": key},
        )
