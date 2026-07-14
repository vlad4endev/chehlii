"""Единая точка импорта ORM-моделей (нужна Alembic для автогенерации)."""

from app.models.admin_user import AdminUser
from app.models.base import Base
from app.models.catalog import CaseType, CaseTypeModel
from app.models.client import Client
from app.models.engagement import Favorite, PromoActivation, Review
from app.models.messaging import BotMessage, Broadcast
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment

__all__ = [
    "Base",
    "AdminUser",
    "CaseType",
    "CaseTypeModel",
    "Client",
    "Favorite",
    "PromoActivation",
    "Review",
    "Broadcast",
    "BotMessage",
    "Order",
    "OrderStatusHistory",
    "Payment",
]
