"""БД Чехлов. Цена = Себес + Маржа, единая для типа (не зависит от модели iPhone)."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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
    # Тип пластины для этого чехла (склад: plate silver|black). По умолчанию чёрная.
    plate_type: Mapped[str | None] = mapped_column(String(16), default="black", server_default="black")

    models: Mapped[list[CaseTypeModel]] = relationship(
        back_populates="case_type", cascade="all, delete-orphan"
    )

    @property
    def client_price(self) -> float:
        """Цена для клиента = Себес + Маржа (расчётное поле)."""
        return float(self.cost) + float(self.margin)


class IphoneModel(Base, TimestampMixin):
    """Канон моделей iPhone. Сид — constants.IPHONE_MODELS; дальше — через админку."""

    __tablename__ = "iphone_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Группа «универсальных» моделей с общим складским остатком (см. models/warehouse.py).
    stock_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_groups.id", ondelete="SET NULL"), index=True
    )


class CaseTypeModel(Base):
    """Доступность типа чехла по модели iPhone (канон — таблица iphone_models)."""

    __tablename__ = "case_type_models"
    __table_args__ = (UniqueConstraint("case_type_id", "model_name", name="uq_case_type_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_type_id: Mapped[int] = mapped_column(
        ForeignKey("case_types.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)  # напр. "iPhone 15 Pro"
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    # Фото чехла именно на этой модели iPhone. Если пусто — в мини-аппе берётся
    # обложка типа (CaseType.photo_url), а если и её нет — рисуется вектор-мокап.
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    # Денормализованный кэш available = min(base, plate) для мини-аппа/ботов.
    # Источник истины — stock_components; обновляется в services/warehouse.py.
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    case_type: Mapped[CaseType] = relationship(back_populates="models")
