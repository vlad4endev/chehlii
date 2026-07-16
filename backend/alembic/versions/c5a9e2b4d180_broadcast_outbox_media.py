"""broadcast + outbox media list (photos and videos)

Revision ID: c5a9e2b4d180
Revises: b3d7e1f0a2c5
Create Date: 2026-07-16 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5a9e2b4d180'
down_revision: Union[str, None] = 'b3d7e1f0a2c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('broadcasts', sa.Column('media', sa.JSON(), nullable=True))
    op.add_column('outbound_messages', sa.Column('media', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('outbound_messages', 'media')
    op.drop_column('broadcasts', 'media')
