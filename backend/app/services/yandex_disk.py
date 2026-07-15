"""Загрузка файлов на Яндекс Диск (REST API, OAuth 2.0).

Материалы клиента → /orders/{id}/client/, макеты дизайнера → /orders/{id}/design/.
Возвращает публичную ссылку на файл (для отправки клиенту и хранения в БД).
"""

from __future__ import annotations

import httpx

from app.core.config import settings

_API = "https://cloud-api.yandex.net/v1/disk"


class YandexDiskError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    token = settings.yandex_disk_oauth_token
    if not token:
        raise YandexDiskError("YANDEX_DISK_OAUTH_TOKEN не задан")
    return {"Authorization": f"OAuth {token}"}


async def _ensure_dirs(client: httpx.AsyncClient, path: str) -> None:
    """Создать вложенные папки по очереди (409 = уже есть — игнорируем)."""
    parts = [p for p in path.strip("/").split("/") if p]
    acc = ""
    for p in parts:
        acc += "/" + p
        r = await client.put(f"{_API}/resources", params={"path": acc}, headers=_headers())
        if r.status_code not in (201, 409):
            raise YandexDiskError(f"Не удалось создать папку {acc}: {r.status_code} {r.text[:200]}")


async def upload(remote_path: str, content: bytes) -> str:
    """Загрузить файл на Яндекс Диск и вернуть публичную ссылку.

    remote_path — абсолютный путь на Диске, напр. /chechlii/orders/5/design/mockup.png
    """
    directory = remote_path.rsplit("/", 1)[0]
    async with httpx.AsyncClient(timeout=60) as client:
        await _ensure_dirs(client, directory)

        # 1) получить одноразовый URL для загрузки
        up = await client.get(
            f"{_API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
            headers=_headers(),
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
            f"{_API}/resources/publish", params={"path": remote_path}, headers=_headers()
        )
        meta = await client.get(
            f"{_API}/resources",
            params={"path": remote_path, "fields": "public_url,file"},
            headers=_headers(),
        )
        data = meta.json()
        return data.get("public_url") or data.get("file") or remote_path


def design_path(order_id: int, filename: str) -> str:
    root = settings.yandex_disk_root.rstrip("/")
    return f"{root}/{order_id}/design/{filename}"


def client_path(order_id: int, filename: str) -> str:
    root = settings.yandex_disk_root.rstrip("/")
    return f"{root}/{order_id}/client/{filename}"
