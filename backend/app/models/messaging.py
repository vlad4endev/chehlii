"""БД Сообщений от бота (редактируются через AdminUI) и рассылки."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import BotMessageMode, ScenarioType
from app.models.base import Base, TimestampMixin


class BotMessage(Base, TimestampMixin):
    """Тексты сообщений бота (msg_001…). Редактируются админом без перепрограммирования."""

    __tablename__ = "bot_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # напр. "msg_003"
    trigger: Mapped[str] = mapped_column(String(255), nullable=False)  # человекочитаемый триггер
    text: Mapped[str] = mapped_column(Text, nullable=False)
    buttons: Mapped[list | None] = mapped_column(JSON)  # список кнопок [{text, action}]
    mode: Mapped[BotMessageMode] = mapped_column(String(8), default=BotMessageMode.AUTO)
    channel_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_max: Mapped[bool] = mapped_column(Boolean, default=True)
    # Задел под этап 2: тип сценария (base — линейный; triggered — триггерные рассылки).
    scenario_type: Mapped[ScenarioType] = mapped_column(String(16), default=ScenarioType.BASE)


class Broadcast(Base, TimestampMixin):
    """Ручная рассылка выбранным сегментам клиентов (по каналу/дате/статусу)."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[dict | None] = mapped_column(JSON)  # фильтры сегмента
    created_by: Mapped[int | None] = mapped_column()  # admin_user.id
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipients_count: Mapped[int] = mapped_column(default=0)
