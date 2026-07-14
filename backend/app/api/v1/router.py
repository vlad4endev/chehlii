"""Агрегатор роутеров API v1.

Каталог — публичный. clients/orders/bot-messages используются ботом (единый backend
обслуживает все платформы). Оплата/доставка/админка добавляются в следующих спринтах.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.router import admin_router
from app.api.v1.bot_messages import router as bot_messages_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.clients import router as clients_router
from app.api.v1.orders import router as orders_router

api_router = APIRouter()
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(clients_router, prefix="/clients", tags=["clients"])
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
api_router.include_router(bot_messages_router, prefix="/bot-messages", tags=["bot-messages"])
api_router.include_router(admin_router, prefix="/admin")
