"""broadcast image_url

Revision ID: b3d7e1f0a2c5
Revises: 9c2f5a1b7e40
Create Date: 2026-07-16 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d7e1f0a2c5'
down_revision: Union[str, None] = '9c2f5a1b7e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('broadcasts', sa.Column('image_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column('broadcasts', 'image_url')
