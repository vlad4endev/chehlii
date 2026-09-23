"""Внутренний API прокси Telegram: бот забирает ключи и пишет статус getMe."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services import tg_proxy

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


class CandidateOut(BaseModel):
    id: str
    kind: str
    label: str
    host: str
    port: int
    socks_url: str | None = None
    proxy_url: str | None = None
    xray_config: dict[str, Any] | None = None
    hysteria_config: dict[str, Any] | None = None


class TgProxyRuntimeOut(BaseModel):
    enabled: bool
    fingerprint: str
    socks_port: int
    candidates: list[CandidateOut]


class TgProxyStatusIn(BaseModel):
    ok: bool
    detail: str
    via: str | None = None
    fingerprint: str | None = None


@router.get("", response_model=TgProxyRuntimeOut)
async def get_runtime(session: Session) -> TgProxyRuntimeOut:
    enabled, keys, _status = await tg_proxy.load_state(session)
    candidates: list[CandidateOut] = []
    if enabled:
        for stored in keys:
            item = tg_proxy.candidate(stored)
            if item:
                candidates.append(CandidateOut(**item))
    return TgProxyRuntimeOut(
        enabled=enabled,
        fingerprint=tg_proxy.fingerprint(enabled, keys),
        socks_port=tg_proxy.SOCKS_PORT,
        candidates=candidates,
    )


@router.post("/status")
async def post_status(body: TgProxyStatusIn, session: Session) -> dict[str, bool]:
    await tg_proxy.save_bot_status(
        session,
        ok=body.ok,
        detail=body.detail,
        via=body.via,
        fingerprint_value=body.fingerprint,
    )
    return {"ok": True}
