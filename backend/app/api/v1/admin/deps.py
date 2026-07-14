"""RBAC-зависимости AdminUI: текущий пользователь и требование роли Админ."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_token
from app.enums import AdminRole
from app.models.admin_user import AdminUser

_bearer = HTTPBearer(auto_error=False)


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    user = await session.get(AdminUser, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь недоступен")
    return user


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


async def require_admin(user: CurrentAdmin) -> AdminUser:
    """Только роль Админ (разделы: клиенты, каталог, отзывы, тексты, рассылки, пользователи)."""
    if user.role != AdminRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав (нужна роль Админ)")
    return user


AdminOnly = Annotated[AdminUser, Depends(require_admin)]


def is_admin(user: AdminUser) -> bool:
    return user.role == AdminRole.ADMIN
