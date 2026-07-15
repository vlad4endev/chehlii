"""Клавиатуры MAX-бота. В MAX клавиатура — это inline-вложение сообщения
(reply-клавиатур, как в Telegram, нет). Каталог открывается кнопкой OpenApp."""

from __future__ import annotations

from maxapi.types import (
    CallbackButton,
    OpenAppButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

# Подписи кнопок меню.
BTN_CATALOG = "🛍 Каталог чехлов"
BTN_DISCOUNT = "🎁 Моя скидочная программа"
BTN_PAYMENTS = "💳 Мои оплаты"
BTN_DELIVERIES = "📦 Мои доставки"
BTN_HELP = "✨ Поможем выбрать"

# Payload'ы callback-кнопок (по ним же ловим нажатия).
CB_CATALOG = "menu:catalog"
CB_DISCOUNT = "menu:discount"
CB_PAYMENTS = "menu:payments"
CB_DELIVERIES = "menu:deliveries"
CB_HELP = "menu:help"
CB_CONFIRM = "order:confirm"
CB_CANCEL = "order:cancel"
CB_MAT_CONFIRM = "materials:confirm"
CB_MAT_REDO = "materials:redo"


def contact_kb():
    b = InlineKeyboardBuilder()
    b.row(RequestContactButton(text="📱 Поделиться контактом"))
    return b.as_markup()


def main_menu_kb(bot_username: str | None, bot_id: int | None):
    b = InlineKeyboardBuilder()
    # Каталог — мини-приложение (OpenApp привязан к боту). Если username неизвестен —
    # callback-заглушка с пояснением.
    if bot_username:
        b.row(OpenAppButton(text=BTN_CATALOG, web_app=bot_username, contact_id=bot_id))
    else:
        b.row(CallbackButton(text=BTN_CATALOG, payload=CB_CATALOG))
    b.row(CallbackButton(text=BTN_DISCOUNT, payload=CB_DISCOUNT))
    b.row(
        CallbackButton(text=BTN_PAYMENTS, payload=CB_PAYMENTS),
        CallbackButton(text=BTN_DELIVERIES, payload=CB_DELIVERIES),
    )
    b.row(CallbackButton(text=BTN_HELP, payload=CB_HELP))
    return b.as_markup()


def confirm_kb():
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Подтвердить", payload=CB_CONFIRM),
        CallbackButton(text="↩️ Назад", payload=CB_CANCEL),
    )
    return b.as_markup()


def materials_confirm_kb():
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Подтвердить", payload=CB_MAT_CONFIRM),
        CallbackButton(text="🔄 Прислать заново", payload=CB_MAT_REDO),
    )
    return b.as_markup()


def mockup_kb(order_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Подтвердить", payload=f"mockup:approve:{order_id}"),
        CallbackButton(text="🔄 Переделать", payload=f"mockup:redo:{order_id}"),
    )
    return b.as_markup()
