"""Точка входа FastAPI: health-check, Sentry, роутер v1."""

from __future__ import annotations

import os

import sentry_sdk
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings


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
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


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
