"""БД Клиентов. Скидки задаются вручную; total_discount = сумма трёх компонент (ТЗ v2.0)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import Channel
from app.models.base import Base, TimestampMixin


class Client(Base, TimestampMixin):
    __tablename__ = "clients"
    __table_args__ = (
        # Один человек в ТГ и МАКС — два разных клиента. Уникальность в пределах канала.
        UniqueConstraint("channel", "channel_user_id", name="uq_client_channel_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    phone: Mapped[str | None] = mapped_column(String(32))  # из кнопки «Поделиться контактом»
    channel: Mapped[Channel] = mapped_column(String(8), nullable=False)
    channel_user_id: Mapped[str] = mapped_column(String(64), nullable=False)  # tg_id / max_id
    nickname: Mapped[str | None] = mapped_column(String(255))
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Мягкое удаление: не NULL → клиент в корзине (скрыт из списков, можно восстановить).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Мастер-код (пришёл от друга)
    master_code: Mapped[str | None] = mapped_column(String(64))
    date_master_code: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discount_master_code: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    # Slave-код (персональный код клиента для друзей)
    slave_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    discount_slave_code: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    number_slave: Mapped[int] = mapped_column(default=0)
    discount_for_slave: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    # Лояльность и итог
    number_orders: Mapped[int] = mapped_column(default=0)
    loyal_discount: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    total_discount: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    # Клиентский путь: последнее коданное сообщение бота (msg_XXX) и когда оно ушло.
    # См. services/journey.py — обновляется из ботов через backend API.
    last_msg_code: Mapped[str | None] = mapped_column(String(32))
    last_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
