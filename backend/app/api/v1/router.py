"""Агрегатор роутеров API v1.

В Спринте 0 подключён только каталог (чтение) как проверка сквозного пути
FastAPI → БД. Остальные роутеры (orders, clients, reviews, favorites, promo,
admin, payments/webhooks, delivery/webhooks) добавляются в спринтах 1–6.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.catalog import router as catalog_router

api_router = APIRouter()
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
