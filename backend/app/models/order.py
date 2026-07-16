"""БД Заказов + история статусов. Финансовые поля скрыты от роли Дизайнер."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import CaseBranch, DeliveryService, OrderStatus, PaymentStatus
from app.models.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    case_type_id: Mapped[int | None] = mapped_column(ForeignKey("case_types.id"))

    branch: Mapped[CaseBranch | None] = mapped_column(String(16))  # standard / custom
    model_name: Mapped[str | None] = mapped_column(String(64))  # модель iPhone
    status: Mapped[OrderStatus] = mapped_column(
        String(40), default=OrderStatus.CASE_TYPE_SELECTED, nullable=False
    )

    # Кастом: текст пожелания + ссылки на файлы в Яндекс Диске (/client/)
    materials_text: Mapped[str | None] = mapped_column(Text)
    materials_files: Mapped[list | None] = mapped_column(JSON)
    # Стандарт: имя/буква для чехла
    custom_text: Mapped[str | None] = mapped_column(String(255))
    # Макет дизайнера — ссылка на файл в Яндекс Диске (/design/)
    mockup_url: Mapped[str | None] = mapped_column(String(1024))

    # Финансовая фиксация на момент оформления (скрыто от Дизайнера)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    margin: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_discount: Mapped[float | None] = mapped_column(Numeric(5, 2))  # применённая скидка, %
    delivery_cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    final_price: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # Доставка
    delivery_service: Mapped[DeliveryService | None] = mapped_column(String(16))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    tracking_code: Mapped[str | None] = mapped_column(String(128))
    payment_status: Mapped[PaymentStatus | None] = mapped_column(String(16))

    # Мягкое удаление: не NULL → заказ в корзине (скрыт из списков, можно восстановить).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Таймер авто-отмены: момент выставления последней ссылки на оплату.
    payment_link_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Задел под этап 3 (автоматизация дизайнера / ИИ-анализ) — не используется в этапе 1.
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)

    status_history: Mapped[list[OrderStatusHistory]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(String(40), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(64))  # "system" | admin_user.id
    trigger: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order: Mapped[Order] = relationship(back_populates="status_history")
