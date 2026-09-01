"""Пользователи AdminUI (только Админ): список, создание, роли, деактивация, удаление.

Защита: нельзя убрать/деактивировать/разжаловать последнего активного Админа
и нельзя удалить самого себя (чтобы не потерять доступ к панели).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.core.security import hash_password
from app.enums import AdminRole
from app.models.admin_user import AdminUser

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    role: AdminRole
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str | None = None
    role: AdminRole = AdminRole.DESIGNER
    password: str = Field(min_length=6, max_length=128)


class UserPatch(BaseModel):
    full_name: str | None = None
    role: AdminRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


def _out(u: AdminUser) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at,
    )


async def _active_admins(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AdminUser)
            .where(AdminUser.role == AdminRole.ADMIN, AdminUser.is_active.is_(True))
        )
        or 0
    )


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminOnly, session: Session) -> list[UserOut]:
    rows = (await session.scalars(select(AdminUser).order_by(AdminUser.id))).all()
    return [_out(u) for u in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, _: AdminOnly, session: Session) -> UserOut:
    user = AdminUser(
        email=str(body.email).lower(),
        full_name=body.full_name,
        role=body.role,
        password_hash=hash_password(body.password),
        is_active=True,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Пользователь с такой почтой уже есть"
        ) from None
    await session.refresh(user)
    return _out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserPatch, _: AdminOnly, session: Session) -> UserOut:
    user = await session.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    # Проверка: не оставить систему без активного Админа.
    demoting = user.role == AdminRole.ADMIN and (
        (body.role is not None and body.role != AdminRole.ADMIN) or (body.is_active is False)
    )
    if demoting and user.is_active and await _active_admins(session) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Нельзя разжаловать/деактивировать последнего Админа"
        )

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)

    await session.commit()
    await session.refresh(user)
    return _out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: AdminOnly, session: Session) -> None:
    user = await session.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить самого себя")
    if user.role == AdminRole.ADMIN and user.is_active and await _active_admins(session) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить последнего Админа")
    await session.delete(user)
    await session.commit()
