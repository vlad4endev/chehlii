"""Склад: балванки (base) и пластины (plate) по моделям iPhone."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class StockComponent(Base):
    """Единица складского учёта: балванка или пластина под модель.

    Уникальность (kind, model_name, coalesce(plate_type,'')) — в миграции
    `b9e2c4a7f103` (NULL у балванок иначе дублировался бы в UNIQUE).
    """

    __tablename__ = "stock_components"
    __table_args__ = (CheckConstraint("qty >= 0", name="ck_stock_components_qty_nonneg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # base | plate
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # null для балванки; silver|black для пластины
    plate_type: Mapped[str | None] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    movements: Mapped[list[StockMovement]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )


class StockGroup(Base):
    """Группа моделей iPhone с общим складским остатком («универсальные» модели).

    Остаток хранится в stock_components под именем группы (model_name = name),
    а не под каждой моделью. scope — что именно общее: both | base | plate.
    """

    __tablename__ = "stock_groups"
    __table_args__ = (
        CheckConstraint("scope IN ('both', 'base', 'plate')", name="ck_stock_groups_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(8), default="both", server_default="both", nullable=False
    )


class StockMovement(Base):
    """Движение по компоненту: поставка, брак, заказ, корректировка."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    component_id: Mapped[int] = mapped_column(
        ForeignKey("stock_components.id", ondelete="CASCADE"), nullable=False
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    # Если запись — отмена другой (сторно), здесь id отменённой. Уникально: отменить дважды нельзя.
    reverses_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    component: Mapped[StockComponent] = relationship(back_populates="movements")
