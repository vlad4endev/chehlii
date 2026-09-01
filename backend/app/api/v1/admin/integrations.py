"""Настройки → Интеграции (только Админ): креды внешних сервисов и статус связи.

Секретные значения наружу не отдаются — только признак «задано». При сохранении
пустой секрет = «не менять». Бейдж «подключено» на карточке — это лишь «ключ задан»;
живую связь с банком показывает кнопка проверки (см. check_yandex_pay).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.api.v1.payments import yandexpay_cfg
from app.core.database import get_session
from app.services import integrations, yandex_pay

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class FieldOut(BaseModel):
    key: str
    label: str
    secret: bool
    placeholder: str | None = None
    is_set: bool
    value: str | None = None  # для секретов всегда None


class GroupOut(BaseModel):
    id: str
    title: str
    hint: str
    fields: list[FieldOut]


class IntegrationsPatch(BaseModel):
    values: dict[str, str]


class ConnectionOut(BaseModel):
    ok: bool
    detail: str


@router.get("", response_model=list[GroupOut])
async def get_integrations(_: AdminOnly, session: Session) -> list[GroupOut]:
    current = await integrations.current_values(session)
    groups: list[GroupOut] = []
    for g in integrations.INTEGRATION_SCHEMA:
        fields: list[FieldOut] = []
        for f in g["fields"]:
            key = f["key"]
            # Текущее значение с учётом env-фоллбэка.
            resolved = await integrations.get(session, key)
            is_set = bool(current.get(key) or resolved)
            fields.append(
                FieldOut(
                    key=key,
                    label=f["label"],
                    secret=f["secret"],
                    placeholder=f.get("placeholder"),
                    is_set=is_set,
                    value=None if f["secret"] else resolved,
                )
            )
        groups.append(GroupOut(id=g["id"], title=g["title"], hint=g["hint"], fields=fields))
    return groups


@router.patch("", response_model=list[GroupOut])
async def save_integrations(
    body: IntegrationsPatch, admin: AdminOnly, session: Session
) -> list[GroupOut]:
    await integrations.set_many(session, body.values)
    return await get_integrations(admin, session)


@router.post("/yandex-pay/check", response_model=ConnectionOut)
async def check_yandex_pay(_: AdminOnly, session: Session) -> ConnectionOut:
    """Статус связи с Яндекс Пэй: проба по сохранённым кредам, заказов не создаёт."""
    ok, detail = await yandex_pay.check_connection(await yandexpay_cfg(session))
    return ConnectionOut(ok=ok, detail=detail)
