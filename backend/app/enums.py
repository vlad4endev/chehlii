"""Перечисления домена casetop. Значения — стабильные строковые коды (хранятся в БД)."""

from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Канал клиента. ТГ и МАКС — независимые пространства клиентов (не объединяются)."""

    TG = "tg"
    MAX = "max"


class CaseBranch(StrEnum):
    """Ветка сценария по типу чехла."""

    STANDARD = "standard"  # Стандарт — клиент вводит имя/букву
    CUSTOM = "custom"  # Кастом — клиент присылает материалы, дизайнер делает макет


class AdminRole(StrEnum):
    """Роли AdminUI. Дизайнер и менеджер доставок — одна роль (ТЗ v2.0)."""

    ADMIN = "admin"
    DESIGNER = "designer"


class OrderStatus(StrEnum):
    """Статусы заказа (модель статусов ТЗ v2.0). Порядок — типовой путь заказа."""

    CASE_TYPE_SELECTED = "case_type_selected"  # Выбран тип чехла
    MODEL_SELECTED = "model_selected"  # Выбрана модель iPhone
    CASE_CONFIRMED = "case_confirmed"  # Согласован чехол
    MATERIALS_SUBMITTED = "materials_submitted"  # Отправка материала для дизайнера
    PREPAYMENT_ISSUED = "prepayment_issued"  # Предоплата выставлена
    PREPAYMENT_PAID = "prepayment_paid"  # Предоплата прошла
    HANDED_TO_DESIGN = "handed_to_design"  # Передан в дизайн
    DESIGN_IN_PROGRESS = "design_in_progress"  # Дизайн в процессе
    MOCKUP_SENT = "mockup_sent"  # Отправка макета
    MOCKUP_APPROVAL = "mockup_approval"  # Согласование макета
    MOCKUP_REVISION = "mockup_revision"  # Пересогласование макета
    POSTPAYMENT_ISSUED = "postpayment_issued"  # Постоплата выставлена
    POSTPAYMENT_PAID = "postpayment_paid"  # Постоплата прошла
    CANCELLED = "cancelled"  # Отменён
    DELIVERY_SERVICE_SELECTION = "delivery_service_selection"  # Выбор службы доставки
    DELIVERY_ADDRESS_SELECTION = "delivery_address_selection"  # Выбор адреса
    DELIVERY_PAYMENT = "delivery_payment"  # Оплата доставки
    SHIPPED = "shipped"  # Заказ отправлен
    DELIVERED = "delivered"  # Заказ получен
    REVIEW_OFFERED = "review_offered"  # Предложение об отзыве
    REVIEW_RECEIVED = "review_received"  # Отзыв получен


class PaymentKind(StrEnum):
    PREPAYMENT = "prepayment"
    POSTPAYMENT = "postpayment"
    DELIVERY = "delivery"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryService(StrEnum):
    OZON = "ozon"
    YANDEX = "yandex"
    CDEK = "cdek"


class ReviewStatus(StrEnum):
    """Отзывы проходят модерацию перед публикацией."""

    PENDING = "pending"  # На модерации
    PUBLISHED = "published"  # Опубликован
    REJECTED = "rejected"  # Отклонён


class BotMessageMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class ScenarioType(StrEnum):
    """Тип сценария сообщения. Задел под этап 2 (триггерные сценарии)."""

    BASE = "base"  # Базовый линейный сценарий (этап 1)
    TRIGGERED = "triggered"  # Триггерные рассылки (этап 2 — не реализуется)
