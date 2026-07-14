"""Клавиатуры Telegram-бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bots.core.config import settings

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
