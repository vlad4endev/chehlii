"""Скачать вложение outbox: локальное /media или публичный файл Яндекс.Диска."""

from __future__ import annotations

import httpx

from bots.core.config import settings

_YADISK_DOWNLOAD = "https://cloud-api.yandex.net/v1/disk/public/resources/download"


def looks_like_image(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def looks_like_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def _absolute(path_or_url: str) -> str:
    if path_or_url.startswith("http"):
        return path_or_url
    origin = settings.backend_url.split("/api/")[0]
    return f"{origin}{path_or_url}"


def _is_disk_page(url: str, content_type: str, body: bytes) -> bool:
    host = url.lower()
    if "yadi.sk" in host or "disk.yandex." in host:
        return True
    ct = (content_type or "").lower()
    if "text/html" in ct:
        return True
    head = body[:32].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


async def _yadisk_public_bytes(client: httpx.AsyncClient, public_url: str) -> bytes | None:
    r = await client.get(_YADISK_DOWNLOAD, params={"public_key": public_url})
    if r.status_code >= 400:
        return None
    href = (r.json() or {}).get("href")
    if not href:
        return None
    file = await client.get(href)
    if file.status_code >= 400 or not file.content:
        return None
    return file.content


async def fetch_bytes(path_or_url: str) -> bytes | None:
    """Байты файла. Страницу yadi.sk разворачиваем в сам файл."""
    if not (path_or_url or "").strip():
        return None
    url = _absolute(path_or_url.strip())
    try:
        async with httpx.AsyncClient(timeout=40.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code < 400 and r.content and not _is_disk_page(str(r.url), r.headers.get("content-type", ""), r.content):
                return r.content
            if _is_disk_page(url, r.headers.get("content-type", ""), r.content or b""):
                return await _yadisk_public_bytes(client, url)
    except Exception:  # noqa: BLE001
        return None
    return None


if __name__ == "__main__":
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert looks_like_image(png)
    assert looks_like_image(b"\xff\xd8\xff" + b"\x00" * 12)
    assert not looks_like_image(b"%PDF-1.4")
    assert looks_like_pdf(b"%PDF-1.7 rest")
    print("ok")
