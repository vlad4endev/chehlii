"""Транзакции оплаты. Двухступенчатая схема: предоплата + постоплата (+ доставка)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import PaymentKind, PaymentStatus
from app.models.base import Base, TimestampMixin


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[PaymentKind] = mapped_column(String(16), nullable=False)
    gateway: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # robokassa/cloudpayments/tbank
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        String(16), default=PaymentStatus.PENDING, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(128))  # id платежа в шлюзе
    payment_url: Mapped[str | None] = mapped_column(String(1024))
    # Идемпотентность webhook'ов: уникальный ключ провайдера, чтобы не обработать дважды.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    raw_webhook: Mapped[dict | None] = mapped_column(JSON)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
