"""Агрегатор роутеров API v1.

Каталог — публичный. clients/orders/bot-messages используются ботом (единый backend
обслуживает все платформы). Оплата/доставка/админка добавляются в следующих спринтах.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.admin.router import admin_router
from app.api.v1.bot_messages import router as bot_messages_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.clients import router as clients_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.internal import require_internal
from app.api.v1.miniapp import router as miniapp_router
from app.api.v1.orders import router as orders_router
from app.api.v1.outbox import router as outbox_router
from app.api.v1.payments import router as payments_router
from app.api.v1.reviews import router as reviews_router

# Бот-только роутеры: требуют X-Internal-Token (см. internal.py).
_internal = [Depends(require_internal)]

api_router = APIRouter()
# Публичные (браузер-мини-приложение / лендинг читают): каталог, hero, отзывы.
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
api_router.include_router(miniapp_router, prefix="/miniapp", tags=["miniapp"])
# Внутренние (только боты). payments/delivery смешанные — защита на уровне эндпоинтов.
api_router.include_router(
    clients_router, prefix="/clients", tags=["clients"], dependencies=_internal
)
api_router.include_router(orders_router, prefix="/orders", tags=["orders"], dependencies=_internal)
api_router.include_router(outbox_router, prefix="/outbox", tags=["outbox"], dependencies=_internal)
api_router.include_router(
    bot_messages_router, prefix="/bot-messages", tags=["bot-messages"], dependencies=_internal
)
api_router.include_router(payments_router, prefix="/payments", tags=["payments"])
api_router.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
api_router.include_router(admin_router, prefix="/admin")
