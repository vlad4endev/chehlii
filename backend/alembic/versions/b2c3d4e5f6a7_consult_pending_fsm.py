"""consult_threads.pending_fsm for admin-driven scenarios

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-07 23:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("consult_threads", sa.Column("pending_fsm", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("consult_threads", "pending_fsm")
