"""Точка входа FastAPI: health-check, Sentry, роутер v1."""

from __future__ import annotations

import sentry_sdk
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, traces_sample_rate=0.1)

app = FastAPI(
    title="ЧехлИИ API",
    version="0.1.0",
    description="Backend базового этапа: каталог, заказы, клиенты, оплата, доставка, webhooks.",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
