"""soft delete (trash) for clients and orders

Revision ID: 9c2f5a1b7e40
Revises: 7b1e2c4a9f10
Create Date: 2026-07-16 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9c2f5a1b7e40'
down_revision: Union[str, None] = '7b1e2c4a9f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'deleted_at')
    op.drop_column('clients', 'deleted_at')
