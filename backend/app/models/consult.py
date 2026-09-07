"""Диалоги «Поможем выбрать»: переписка клиента с продавцом."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ConsultSender, ConsultStatus
from app.models.base import Base, TimestampMixin


class ConsultThread(Base, TimestampMixin):
    """Один диалог на клиента. Повторные обращения продолжают ту же переписку."""

    __tablename__ = "consult_threads"
    __table_args__ = (UniqueConstraint("client_id", name="uq_consult_thread_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ConsultStatus] = mapped_column(
        String(16), default=ConsultStatus.OPEN, nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_preview: Mapped[str | None] = mapped_column(String(255))
    last_sender: Mapped[ConsultSender | None] = mapped_column(String(16))
    unread_admin: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Сценарий из админки: бот заберёт и выставит FSM ({state, order_id?, code}).
    pending_fsm: Mapped[dict | None] = mapped_column(JSON)


class ConsultMessage(Base, TimestampMixin):
    """Сообщение в диалоге: текст и/или вложения."""

    __tablename__ = "consult_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("consult_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[ConsultSender] = mapped_column(String(16), nullable=False)
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list | None] = mapped_column(JSON)
