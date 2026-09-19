"""Точка входа FastAPI: health-check, Sentry, роутер v1."""

from __future__ import annotations

import os
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings

BRAND_DIR = Path(__file__).resolve().parent / "static" / "brand"
FAVICON_SVG = "/favicon.svg"


class SPAStaticFiles(StaticFiles):
    """StaticFiles с SPA-fallback: на 404 отдаёт index.html (для client-side роутинга)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, traces_sample_rate=0.1)

app = FastAPI(
    title="casetop API",
    version="0.1.0",
    description="Backend базового этапа: каталог, заказы, клиенты, оплата, доставка, webhooks.",
    docs_url=None,
    redoc_url=None,
)

app.include_router(api_router, prefix="/api/v1")


def _brand_file(name: str, media_type: str) -> FileResponse:
    return FileResponse(
        BRAND_DIR / name,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — docs",
        swagger_favicon_url=FAVICON_SVG,
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_ui() -> HTMLResponse:
    return get_redoc_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — docs",
        redoc_favicon_url=FAVICON_SVG,
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> FileResponse:
    return _brand_file("favicon.ico", "image/x-icon")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> FileResponse:
    return _brand_file("favicon.svg", "image/svg+xml")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    return _brand_file("apple-touch-icon.png", "image/png")


# Загруженные медиа (фото каталога) — на /media, до корневого SPA-маршрута.
# Папку создаём при старте: том монтируется на запись (не :ro, как webroot).
os.makedirs(settings.media_root, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

# Отдача собранных SPA с того же домена (после API-роутов, поэтому /api, /docs,
# /health имеют приоритет). Админка — на /admin (монтируется до корня), мини-
# приложение — на /. Более специфичный маршрут регистрируется первым.
if settings.webroot_admin and os.path.isdir(settings.webroot_admin):
    app.mount("/admin", SPAStaticFiles(directory=settings.webroot_admin, html=True), name="admin")

if settings.webroot and os.path.isdir(settings.webroot):
    app.mount("/", SPAStaticFiles(directory=settings.webroot, html=True), name="webapp")
