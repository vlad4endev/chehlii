"""Настройки → Интеграции (только Админ): креды внешних сервисов и статус связи.

Секретные значения наружу не отдаются — только признак «задано». При сохранении
пустой секрет = «не менять». Бейдж «подключено» на карточке — это лишь «ключ задан»;
живую связь показывает кнопка проверки на каждой карточке.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.api.v1.delivery import cdek_cfg, yandex_cfg
from app.api.v1.payments import robokassa_cfg, yandexpay_cfg
from app.core.database import get_session
from app.services import cdek, integrations, robokassa, yandex_delivery, yandex_disk, yandex_pay

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


@router.post("/yandex-delivery/check", response_model=ConnectionOut)
async def check_yandex_delivery(_: AdminOnly, session: Session) -> ConnectionOut:
    """Статус связи с Яндекс Доставкой: location/detect без побочных эффектов."""
    ok, detail = await yandex_delivery.check_connection(await yandex_cfg(session))
    return ConnectionOut(ok=ok, detail=detail)


@router.post("/cdek/check", response_model=ConnectionOut)
async def check_cdek(_: AdminOnly, session: Session) -> ConnectionOut:
    """Статус связи со СДЭК: OAuth + справочник городов, заказов не создаёт."""
    ok, detail = await cdek.check_connection(await cdek_cfg(session))
    return ConnectionOut(ok=ok, detail=detail)


class OAuthUrlOut(BaseModel):
    url: str
    response_type: str


class YandexDiskOAuthIn(BaseModel):
    access_token: str | None = None
    code: str | None = None
    redirect_uri: str | None = None


@router.get("/yandex-disk/oauth-url", response_model=OAuthUrlOut)
async def yandex_disk_oauth_url(
    _: AdminOnly,
    session: Session,
    redirect_uri: str | None = None,
) -> OAuthUrlOut:
    """Ссылка на oauth.yandex.ru/authorize по сохранённому Client ID.

    Если задан Client secret — code flow, иначе implicit token (как в quickstart).
    """
    client_id = await integrations.get(session, "yandex_disk.client_id")
    if not client_id:
        raise HTTPException(
            400,
            "Сначала сохраните Client ID приложения с oauth.yandex.ru.",
        )
    secret = await integrations.get(session, "yandex_disk.client_secret")
    response_type = "code" if secret else "token"
    try:
        url = yandex_disk.authorize_url(
            client_id, redirect_uri=redirect_uri, response_type=response_type
        )
    except yandex_disk.YandexDiskError as e:
        raise HTTPException(400, str(e)) from e
    return OAuthUrlOut(url=url, response_type=response_type)


@router.post("/yandex-disk/oauth", response_model=ConnectionOut)
async def complete_yandex_disk_oauth(
    body: YandexDiskOAuthIn, _: AdminOnly, session: Session
) -> ConnectionOut:
    """Сохранить токен из implicit-flow или обменять code на access_token."""
    token: str | None = None
    if body.access_token:
        token = yandex_disk.sanitize_token(body.access_token)
        if not token:
            raise HTTPException(400, "Пустой OAuth-токен.")
    elif body.code:
        client_id = await integrations.get(session, "yandex_disk.client_id")
        secret = await integrations.get(session, "yandex_disk.client_secret")
        if not client_id or not secret:
            raise HTTPException(
                400,
                "Для обмена кода сохраните Client ID и Client secret, затем повторите.",
            )
        try:
            token = await yandex_disk.exchange_code(
                client_id=client_id,
                client_secret=secret,
                code=body.code,
                redirect_uri=body.redirect_uri,
            )
        except yandex_disk.YandexDiskError as e:
            raise HTTPException(400, str(e)) from e
    else:
        raise HTTPException(400, "Нужен access_token или code из ответа Яндекса.")

    await integrations.set_many(session, {"yandex_disk.oauth_token": token})
    root = await integrations.get(session, "yandex_disk.root", "/chechlii/orders")
    ok, detail = await yandex_disk.check_connection(token=token, root=root)
    return ConnectionOut(ok=ok, detail=detail)


@router.post("/yandex-disk/check", response_model=ConnectionOut)
async def check_yandex_disk(_: AdminOnly, session: Session) -> ConnectionOut:
    """Статус связи с Яндекс.Диском: метаданные диска, папок не создаёт."""
    token = await integrations.get(session, "yandex_disk.oauth_token")
    if not token:
        raise HTTPException(
            400, "Яндекс.Диск не настроен — задайте токен в «Настройки → Интеграции»."
        )
    root = await integrations.get(session, "yandex_disk.root", "/chechlii/orders")
    ok, detail = await yandex_disk.check_connection(token=token, root=root)
    return ConnectionOut(ok=ok, detail=detail)


@router.post("/robokassa/check", response_model=ConnectionOut)
async def check_robokassa(_: AdminOnly, session: Session) -> ConnectionOut:
    """Статус связи с Robokassa: OpStateExt по чужому счёту, платежей не создаёт."""
    cfg = await robokassa_cfg(session)
    ok, detail = await robokassa.check_connection(
        login=cfg["login"], password2=cfg["pass2"], is_test=cfg["is_test"]
    )
    return ConnectionOut(ok=ok, detail=detail)
