"""БД Чехлов. Цена = Себес + Маржа, единая для типа (не зависит от модели iPhone)."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class CaseType(Base, TimestampMixin):
    __tablename__ = "case_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # уникальное название типа
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)  # Кастом Да/Нет
    description: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Финансовые поля — скрыты от роли Дизайнер на уровне сериализации API.
    cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)  # Себес
    margin: Mapped[float] = mapped_column(Numeric(12, 2), default=0)  # Маржа

    models: Mapped[list[CaseTypeModel]] = relationship(
        back_populates="case_type", cascade="all, delete-orphan"
    )

    @property
    def client_price(self) -> float:
        """Цена для клиента = Себес + Маржа (расчётное поле)."""
        return float(self.cost) + float(self.margin)


class CaseTypeModel(Base):
    """Доступность типа чехла по модели iPhone (iPhone 14 … iPhone 17 Air)."""

    __tablename__ = "case_type_models"
    __table_args__ = (UniqueConstraint("case_type_id", "model_name", name="uq_case_type_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_type_id: Mapped[int] = mapped_column(
        ForeignKey("case_types.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)  # напр. "iPhone 15 Pro"
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

    case_type: Mapped[CaseType] = relationship(back_populates="models")
