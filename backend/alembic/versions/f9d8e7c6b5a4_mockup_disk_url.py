"""orders.mockup_disk_url: архивная ссылка на Яндекс.Диск

Revision ID: f9d8e7c6b5a4
Revises: e6b3f9d21c47
Create Date: 2026-09-07 22:25:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9d8e7c6b5a4"
down_revision: Union[str, None] = "e6b3f9d21c47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("mockup_disk_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "mockup_disk_url")
