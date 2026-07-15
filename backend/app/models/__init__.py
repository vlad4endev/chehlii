"""Единая точка импорта ORM-моделей (нужна Alembic для автогенерации)."""

from app.models.admin_user import AdminUser
from app.models.base import Base
from app.models.catalog import CaseType, CaseTypeModel
from app.models.client import Client
from app.models.engagement import Favorite, PromoActivation, Review
from app.models.messaging import BotMessage, Broadcast, OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.models.settings import IntegrationSetting

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
    "OutboundMessage",
    "Order",
    "OrderStatusHistory",
    "Payment",
    "IntegrationSetting",
]
