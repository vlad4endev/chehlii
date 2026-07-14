"""Пользователи AdminUI: роли Админ / Дизайнер."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import AdminRole
from app.models.base import Base, TimestampMixin


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(String(16), default=AdminRole.DESIGNER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
