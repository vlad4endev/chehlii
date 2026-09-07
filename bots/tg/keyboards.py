"""Клавиатуры Telegram-бота."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bots.core.config import settings
from bots.core.payments import PayButton

# Тексты кнопок главного меню (по ним же ловим нажатия).
BTN_CATALOG = "🛍 Каталог чехлов"
BTN_HELP = "✨ Поможем выбрать"
BTN_DISCOUNT = "🎁 Моя скидочная программа"
BTN_PAYMENTS = "💳 Мои оплаты"
BTN_DELIVERIES = "📦 Мои доставки"


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_kb() -> ReplyKeyboardMarkup:
    # Каталог — WebApp-кнопка (только по HTTPS). Иначе обычная кнопка + пояснение.
    https = settings.webapp_url and settings.webapp_url.startswith("https://")
    catalog_btn = (
        KeyboardButton(text=BTN_CATALOG, web_app=WebAppInfo(url=settings.webapp_url))
        if https
        else KeyboardButton(text=BTN_CATALOG)
    )
    return ReplyKeyboardMarkup(
        keyboard=[
            [catalog_btn],
            [KeyboardButton(text=BTN_DISCOUNT)],
            [KeyboardButton(text=BTN_PAYMENTS), KeyboardButton(text=BTN_DELIVERIES)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="order:confirm"),
                InlineKeyboardButton(text="↩️ Назад", callback_data="order:cancel"),
            ]
        ]
    )


def pay_kb(buttons: Sequence[PayButton]) -> InlineKeyboardMarkup:
    """Кнопки оплаты — по одной на шлюз, каждая своей строкой. Ссылка живёт в кнопке,
    а не в тексте: иначе Telegram подтягивает превью страницы шлюза и сообщение
    выглядит мусорно."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=b.label, url=b.url)] for b in buttons]
    )


def mockup_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"mockup:approve:{order_id}"),
                InlineKeyboardButton(text="🔄 Переделать", callback_data=f"mockup:redo:{order_id}"),
            ]
        ]
    )


def materials_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="materials:confirm"),
                InlineKeyboardButton(text="🔄 Прислать заново", callback_data="materials:redo"),
            ]
        ]
    )


def delivery_service_kb(order_id: int, services: list[str]) -> InlineKeyboardMarkup:
    labels = {"cdek": "СДЭК", "yandex": "Яндекс Доставка"}
    rows = [
        [
            InlineKeyboardButton(
                text=labels.get(s, s),
                callback_data=f"dlv:svc:{order_id}:{s}",
            )
        ]
        for s in services
        if s in labels
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_mode_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Пункт выдачи",
                    callback_data=f"dlv:pvz:{order_id}",
                ),
                InlineKeyboardButton(
                    text="🚚 Курьер до двери",
                    callback_data=f"dlv:door:{order_id}",
                ),
            ]
        ]
    )


def delivery_points_kb(order_id: int, points: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=str(i + 1), callback_data=f"dlv:n:{order_id}:{i}")]
        for i in range(len(points))
    ]
    rows.append(
        [
            InlineKeyboardButton(text="🚚 Курьер до двери", callback_data=f"dlv:door:{order_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_start_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Оформить доставку", callback_data=f"dlv:go:{order_id}")]
        ]
    )


def delivery_orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"#{o['id']} оформить доставку",
                    callback_data=f"dlv:go:{o['id']}",
                )
            ]
            for o in orders[:5]
        ]
    )
