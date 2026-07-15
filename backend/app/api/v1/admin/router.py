"""Агрегатор роутеров AdminUI. Разделы добавляются по фазам (см. docs/ADMIN_PANEL.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.auth import router as auth_router
from app.api.v1.admin.bot_messages import router as bot_messages_router
from app.api.v1.admin.catalog import router as catalog_router
from app.api.v1.admin.clients import router as clients_router
from app.api.v1.admin.orders import router as orders_router
from app.api.v1.admin.reviews import router as reviews_router

admin_router = APIRouter()
admin_router.include_router(auth_router, prefix="/auth", tags=["admin-auth"])
admin_router.include_router(catalog_router, prefix="/case-types", tags=["admin-catalog"])
admin_router.include_router(orders_router, prefix="/orders", tags=["admin-orders"])
admin_router.include_router(clients_router, prefix="/clients", tags=["admin-clients"])
admin_router.include_router(reviews_router, prefix="/reviews", tags=["admin-reviews"])
admin_router.include_router(bot_messages_router, prefix="/bot-messages", tags=["admin-bot-messages"])
