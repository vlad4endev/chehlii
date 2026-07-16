"""Агрегатор роутеров AdminUI. Разделы добавляются по фазам (см. docs/ADMIN_PANEL.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.auth import router as auth_router
from app.api.v1.admin.bot_messages import router as bot_messages_router
from app.api.v1.admin.broadcasts import router as broadcasts_router
from app.api.v1.admin.catalog import router as catalog_router
from app.api.v1.admin.integrations import router as integrations_router
from app.api.v1.admin.journeys import router as journeys_router
from app.api.v1.admin.media import router as media_router
from app.api.v1.admin.miniapp import router as miniapp_router
from app.api.v1.admin.clients import router as clients_router
from app.api.v1.admin.orders import router as orders_router
from app.api.v1.admin.reviews import router as reviews_router
from app.api.v1.admin.stats import router as stats_router
from app.api.v1.admin.trash import router as trash_router
from app.api.v1.admin.users import router as users_router

admin_router = APIRouter()
admin_router.include_router(auth_router, prefix="/auth", tags=["admin-auth"])
admin_router.include_router(stats_router, prefix="/stats", tags=["admin-stats"])
admin_router.include_router(catalog_router, prefix="/case-types", tags=["admin-catalog"])
admin_router.include_router(orders_router, prefix="/orders", tags=["admin-orders"])
admin_router.include_router(clients_router, prefix="/clients", tags=["admin-clients"])
admin_router.include_router(reviews_router, prefix="/reviews", tags=["admin-reviews"])
admin_router.include_router(
    bot_messages_router, prefix="/bot-messages", tags=["admin-bot-messages"]
)
admin_router.include_router(broadcasts_router, prefix="/broadcasts", tags=["admin-broadcasts"])
admin_router.include_router(users_router, prefix="/users", tags=["admin-users"])
admin_router.include_router(integrations_router, prefix="/integrations", tags=["admin-integrations"])
admin_router.include_router(media_router, prefix="/media", tags=["admin-media"])
admin_router.include_router(miniapp_router, prefix="/miniapp", tags=["admin-miniapp"])
admin_router.include_router(trash_router, prefix="/trash", tags=["admin-trash"])
admin_router.include_router(journeys_router, prefix="/journeys", tags=["admin-journeys"])
