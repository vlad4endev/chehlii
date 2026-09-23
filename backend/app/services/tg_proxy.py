"""Хранение ключей прокси Telegram в integration_settings.

Разбор ссылок и xray-конфиг — в tg_proxy_parse (без SQLAlchemy).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import IntegrationSetting
from app.services.tg_proxy_parse import (
    SOCKS_PORT,
    ProxyParseError,
    add_uris,
    candidate,
    extract_uris,
    fingerprint,
    hysteria_config,
    parse_share_link,
    public_key,
    xray_config,
)

__all__ = [
    "SOCKS_PORT",
    "ProxyParseError",
    "add_uris",
    "candidate",
    "extract_uris",
    "fingerprint",
    "hysteria_config",
    "parse_share_link",
    "public_key",
    "xray_config",
]

KEY_ENABLED = "tg_proxy.enabled"
KEY_KEYS = "tg_proxy.keys"
KEY_STATUS = "tg_proxy.bot_status"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


async def _get_row(session: AsyncSession, key: str) -> str | None:
    row = await session.get(IntegrationSetting, key)
    if row and row.value:
        return row.value
    return None


async def _put_row(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(IntegrationSetting, key)
    if row is None:
        session.add(IntegrationSetting(key=key, value=value))
    else:
        row.value = value


async def load_state(
    session: AsyncSession,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    enabled_raw = await _get_row(session, KEY_ENABLED)
    enabled = (enabled_raw or "").strip().lower() in {"1", "true", "yes", "on"}
    keys_raw = await _get_row(session, KEY_KEYS)
    keys: list[dict[str, Any]] = []
    if keys_raw:
        try:
            loaded = json.loads(keys_raw)
            if isinstance(loaded, list):
                keys = [k for k in loaded if isinstance(k, dict) and k.get("uri") and k.get("id")]
        except json.JSONDecodeError:
            keys = []
    status_raw = await _get_row(session, KEY_STATUS)
    status: dict[str, Any] | None = None
    if status_raw:
        try:
            parsed = json.loads(status_raw)
            if isinstance(parsed, dict):
                status = parsed
        except json.JSONDecodeError:
            status = None
    return enabled, keys, status


async def save_keys(session: AsyncSession, keys: list[dict[str, Any]]) -> None:
    await _put_row(session, KEY_KEYS, json.dumps(keys, ensure_ascii=False))
    await session.commit()


async def save_enabled(session: AsyncSession, enabled: bool) -> None:
    await _put_row(session, KEY_ENABLED, "true" if enabled else "false")
    await session.commit()


async def save_bot_status(
    session: AsyncSession,
    *,
    ok: bool,
    detail: str,
    via: str | None = None,
    fingerprint_value: str | None = None,
) -> None:
    payload = {
        "ok": ok,
        "detail": (detail or "")[:400],
        "via": via,
        "fingerprint": fingerprint_value,
        "updated_at": _now_iso(),
    }
    await _put_row(session, KEY_STATUS, json.dumps(payload, ensure_ascii=False))
    await session.commit()


async def check_tcp(host: str, port: int, timeout: float = 4.0) -> tuple[bool, str]:
    """Проба TCP до сервера прокси (не до Telegram). Заказов не создаёт."""
    import asyncio

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        _ = reader
        return True, f"{host}:{port} отвечает"
    except TimeoutError:
        return False, f"{host}:{port} не ответил за {int(timeout)} с"
    except OSError as e:
        return False, f"{host}:{port} — {e.strerror or e}"
