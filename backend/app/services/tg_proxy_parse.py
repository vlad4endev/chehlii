"""Разбор VLESS / Hysteria2 / SOCKS / HTTP-ссылок и сборка клиентских конфигов."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

SOCKS_PORT = 10808

_SHARE_RE = re.compile(
    r"(?:vless|vmess|trojan|ss|hysteria2|hy2|hysteria|socks5h?|socks4a?|socks|https?)://[^\s<>\"']+",
    re.IGNORECASE,
)

_SUPPORTED_NET = {
    "tcp": "tcp",
    "raw": "tcp",
    "ws": "ws",
    "websocket": "ws",
    "grpc": "grpc",
    "gun": "grpc",
    "httpupgrade": "httpupgrade",
    "http_upgrade": "httpupgrade",
    "xhttp": "xhttp",
    "splithttp": "xhttp",
    "h2": "h2",
    "http": "h2",
}


class ProxyParseError(ValueError):
    """Ссылка не является поддерживаемым ключом прокси."""


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def extract_uris(blob: str) -> list[str]:
    """Достать ссылки из текста: по одной на строку или целая подписка."""
    text = (blob or "").strip()
    if not text:
        return []
    found = [m.rstrip(".,;") for m in _SHARE_RE.findall(text)]
    if found:
        return found
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip("\"'")
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def parse_share_link(raw: str) -> dict[str, Any]:
    """Разобрать одну share-ссылку. Возвращает каноническое описание ключа."""
    uri = (raw or "").strip().strip("\"'<>")
    if not uri:
        raise ProxyParseError("Пустая ссылка")
    scheme = uri.split(":", 1)[0].lower()
    if scheme == "vless":
        return _parse_vless(uri)
    if scheme in {"hysteria2", "hy2"}:
        return _parse_hysteria2(uri)
    if scheme in {"socks", "socks5", "socks5h", "socks4", "socks4a"}:
        return _parse_generic(uri, kind="socks")
    if scheme in {"http", "https"}:
        return _parse_generic(uri, kind="http")
    if scheme == "vmess":
        raise ProxyParseError("VMess не поддерживается — нужен VLESS, Hysteria2 или SOCKS5")
    if scheme == "hysteria":
        raise ProxyParseError("Hysteria 1 не поддерживается — вставьте hysteria2:// или hy2://")
    if scheme in {"trojan", "ss", "ssr", "tuic"}:
        raise ProxyParseError(f"{scheme} не поддерживается — вставьте VLESS, Hysteria2 (hy2://) или SOCKS5")
    raise ProxyParseError("Ожидалась ссылка vless://, hysteria2:// / hy2://, socks5:// или http://")


def _parse_generic(uri: str, *, kind: str) -> dict[str, Any]:
    label = ""
    body = uri
    if "#" in uri:
        body, frag = uri.split("#", 1)
        label = unquote(frag).strip()
    u = urlparse(body)
    host = u.hostname
    if not host:
        raise ProxyParseError("В ссылке нет хоста")
    port = u.port or (443 if u.scheme == "https" else 80 if kind == "http" else 1080)
    if kind == "socks":
        # aiogram/aiohttp-socks: socks5 / socks5h (DNS на прокси) / socks4.
        raw_scheme = u.scheme.lower()
        if raw_scheme in {"socks4", "socks4a"}:
            scheme = raw_scheme
        elif raw_scheme == "socks5h":
            scheme = "socks5h"
        else:
            scheme = "socks5"
    else:
        scheme = "http"
    netloc = u.netloc
    proxy_url = f"{scheme}://{netloc}"
    if not label:
        label = f"{host}:{port}"
    return {
        "kind": kind,
        "uri": uri,
        "proxy_url": proxy_url,
        "label": label,
        "host": host,
        "port": int(port),
        "network": None,
        "security": None,
        "xray_outbound": None,
    }


def _qs(u) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}


def _parse_vless(uri: str) -> dict[str, Any]:
    label = ""
    body = uri
    if "#" in uri:
        body, frag = uri.split("#", 1)
        label = unquote(frag).strip()
    u = urlparse(body)
    user_id = unquote(u.username or "").strip()
    host = u.hostname
    if not user_id:
        raise ProxyParseError("В VLESS-ссылке нет UUID")
    if not host:
        raise ProxyParseError("В VLESS-ссылке нет хоста")
    port = int(u.port or 443)
    q = _qs(u)
    net_raw = (q.get("type") or q.get("network") or "tcp").lower()
    network = _SUPPORTED_NET.get(net_raw)
    if network is None:
        raise ProxyParseError(f"Транспорт {net_raw} не поддерживается")
    security = (q.get("security") or "none").lower()
    if security not in {"none", "tls", "reality"}:
        raise ProxyParseError(f"security={security} не поддерживается")
    flow = q.get("flow") or ""
    if network != "tcp":
        flow = ""
    encryption = q.get("encryption") or "none"
    outbound = _vless_outbound(
        host=host,
        port=port,
        user_id=user_id,
        encryption=encryption,
        flow=flow,
        network=network,
        security=security,
        q=q,
    )
    if not label:
        label = f"{host}:{port}"
    return {
        "kind": "vless",
        "uri": uri,
        "proxy_url": f"socks5://127.0.0.1:{SOCKS_PORT}",
        "label": label,
        "host": host,
        "port": port,
        "network": network,
        "security": security,
        "xray_outbound": outbound,
        "hysteria_config": None,
    }


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_hy2_hostport(hostport: str, *, default_port: int = 443) -> tuple[str, int, str]:
    """Хост, порт для карточки и полный server (с port hopping) для клиента."""
    hostport = (hostport or "").strip()
    if not hostport:
        raise ProxyParseError("В Hysteria2-ссылке нет хоста")
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            raise ProxyParseError("Некорректный IPv6 в Hysteria2-ссылке")
        host = hostport[1:end]
        rest = hostport[end + 1 :]
        if rest.startswith(":"):
            rest = rest[1:]
        if not rest:
            return host, default_port, f"[{host}]:{default_port}"
        first = rest.split(",", 1)[0].split("-", 1)[0]
        try:
            port = int(first)
        except ValueError as e:
            raise ProxyParseError("Некорректный порт в Hysteria2-ссылке") from e
        return host, port, f"[{host}]:{rest}"
    if ":" not in hostport:
        return hostport, default_port, f"{hostport}:{default_port}"
    host, rest = hostport.split(":", 1)
    if not host:
        raise ProxyParseError("В Hysteria2-ссылке нет хоста")
    first = rest.split(",", 1)[0].split("-", 1)[0]
    try:
        port = int(first)
    except ValueError as e:
        raise ProxyParseError("Некорректный порт в Hysteria2-ссылке") from e
    return host, port, f"{host}:{rest}"


def _parse_hysteria2(uri: str) -> dict[str, Any]:
    label = ""
    body = uri
    if "#" in uri:
        body, frag = uri.split("#", 1)
        label = unquote(frag).strip()
    if "://" not in body:
        raise ProxyParseError("Некорректная Hysteria2-ссылка")
    rest = body.split("://", 1)[1]
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    userinfo = ""
    hostport = rest
    if "@" in rest:
        userinfo, hostport = rest.rsplit("@", 1)
    if "/" in hostport:
        hostport = hostport.split("/", 1)[0]
    host, port, server = _split_hy2_hostport(unquote(hostport))
    q = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
    auth = unquote(userinfo) if userinfo else (q.get("auth") or q.get("password") or "")
    if not auth:
        raise ProxyParseError("В Hysteria2-ссылке нет пароля (auth)")
    obfs = (q.get("obfs") or "").strip().lower()
    obfs_pass = (
        q.get("obfs-password")
        or q.get("obfs_password")
        or q.get("obfsPassword")
        or q.get("obfsParam")
        or ""
    )
    if obfs and obfs not in {"salamander", "gecko"}:
        raise ProxyParseError(f"obfs={obfs} не поддерживается")
    if obfs and not obfs_pass:
        raise ProxyParseError("Для obfuscation нужен параметр obfs-password")
    if not label:
        label = f"{host}:{port}"
    cfg = hysteria_config(
        server=server,
        auth=auth,
        sni=q.get("sni") or "",
        insecure=_truthy(q.get("insecure") or q.get("allowInsecure")),
        pin_sha256=q.get("pinSHA256") or q.get("pinsha256") or "",
        ech=q.get("ech") or "",
        obfs=obfs,
        obfs_password=obfs_pass,
        socks_port=SOCKS_PORT,
    )
    return {
        "kind": "hysteria2",
        "uri": uri,
        "proxy_url": f"socks5://127.0.0.1:{SOCKS_PORT}",
        "label": label,
        "host": host,
        "port": port,
        "network": "udp",
        "security": "tls",
        "xray_outbound": None,
        "hysteria_config": cfg,
    }


def _alpn_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    items = [p.strip() for p in unquote(raw).split(",") if p.strip()]
    return items or None


def _tls_settings(q: dict[str, str], host: str) -> dict[str, Any]:
    sni = q.get("sni") or q.get("host") or host
    allow = (q.get("allowInsecure") or q.get("insecure") or "0") in {"1", "true", "True"}
    settings: dict[str, Any] = {
        "serverName": sni,
        "allowInsecure": allow,
    }
    fp = q.get("fp") or q.get("fingerprint")
    if fp:
        settings["fingerprint"] = fp
    alpn = _alpn_list(q.get("alpn"))
    if alpn:
        settings["alpn"] = alpn
    return settings


def _reality_settings(q: dict[str, str], host: str) -> dict[str, Any]:
    pbk = q.get("pbk") or q.get("publicKey") or ""
    if not pbk:
        raise ProxyParseError("Для Reality в ссылке нужен параметр pbk (публичный ключ)")
    sni = q.get("sni") or host
    settings: dict[str, Any] = {
        "serverName": sni,
        "publicKey": pbk,
        "shortId": q.get("sid") or q.get("shortId") or "",
        "spiderX": unquote(q.get("spx") or q.get("spiderX") or "/"),
    }
    fp = q.get("fp") or q.get("fingerprint") or "chrome"
    settings["fingerprint"] = fp
    return settings


def _ws_settings(q: dict[str, str], host: str) -> dict[str, Any]:
    path = unquote(q.get("path") or "/")
    ws_host = q.get("host") or host
    return {"path": path, "host": ws_host}


def _grpc_settings(q: dict[str, str]) -> dict[str, Any]:
    name = q.get("serviceName") or q.get("servicename") or q.get("authority") or ""
    mode = q.get("mode") or "gun"
    settings: dict[str, Any] = {"serviceName": name}
    if mode:
        settings["multiMode"] = mode.lower() == "multi"
    return settings


def _tcp_header(q: dict[str, str], host: str) -> dict[str, Any] | None:
    header = (q.get("headerType") or q.get("headertype") or "none").lower()
    if header in {"", "none"}:
        return None
    if header != "http":
        raise ProxyParseError(f"headerType={header} не поддерживается")
    http_host = q.get("host") or host
    return {
        "header": {
            "type": "http",
            "request": {"headers": {"Host": [http_host]}},
        }
    }


def _vless_outbound(
    *,
    host: str,
    port: int,
    user_id: str,
    encryption: str,
    flow: str,
    network: str,
    security: str,
    q: dict[str, str],
) -> dict[str, Any]:
    user: dict[str, Any] = {"id": user_id, "encryption": encryption or "none"}
    if flow:
        user["flow"] = flow
    outbound: dict[str, Any] = {
        "protocol": "vless",
        "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
        "streamSettings": {"network": network},
    }
    stream = outbound["streamSettings"]
    if security == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = _tls_settings(q, host)
    elif security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = _reality_settings(q, host)
    else:
        stream["security"] = "none"

    if network == "ws":
        stream["wsSettings"] = _ws_settings(q, host)
    elif network == "grpc":
        stream["grpcSettings"] = _grpc_settings(q)
    elif network == "httpupgrade":
        stream["httpupgradeSettings"] = {
            "path": unquote(q.get("path") or "/"),
            "host": q.get("host") or host,
        }
    elif network == "xhttp":
        stream["xhttpSettings"] = {
            "path": unquote(q.get("path") or "/"),
            "host": q.get("host") or host,
            "mode": q.get("mode") or "auto",
        }
    elif network == "h2":
        stream["httpSettings"] = {
            "path": unquote(q.get("path") or "/"),
            "host": [q.get("host") or host],
        }
    elif network == "tcp":
        tcp = _tcp_header(q, host)
        if tcp:
            stream["tcpSettings"] = tcp
    return outbound


def hysteria_config(
    *,
    server: str,
    auth: str,
    sni: str,
    insecure: bool,
    pin_sha256: str,
    ech: str,
    obfs: str,
    obfs_password: str,
    socks_port: int = SOCKS_PORT,
) -> dict[str, Any]:
    """Конфиг hysteria-клиента: локальный SOCKS → этот HY2. Только для бота."""
    cfg: dict[str, Any] = {
        "server": server,
        "auth": auth,
        "lazy": True,
        "socks5": {"listen": f"127.0.0.1:{socks_port}", "disableUDP": True},
    }
    tls: dict[str, Any] = {}
    if sni:
        tls["sni"] = sni
    if insecure:
        tls["insecure"] = True
    if pin_sha256:
        tls["pinSHA256"] = pin_sha256
    if ech:
        tls["ech"] = ech
    if tls:
        cfg["tls"] = tls
    if obfs:
        cfg["obfs"] = {"type": obfs, obfs: {"password": obfs_password}}
    return cfg


def xray_config(outbound: dict[str, Any], socks_port: int = SOCKS_PORT) -> dict[str, Any]:
    """Полный конфиг xray: локальный SOCKS → этот VLESS. Только для бота."""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks",
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": False, "auth": "noauth"},
            }
        ],
        "outbounds": [
            {**outbound, "tag": "proxy"},
            {"tag": "direct", "protocol": "freedom"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "inboundTag": ["socks"], "outboundTag": "proxy"}],
        },
    }


def fingerprint(enabled: bool, keys: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "e": bool(enabled),
            "k": [(k.get("id"), k.get("uri"), bool(k.get("enabled", True))) for k in keys],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def public_key(stored: dict[str, Any], parsed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Карточка ключа для админки: без UUID и query."""
    info = parsed
    if info is None:
        try:
            info = parse_share_link(stored["uri"])
        except ProxyParseError:
            info = {
                "kind": "unknown",
                "label": stored.get("label") or "ключ",
                "host": "",
                "port": 0,
                "network": None,
                "security": None,
            }
    return {
        "id": stored["id"],
        "kind": info["kind"],
        "label": stored.get("label") or info.get("label") or info.get("host") or "ключ",
        "host": info.get("host") or "",
        "port": int(info.get("port") or 0),
        "network": info.get("network"),
        "security": info.get("security"),
        "enabled": bool(stored.get("enabled", True)),
        "added_at": stored.get("added_at"),
    }


