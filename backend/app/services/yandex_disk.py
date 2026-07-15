"""Загрузка файлов на Яндекс Диск (REST API, OAuth 2.0).

Материалы клиента → /orders/{id}/client/, макеты дизайнера → /orders/{id}/design/.
Возвращает публичную ссылку на файл (для отправки клиенту и хранения в БД).
"""

from __future__ import annotations

import httpx

_API = "https://cloud-api.yandex.net/v1/disk"


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
