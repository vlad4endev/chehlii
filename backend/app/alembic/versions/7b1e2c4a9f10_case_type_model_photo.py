"""case_type_model per-model photo

Revision ID: 7b1e2c4a9f10
Revises: 4150145b3532
Create Date: 2026-07-15 18:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7b1e2c4a9f10'
down_revision: Union[str, None] = '4150145b3532'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'case_type_models',
        sa.Column('photo_url', sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('case_type_models', 'photo_url')
