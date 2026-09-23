"""Прокси Telegram Bot API: VLESS/Hysteria2 → локальный SOCKS, иначе socks/http напрямую.

Админка хранит ключи. Этот модуль:
- поднимает xray-core под VLESS (Reality/WS/gRPC);
- поднимает hysteria-клиент под Hysteria2 (hy2://);
- SOCKS5/HTTP отдаёт в AiohttpSession как есть;
- не падает на прямой доступ, если прокси включён — иначе бот «жив», а Telegram мёртв.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from bots.core.config import settings

log = logging.getLogger(__name__)

XRAY_VERSION = "26.1.23"
HYSTERIA_VERSION = "2.12.2"
_SOCKS_PORT = 10808
_DIR = Path(__file__).resolve().parents[1] / ".xray"
_CONFIG = _DIR / "config.json"
_HY_DIR = Path(__file__).resolve().parents[1] / ".hysteria"
_HY_CONFIG = _HY_DIR / "config.yaml"

_ASSETS = {
    ("Linux", "x86_64"): "Xray-linux-64.zip",
    ("Linux", "aarch64"): "Xray-linux-arm64-v8a.zip",
    ("Darwin", "x86_64"): "Xray-macos-64.zip",
    ("Darwin", "arm64"): "Xray-macos-arm64-v8a.zip",
}

_HY_ASSETS = {
    ("Linux", "x86_64"): "hysteria-linux-amd64",
    ("Linux", "amd64"): "hysteria-linux-amd64",
    ("Linux", "aarch64"): "hysteria-linux-arm64",
    ("Darwin", "x86_64"): "hysteria-darwin-amd64",
    ("Darwin", "arm64"): "hysteria-darwin-arm64",
}


class ProxyError(RuntimeError):
    pass


def _redact(text: str) -> str:
    """Не светить UUID и query VLESS в логах."""
    out = text
    for needle in ("vless://", "hysteria2://", "hy2://", "socks5://", "socks5h://", "socks://", "http://"):
        if needle in out.lower():
            return needle + "…"
    if len(out) > 220:
        return out[:220] + "…"
    return out


def _xray_bin() -> Path | None:
    env = os.environ.get("XRAY_BIN")
    if env and Path(env).is_file():
        return Path(env)
    which = shutil.which("xray")
    if which:
        return Path(which)
    local = _DIR / "xray"
    if local.is_file():
        return local
    return None


def _download_xray() -> Path:
    key = (platform.system(), platform.machine())
    asset = _ASSETS.get(key)
    if not asset:
        raise ProxyError(
            f"Нет сборки xray для {key[0]}/{key[1]}. Поставьте xray в PATH или XRAY_BIN."
        )
    url = (
        f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}/{asset}"
    )
    _DIR.mkdir(parents=True, exist_ok=True)
    zip_path = _DIR / asset
    log.info("Telegram: скачиваем xray-core %s", XRAY_VERSION)
    with urlopen(url, timeout=60) as resp, zip_path.open("wb") as fh:  # noqa: S310
        shutil.copyfileobj(resp, fh)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("xray", _DIR)
    zip_path.unlink(missing_ok=True)
    bin_path = _DIR / "xray"
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_path


def ensure_xray() -> Path:
    found = _xray_bin()
    if found:
        return found
    return _download_xray()


def _hysteria_bin() -> Path | None:
    env = os.environ.get("HYSTERIA_BIN")
    if env and Path(env).is_file():
        return Path(env)
    which = shutil.which("hysteria")
    if which:
        return Path(which)
    local = _HY_DIR / "hysteria"
    if local.is_file():
        return local
    vendored = Path(__file__).resolve().parents[1] / "hysteria"
    if vendored.is_file():
        return vendored
    return None


def _download_hysteria() -> Path:
    key = (platform.system(), platform.machine())
    asset = _HY_ASSETS.get(key)
    if not asset:
        raise ProxyError(
            f"Нет сборки hysteria для {key[0]}/{key[1]}. Поставьте hysteria в PATH или HYSTERIA_BIN."
        )
    urls = [
        f"https://github.com/apernet/hysteria/releases/download/app%2Fv{HYSTERIA_VERSION}/{asset}",
        f"https://download.hysteria.network/app/v{HYSTERIA_VERSION}/{asset}",
    ]
    _HY_DIR.mkdir(parents=True, exist_ok=True)
    dest = _HY_DIR / "hysteria"
    last_err: Exception | None = None
    log.info("Telegram: скачиваем hysteria %s", HYSTERIA_VERSION)
    for url in urls:
        try:
            with urlopen(url, timeout=60) as resp, dest.open("wb") as fh:  # noqa: S310
                shutil.copyfileobj(resp, fh)
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return dest
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise ProxyError(f"Не удалось скачать hysteria: {last_err}")


def ensure_hysteria() -> Path:
    found = _hysteria_bin()
    if found:
        return found
    return _download_hysteria()


class XrayProcess:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._fingerprint: str | None = None

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        self._fingerprint = None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def apply(self, config: dict[str, Any], fingerprint: str) -> None:
        if self._proc and self._proc.returncode is None and self._fingerprint == fingerprint:
            return
        bin_path = ensure_xray()
        _DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        _CONFIG.chmod(0o600)
        await self.stop()
        self._proc = await asyncio.create_subprocess_exec(
            str(bin_path),
            "run",
            "-c",
            str(_CONFIG),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        port = int((config.get("inbounds") or [{}])[0].get("port") or _SOCKS_PORT)
        try:
            await _wait_port(port, timeout=8)
        except ProxyError:
            err = b""
            if self._proc.stderr:
                try:
                    err = await asyncio.wait_for(self._proc.stderr.read(), timeout=1)
                except TimeoutError:
                    err = b""
            await self.stop()
            raise ProxyError(f"xray не слушает SOCKS :{port}: {_redact(err.decode(errors='replace'))}")
        if self._proc.returncode is not None:
            raise ProxyError("xray сразу завершился")
        self._fingerprint = fingerprint
        log.info("Telegram: xray слушает socks5://127.0.0.1:%s", port)


class HysteriaProcess:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._fingerprint: str | None = None

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        self._fingerprint = None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def apply(self, config: dict[str, Any], fingerprint: str) -> None:
        if self._proc and self._proc.returncode is None and self._fingerprint == fingerprint:
            return
        bin_path = ensure_hysteria()
        _HY_DIR.mkdir(parents=True, exist_ok=True)
        _HY_CONFIG.write_text(_hysteria_yaml(config), encoding="utf-8")
        _HY_CONFIG.chmod(0o600)
        await self.stop()
        self._proc = await asyncio.create_subprocess_exec(
            str(bin_path),
            "client",
            "-c",
            str(_HY_CONFIG),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        listen = ((config.get("socks5") or {}).get("listen") or f"127.0.0.1:{_SOCKS_PORT}")
        port = int(str(listen).rsplit(":", 1)[-1])
        try:
            await _wait_port(port, timeout=10)
        except ProxyError:
            err = b""
            if self._proc.stderr:
                try:
                    err = await asyncio.wait_for(self._proc.stderr.read(), timeout=1)
                except TimeoutError:
                    err = b""
            await self.stop()
            raise ProxyError(
                f"hysteria не слушает SOCKS :{port}: {_redact(err.decode(errors='replace'))}"
            )
        if self._proc.returncode is not None:
            raise ProxyError("hysteria сразу завершился")
        self._fingerprint = fingerprint
        log.info("Telegram: hysteria слушает socks5://127.0.0.1:%s", port)


async def _wait_port(port: int, timeout: float) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    last: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=0.4
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            del reader
            return
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(0.15)
    raise ProxyError(f"порт 127.0.0.1:{port} не открылся ({last})")


xray = XrayProcess()
hysteria = HysteriaProcess()


def _hysteria_yaml(obj: dict[str, Any], indent: int = 0) -> str:
    """Мини-дамп YAML без PyYAML: только dict / bool / число / строка."""
    lines: list[str] = []
    pad = "  " * indent
    for key, value in obj.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            nested = _hysteria_yaml(value, indent + 1).rstrip("\n")
            if nested:
                lines.append(nested)
        elif isinstance(value, bool):
            lines.append(f"{pad}{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{pad}{key}: {value}")
        else:
            lines.append(f"{pad}{key}: {json.dumps('' if value is None else str(value), ensure_ascii=False)}")
    return "\n".join(lines) + ("\n" if indent == 0 else "")


async def stop_local() -> None:
    await xray.stop()
    await hysteria.stop()


def env_fallback_url() -> str | None:
    url = (settings.tg_proxy or "").strip()
    return url or None


def session_url_for(candidate: dict[str, Any]) -> str:
    if candidate.get("kind") in {"vless", "hysteria2"}:
        return candidate.get("socks_url") or f"socks5://127.0.0.1:{_SOCKS_PORT}"
    url = candidate.get("proxy_url")
    if not url:
        raise ProxyError("У ключа нет адреса прокси")
    return url


async def prepare_candidate(candidate: dict[str, Any], fingerprint: str) -> str:
    """Поднять xray/hysteria и вернуть URL для AiohttpSession."""
    kind = candidate.get("kind")
    tag = f"{fingerprint}:{candidate.get('id')}"
    if kind == "vless":
        cfg = candidate.get("xray_config")
        if not isinstance(cfg, dict):
            raise ProxyError("Нет конфига xray для VLESS-ключа")
        await hysteria.stop()
        await xray.apply(cfg, fingerprint=tag)
        return session_url_for(candidate)
    if kind == "hysteria2":
        cfg = candidate.get("hysteria_config")
        if not isinstance(cfg, dict):
            raise ProxyError("Нет конфига hysteria для Hysteria2-ключа")
        await xray.stop()
        await hysteria.apply(cfg, fingerprint=tag)
        return session_url_for(candidate)
    await stop_local()
    return session_url_for(candidate)
