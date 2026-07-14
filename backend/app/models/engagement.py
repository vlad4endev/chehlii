"""Избранное, отзывы, промокоды и их активации."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ReviewStatus
from app.models.base import Base, TimestampMixin


class Favorite(Base):
    """Избранное на сервере, привязано к клиенту. Между каналами не синхронизируется."""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("client_id", "case_type_id", name="uq_favorite"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    case_type_id: Mapped[int] = mapped_column(
        ForeignKey("case_types.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Review(Base, TimestampMixin):
    """Отзыв клиента. Публикуется только после модерации в админке."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)  # сообщение клиента в боте
    photo_url: Mapped[str | None] = mapped_column(String(1024))  # фото чехла (опционально)
    author_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ReviewStatus] = mapped_column(
        String(16), default=ReviewStatus.PENDING, nullable=False
    )


class PromoActivation(Base):
    """Факт ввода клиентом чужого промокода (для подсчёта number_slave владельца)."""

    __tablename__ = "promo_activations"
    __table_args__ = (
        UniqueConstraint(
            "client_id", name="uq_promo_activation_client"
        ),  # один мастер-код на клиента
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    discount: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
