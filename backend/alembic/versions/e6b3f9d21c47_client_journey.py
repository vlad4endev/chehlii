"""client journey: last_msg_code + last_msg_at

Revision ID: e6b3f9d21c47
Revises: d4f2a7c1e831
Create Date: 2026-07-16 22:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6b3f9d21c47'
down_revision: Union[str, None] = 'd4f2a7c1e831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('last_msg_code', sa.String(length=32), nullable=True))
    op.add_column('clients', sa.Column('last_msg_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'last_msg_at')
    op.drop_column('clients', 'last_msg_code')
