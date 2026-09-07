"""consult threads + messages (поможем выбрать)

Revision ID: a1b2c3d4e5f6
Revises: f9d8e7c6b5a4
Create Date: 2026-09-07 22:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f9d8e7c6b5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consult_threads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_preview", sa.String(length=255), nullable=True),
        sa.Column("last_sender", sa.String(length=16), nullable=True),
        sa.Column("unread_admin", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("client_id", name="uq_consult_thread_client"),
    )
    op.create_index("ix_consult_threads_last_message_at", "consult_threads", ["last_message_at"])

    op.create_table(
        "consult_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.BigInteger(),
            sa.ForeignKey("consult_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_consult_messages_thread_id", "consult_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_consult_messages_thread_id", table_name="consult_messages")
    op.drop_table("consult_messages")
    op.drop_index("ix_consult_threads_last_message_at", table_name="consult_threads")
    op.drop_table("consult_threads")
