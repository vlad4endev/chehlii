"""stock: case_type_models.stock + orders.stock_deducted

Revision ID: d4f2a7c1e831
Revises: c5a9e2b4d180
Create Date: 2026-07-16 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f2a7c1e831'
down_revision: Union[str, None] = 'c5a9e2b4d180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'case_type_models',
        sa.Column('stock', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'orders',
        sa.Column('stock_deducted', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('orders', 'stock_deducted')
    op.drop_column('case_type_models', 'stock')
