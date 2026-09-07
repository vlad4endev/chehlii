"""Загрузка файлов на Яндекс Диск (REST API, OAuth 2.0).

Документация: https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart

Материалы клиента → /orders/{id}/client/, макеты дизайнера → /orders/{id}/design/.
Возвращает публичную ссылку на файл (для отправки клиенту и хранения в БД).
Проба связи — GET /v1/disk (метаданные диска), папок и файлов не создаёт.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlencode, urlparse

import httpx

_API = "https://cloud-api.yandex.net/v1/disk"
_OAUTH_AUTHORIZE = "https://oauth.yandex.ru/authorize"
_OAUTH_TOKEN = "https://oauth.yandex.ru/token"
_TIMEOUT = 15.0
_JSON = "application/json"

# Права, которые нужно отметить в OAuth-приложении (Доступ к данным).
# В authorize URL их не передаём: если хоть одно не зарегистрировано,
# Яндекс отвечает invalid_scope. Токен получает права из кабинета приложения.
DISK_SCOPES = (
    "cloud_api:disk.write",
    "cloud_api:disk.read",
    "cloud_api:disk.info",
)


class YandexDiskError(RuntimeError):
    pass


_TOKEN_REJECTED = (
    "OAuth-токен отклонён Яндексом (401). Откройте «Настройки → Интеграции», "
    "нажмите «Получить токен у Яндекса» и сохраните новый — текущий истёк, "
    "обрезан или вставлен вместе с адресом страницы Яндекса."
)


def sanitize_token(raw: str | None) -> str:
    """Достать чистый access_token: URL-hash, «OAuth …», переносы строк."""
    token = (raw or "").strip().strip('"').strip("'").lstrip("\ufeff")
    if not token:
        return ""
    if "access_token=" in token:
        token = token.split("access_token=", 1)[1]
    token = token.split("&", 1)[0].split("#", 1)[0].strip()
    token = re.sub(r"^(oauth|bearer)[\s:]+", "", token, flags=re.IGNORECASE).strip()
    return "".join(token.split())


def authorize_url(
    client_id: str,
    *,
    redirect_uri: str | None = None,
    response_type: str = "token",
) -> str:
    """URL страницы Яндекс OAuth (quickstart: response_type=token, без redirect_uri).

    Свой Callback не передаём: если он не совпадает с Redirect URI в кабинете,
    Яндекс отвечает «redirect_uri не совпадает с Callback URL» и берёт
    https://oauth.yandex.ru/verification_code из настроек приложения.
    """
    cid = client_id.strip()
    if not cid:
        raise YandexDiskError("не задан Client ID приложения")
    params: dict[str, str] = {
        "response_type": response_type,
        "client_id": cid,
        "force_confirm": "yes",
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    return f"{_OAUTH_AUTHORIZE}?{urlencode(params)}"


def _headers(token: str) -> dict[str, str]:
    clean = sanitize_token(token)
    if not clean:
        raise YandexDiskError("токен Яндекс.Диска не задан")
    # Quickstart: Authorization: OAuth <token>. Accept/Content-Type — только JSON,
    # иначе API отвечает ошибкой формата (в т.ч. 406).
    return {
        "Authorization": f"OAuth {clean}",
        "Accept": _JSON,
        "Content-Type": _JSON,
    }


def _api_error(r: httpx.Response) -> str:
    if r.status_code == 401:
        return _TOKEN_REJECTED
    try:
        data = r.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("description") or data.get("error")
            if msg:
                return f"{r.status_code} {msg}"
    except Exception:
        pass
    return f"{r.status_code} {r.text[:160]}"


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str | None = None,
) -> str:
    """Обменять code из redirect на access_token (POST oauth.yandex.ru/token)."""
    cid, secret, confirmation = client_id.strip(), client_secret.strip(), code.strip()
    if not cid or not secret:
        raise YandexDiskError("для обмена кода нужны Client ID и Client secret")
    if not confirmation:
        raise YandexDiskError("не передан код подтверждения")
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": confirmation,
        "client_id": cid,
        "client_secret": secret,
    }
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            _OAUTH_TOKEN,
            data=data,
            headers={"Accept": _JSON, "Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            raise YandexDiskError(f"обмен кода: {_api_error(r)}")
        payload = r.json() if r.content else {}
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise YandexDiskError("Яндекс не вернул access_token")
        return token


async def _ensure_dirs(client: httpx.AsyncClient, path: str, token: str) -> None:
    """Создать вложенные папки по очереди (409 = уже есть — игнорируем)."""
    parts = [p for p in path.strip("/").split("/") if p]
    acc = ""
    headers = _headers(token)
    for p in parts:
        acc += "/" + p
        r = await client.put(f"{_API}/resources", params={"path": acc}, headers=headers)
        if r.status_code not in (201, 409):
            raise YandexDiskError(f"Не удалось создать папку {acc}: {_api_error(r)}")


async def _wait_ready(client: httpx.AsyncClient, path: str, token: str) -> None:
    """После 202 Accepted файл ещё не на Диске — подождать появления ресурса."""
    headers = _headers(token)
    for _ in range(12):
        r = await client.get(
            f"{_API}/resources",
            params={"path": path, "fields": "type,path"},
            headers=headers,
        )
        if r.status_code == 200:
            return
        await asyncio.sleep(0.5)


async def upload(remote_path: str, content: bytes, *, token: str) -> str:
    """Загрузить файл на Яндекс Диск и вернуть публичную ссылку.

    remote_path — абсолютный путь на Диске, напр. /chechlii/orders/5/design/mockup.png
    """
    directory = remote_path.rsplit("/", 1)[0]
    headers = _headers(token)
    async with httpx.AsyncClient(timeout=60) as client:
        await _ensure_dirs(client, directory, token)

        # 1) одноразовый URL загрузчика (живёт 30 минут).
        up = await client.get(
            f"{_API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
            headers=headers,
        )
        if up.status_code != 200:
            raise YandexDiskError(f"upload url: {_api_error(up)}")
        href = up.json().get("href")
        if not href:
            raise YandexDiskError("upload url: в ответе нет href")

        # 2) PUT файла на загрузчик — OAuth-заголовок не нужен.
        put = await client.put(href, content=content)
        if put.status_code not in (200, 201, 202):
            raise YandexDiskError(f"put file: {_api_error(put)}")
        if put.status_code == 202:
            await _wait_ready(client, remote_path, token)

        # 3) опубликовать и взять public_url (нужны disk.read + disk.write).
        pub = await client.put(
            f"{_API}/resources/publish", params={"path": remote_path}, headers=headers
        )
        if pub.status_code not in (200, 201, 202):
            raise YandexDiskError(f"publish: {_api_error(pub)}")

        public_url = None
        file_url = None
        for _ in range(6):
            meta = await client.get(
                f"{_API}/resources",
                params={"path": remote_path, "fields": "public_url,file"},
                headers=headers,
            )
            if meta.status_code == 200:
                data = meta.json() if meta.content else {}
                public_url = data.get("public_url")
                file_url = data.get("file")
                if public_url:
                    break
            await asyncio.sleep(0.4)
        return public_url or file_url or remote_path


_SAFE_EXT = {"png", "jpg", "jpeg", "webp", "gif", "pdf", "heic"}


def safe_filename(name: str, fallback: str = "file") -> str:
    """Имя для пути на Диске: без каталогов, запятых и пробелов (иначе API 400)."""
    raw = (name or fallback).replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem, dot, ext = raw.rpartition(".")
    ext = ext.lower() if dot else ""
    if ext not in _SAFE_EXT:
        stem = raw or fallback
        ext = "bin"
    cleaned = re.sub(r"[^\w.\-]+", "_", stem, flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._") or fallback
    return f"{cleaned[:80]}.{ext}"


_PUBLIC_HOSTS = (
    "yadi.sk",
    "disk.yandex.ru",
    "disk.yandex.com",
    "disk.yandex.net",
)


def is_public_url(url: str) -> bool:
    """Публичная страница/ключ Яндекс.Диска (не произвольный URL — защита от SSRF)."""
    raw = (url or "").strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        return False
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host in _PUBLIC_HOSTS or any(host.endswith(f".{h}") for h in _PUBLIC_HOSTS)


async def download_public(public_url: str) -> bytes:
    """Скачать опубликованный файл по public_url / yadi.sk без OAuth."""
    if not is_public_url(public_url):
        raise YandexDiskError("это не публичная ссылка Яндекс.Диска")
    async with httpx.AsyncClient(timeout=40.0, follow_redirects=True) as client:
        r = await client.get(
            f"{_API}/public/resources/download",
            params={"public_key": public_url},
        )
        if r.status_code >= 400:
            raise YandexDiskError(f"public download: {_api_error(r)}")
        href = (r.json() or {}).get("href") if r.content else None
        if not isinstance(href, str) or not href:
            raise YandexDiskError("public download: в ответе нет href")
        file = await client.get(href)
        if file.status_code >= 400 or not file.content:
            raise YandexDiskError(f"public download: файл недоступен ({file.status_code})")
        return file.content


def design_path(root: str, order_id: int, filename: str) -> str:
    return f"{root.rstrip('/')}/{order_id}/design/{safe_filename(filename, f'mockup_{order_id}')}"


def client_path(root: str, order_id: int, filename: str) -> str:
    return f"{root.rstrip('/')}/{order_id}/client/{safe_filename(filename, f'client_{order_id}')}"


def _space_hint(data: dict) -> str:
    used, total = data.get("used_space"), data.get("total_space")
    if not isinstance(used, int | float) or not isinstance(total, int | float) or total <= 0:
        return ""
    return f", занято {used / 1024**3:.1f} из {total / 1024**3:.0f} ГБ"


async def check_connection(*, token: str, root: str | None = None) -> tuple[bool, str]:
    """Статус связи с Диском: метаданные аккаунта + наличие корневой папки.

    Файлов и папок не создаёт — 404 на корне означает «токен принят, папка
    появится при первой загрузке», а не «нет связи».
    """
    try:
        headers = _headers(token)
    except YandexDiskError as e:
        return False, str(e)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(_API, headers=headers)
            login = "диск"
            extra = ""
            if r.status_code == 401:
                return False, _TOKEN_REJECTED
            if r.status_code == 403:
                # Без cloud_api:disk.info GET /v1/disk даёт 403, хотя запись работает.
                probe = await client.get(
                    f"{_API}/resources",
                    params={"path": "/", "fields": "type"},
                    headers=headers,
                )
                if probe.status_code in (401, 403):
                    return False, f"токен отклонён: {_api_error(r)}"
                if probe.status_code not in (200, 404):
                    return False, f"нет связи: {_api_error(r)}"
                extra = ". Нет права cloud_api:disk.info — добавьте его в OAuth-приложении"
            elif r.status_code != 200:
                return False, f"нет связи: {_api_error(r)}"
            else:
                data = r.json() if r.content else {}
                user = data.get("user") if isinstance(data, dict) else None
                if isinstance(user, dict):
                    login = str(user.get("display_name") or user.get("login") or login)
                extra = _space_hint(data) if isinstance(data, dict) else ""
            if root:
                folder = await client.get(
                    f"{_API}/resources",
                    params={"path": root, "fields": "type,path"},
                    headers=headers,
                )
                if folder.status_code == 404:
                    extra += f". Папка {root} ещё не создана — появится при первой загрузке"
                elif folder.status_code == 200:
                    extra += f". Папка {root} есть"
                elif folder.status_code in (401, 403):
                    extra += (
                        f". Папка {root}: нет прав на чтение "
                        "(нужны cloud_api:disk.read и cloud_api:disk.write)"
                    )
                else:
                    extra += f". Папка {root}: {_api_error(folder)[:80]}"
    except httpx.HTTPError as e:
        return False, f"нет связи: {e}"[:200]
    return True, f"связь есть, токен принят ({login}){extra}"