def candidate(stored: dict[str, Any]) -> dict[str, Any] | None:
    """Описание ключа для бота (с xray_config / proxy_url). None если ссылка битая."""
    if not stored.get("enabled", True):
        return None
    try:
        info = parse_share_link(stored["uri"])
    except ProxyParseError:
        return None
    item: dict[str, Any] = {
        "id": stored["id"],
        "kind": info["kind"],
        "label": stored.get("label") or info["label"],
        "host": info["host"],
        "port": info["port"],
    }
    if info["kind"] == "vless" and info.get("xray_outbound"):
        item["socks_url"] = f"socks5://127.0.0.1:{SOCKS_PORT}"
        item["xray_config"] = xray_config(info["xray_outbound"], SOCKS_PORT)
        item["hysteria_config"] = None
        item["proxy_url"] = None
    elif info["kind"] == "hysteria2" and info.get("hysteria_config"):
        item["socks_url"] = f"socks5://127.0.0.1:{SOCKS_PORT}"
        item["xray_config"] = None
        item["hysteria_config"] = info["hysteria_config"]
        item["proxy_url"] = None
    else:
        item["socks_url"] = None
        item["xray_config"] = None
        item["hysteria_config"] = None
        item["proxy_url"] = info.get("proxy_url")
    return item


def add_uris(keys: list[dict[str, Any]], blob: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Добавить ключи из текста. Возвращает (новый список, метки добавленных)."""
    uris = extract_uris(blob)
    if not uris:
        raise ProxyParseError(
            "Не нашли ни одной ссылки vless:// / hysteria2:// / hy2:// / socks5:// / http://"
        )
    existing = {(k.get("uri") or "").strip() for k in keys}
    added: list[str] = []
    next_keys = list(keys)
    for uri in uris:
        if uri in existing:
            continue
        info = parse_share_link(uri)
        next_keys.append(
            {
                "id": uuid.uuid4().hex[:10],
                "uri": uri,
                "enabled": True,
                "label": info["label"],
                "added_at": _now_iso(),
            }
        )
        existing.add(uri)
        added.append(info["label"])
    if not added:
        raise ProxyParseError("Эти ключи уже сохранены")
    return next_keys, added
