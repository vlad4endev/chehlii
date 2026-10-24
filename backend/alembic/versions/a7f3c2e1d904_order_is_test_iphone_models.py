"""orders.is_test + расширенный список моделей iPhone (26)

Revision ID: a7f3c2e1d904
Revises: c8e4a1b9d702
Create Date: 2026-10-24 17:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f3c2e1d904"
down_revision: Union[str, None] = "c8e4a1b9d702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Канонический список из Приложения А (приёмка 23.10.2026).
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


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )

    conn = op.get_bind()
    type_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM case_types")).fetchall()]
    existing = {
        (r[0], r[1])
        for r in conn.execute(
            sa.text("SELECT case_type_id, model_name FROM case_type_models")
        ).fetchall()
    }
    for type_id in type_ids:
        for name in IPHONE_MODELS:
            if (type_id, name) not in existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO case_type_models "
                        "(case_type_id, model_name, is_available, stock) "
                        "VALUES (:tid, :name, true, 0)"
                    ),
                    {"tid": type_id, "name": name},
                )
        # Модели не из списка — скрыть, не удалять (могут быть заказы).
        placeholders = ", ".join(f":n{i}" for i in range(len(IPHONE_MODELS)))
        params = {"tid": type_id, **{f"n{i}": n for i, n in enumerate(IPHONE_MODELS)}}
        conn.execute(
            sa.text(
                "UPDATE case_type_models SET is_available = false "
                f"WHERE case_type_id = :tid AND model_name NOT IN ({placeholders})"
            ),
            params,
        )


def downgrade() -> None:
    op.drop_column("orders", "is_test")
