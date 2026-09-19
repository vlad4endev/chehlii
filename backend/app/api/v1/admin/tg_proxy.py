"""Настройки → Прокси (только Админ): ключи VLESS/SOCKS для Telegram-бота.

Секретные URI наружу не отдаются. «Проверить» — TCP до сервера прокси,
не запрос в Telegram (его с backend всё равно не достучаться, если он
заблокирован). Живой статус Bot API пишет сам бот.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.services import tg_proxy

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


class ProxyKeyOut(BaseModel):
    id: str
    kind: str
    label: str
    host: str
    port: int
    network: str | None = None
    security: str | None = None
    enabled: bool
    added_at: str | None = None


class BotStatusOut(BaseModel):
    ok: bool | None = None
    detail: str | None = None
    via: str | None = None
    updated_at: str | None = None


class TgProxyOut(BaseModel):
    enabled: bool
    keys: list[ProxyKeyOut]
    bot: BotStatusOut
    fingerprint: str


class TgProxyPatch(BaseModel):
    enabled: bool | None = None
    add: str | None = None
    remove_ids: list[str] | None = None
    set_enabled: dict[str, bool] | None = None


class KeyCheckOut(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str


class CheckOut(BaseModel):
    ok: bool
    detail: str
    keys: list[KeyCheckOut]


def _view(enabled: bool, keys: list, status: dict | None) -> TgProxyOut:
    cards: list[ProxyKeyOut] = []
    for stored in keys:
        pub = tg_proxy.public_key(stored)
        cards.append(ProxyKeyOut(**pub))
    bot = BotStatusOut()
    if status:
        bot = BotStatusOut(
            ok=status.get("ok"),
            detail=status.get("detail"),
            via=status.get("via"),
            updated_at=status.get("updated_at"),
        )
    return TgProxyOut(
        enabled=enabled,
        keys=cards,
        bot=bot,
        fingerprint=tg_proxy.fingerprint(enabled, keys),
    )


@router.get("", response_model=TgProxyOut)
async def get_tg_proxy(_: AdminOnly, session: Session) -> TgProxyOut:
    enabled, keys, status = await tg_proxy.load_state(session)
    return _view(enabled, keys, status)


@router.patch("", response_model=TgProxyOut)
async def patch_tg_proxy(body: TgProxyPatch, _: AdminOnly, session: Session) -> TgProxyOut:
    enabled, keys, status = await tg_proxy.load_state(session)
    changed = False
    if body.enabled is not None:
        enabled = body.enabled
        await tg_proxy.save_enabled(session, enabled)
        changed = True
    if body.add is not None:
        try:
            keys, _added = tg_proxy.add_uris(keys, body.add)
        except tg_proxy.ProxyParseError as e:
            raise HTTPException(400, str(e)) from e
        await tg_proxy.save_keys(session, keys)
        changed = True
    if body.remove_ids:
        drop = set(body.remove_ids)
        keys = [k for k in keys if k.get("id") not in drop]
        await tg_proxy.save_keys(session, keys)
        changed = True
    if body.set_enabled:
        by_id = {k["id"]: k for k in keys}
        for kid, on in body.set_enabled.items():
            if kid in by_id:
                by_id[kid]["enabled"] = bool(on)
        await tg_proxy.save_keys(session, keys)
        changed = True
    if not changed:
        raise HTTPException(400, "Нечего сохранять")
    enabled, keys, status = await tg_proxy.load_state(session)
    return _view(enabled, keys, status)


@router.post("/check", response_model=CheckOut)
async def check_tg_proxy(_: AdminOnly, session: Session) -> CheckOut:
    """TCP до каждого включённого сервера прокси. Telegram с backend не зовём."""
    enabled, keys, _status = await tg_proxy.load_state(session)
    if not keys:
        return CheckOut(ok=False, detail="Ключей нет — вставьте VLESS или SOCKS5.", keys=[])
    results: list[KeyCheckOut] = []
    any_ok = False
    for stored in keys:
        if not stored.get("enabled", True):
            continue
        pub = tg_proxy.public_key(stored)
        if not pub["host"] or not pub["port"]:
            results.append(
                KeyCheckOut(
                    id=pub["id"],
                    label=pub["label"],
                    ok=False,
                    detail="Ссылку не разобрали",
                )
            )
            continue
        ok, detail = await tg_proxy.check_tcp(pub["host"], pub["port"])
        any_ok = any_ok or ok
        results.append(KeyCheckOut(id=pub["id"], label=pub["label"], ok=ok, detail=detail))
    if not results:
        return CheckOut(ok=False, detail="Все ключи выключены.", keys=[])
    if not enabled:
        detail = "Сервер отвечает, но прокси выключен — Telegram пойдёт напрямую."
        if not any_ok:
            detail = "Нет TCP-связи. Прокси всё равно выключен."
        return CheckOut(ok=any_ok, detail=detail, keys=results)
    detail = (
        "Сервер прокси отвечает. Статус Telegram появится, когда бот подключится."
        if any_ok
        else "Нет TCP-связи ни с одним сервером прокси."
    )
    return CheckOut(ok=any_ok, detail=detail, keys=results)


class AddPreviewOut(BaseModel):
    kind: str
    label: str
    host: str
    port: int
    network: str | None = None
    security: str | None = None


class PreviewIn(BaseModel):
    text: str = Field(min_length=1)


@router.post("/preview", response_model=list[AddPreviewOut])
async def preview_uris(_: AdminOnly, body: PreviewIn) -> list[AddPreviewOut]:
    """Разобрать ссылки без сохранения — чтобы админ видел, что это VLESS Reality, а не мусор."""
    uris = tg_proxy.extract_uris(body.text)
    if not uris:
        raise HTTPException(400, "Не нашли ни одной ссылки vless:// / socks5:// / http://")
    out: list[AddPreviewOut] = []
    for uri in uris:
        try:
            info = tg_proxy.parse_share_link(uri)
        except tg_proxy.ProxyParseError as e:
            raise HTTPException(400, str(e)) from e
        out.append(
            AddPreviewOut(
                kind=info["kind"],
                label=info["label"],
                host=info["host"],
                port=info["port"],
                network=info.get("network"),
                security=info.get("security"),
            )
        )
    return out
