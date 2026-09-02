"""Загрузка файлов на Яндекс Диск (REST API, OAuth 2.0).

Материалы клиента → /orders/{id}/client/, макеты дизайнера → /orders/{id}/design/.
Возвращает публичную ссылку на файл (для отправки клиенту и хранения в БД).
Проба связи — GET /v1/disk (метаданные диска), папок и файлов не создаёт.
"""

from __future__ import annotations

import httpx

_API = "https://cloud-api.yandex.net/v1/disk"
_TIMEOUT = 15.0


class YandexDiskError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise YandexDiskError("токен Яндекс.Диска не задан")
    return {"Authorization": f"OAuth {token}"}


async def _ensure_dirs(client: httpx.AsyncClient, path: str, token: str) -> None:
    """Создать вложенные папки по очереди (409 = уже есть — игнорируем)."""
    parts = [p for p in path.strip("/").split("/") if p]
    acc = ""
    for p in parts:
        acc += "/" + p
        r = await client.put(f"{_API}/resources", params={"path": acc}, headers=_headers(token))
        if r.status_code not in (201, 409):
            raise YandexDiskError(f"Не удалось создать папку {acc}: {r.status_code} {r.text[:200]}")


async def upload(remote_path: str, content: bytes, *, token: str) -> str:
    """Загрузить файл на Яндекс Диск и вернуть публичную ссылку.

    remote_path — абсолютный путь на Диске, напр. /chechlii/orders/5/design/mockup.png
    """
    directory = remote_path.rsplit("/", 1)[0]
    async with httpx.AsyncClient(timeout=60) as client:
        await _ensure_dirs(client, directory, token)

        # 1) получить одноразовый URL для загрузки
        up = await client.get(
            f"{_API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
            headers=_headers(token),
        )
        if up.status_code != 200:
            raise YandexDiskError(f"upload url: {up.status_code} {up.text[:200]}")
        href = up.json()["href"]

        # 2) залить файл
        put = await client.put(href, content=content)
        if put.status_code not in (201, 202):
            raise YandexDiskError(f"put file: {put.status_code} {put.text[:200]}")

        # 3) опубликовать и получить публичную ссылку
        await client.put(
            f"{_API}/resources/publish", params={"path": remote_path}, headers=_headers(token)
        )
        meta = await client.get(
            f"{_API}/resources",
            params={"path": remote_path, "fields": "public_url,file"},
            headers=_headers(token),
        )
        data = meta.json()
        return data.get("public_url") or data.get("file") or remote_path


def design_path(root: str, order_id: int, filename: str) -> str:
    return f"{root.rstrip('/')}/{order_id}/design/{filename}"


def client_path(root: str, order_id: int, filename: str) -> str:
    return f"{root.rstrip('/')}/{order_id}/client/{filename}"


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
            if r.status_code in (401, 403):
                return False, f"токен отклонён: {r.text[:160]}"
            if r.status_code != 200:
                return False, f"нет связи: {r.status_code} {r.text[:160]}"
            data = r.json() if r.content else {}
            user = data.get("user") if isinstance(data, dict) else None
            login = "диск"
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
                else:
                    extra += f". Папка {root}: {folder.status_code} {folder.text[:80]}"
    except httpx.HTTPError as e:
        return False, f"нет связи: {e}"[:200]
    return True, f"связь есть, токен принят ({login}){extra}"
