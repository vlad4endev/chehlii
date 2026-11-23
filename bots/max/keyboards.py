"""Клавиатуры MAX-бота. В MAX клавиатура — это inline-вложение сообщения
(reply-клавиатур, как в Telegram, нет). Каталог открывается кнопкой OpenApp."""

from __future__ import annotations

from collections.abc import Sequence

from maxapi.types import (
    CallbackButton,
    LinkButton,
    OpenAppButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bots.core.payments import PayButton

# Подписи кнопок меню.
BTN_CATALOG = "🛍 Каталог чехлов"
BTN_DISCOUNT = "🎁 Моя скидочная программа"
BTN_PAYMENTS = "💳 Мои оплаты"
BTN_DELIVERIES = "📦 Мои доставки"
BTN_HELP = "🙋 Позвать человека"
CB_HUMAN = "menu:human"  # alias; CB_HELP остаётся для совместимости

# Payload'ы callback-кнопок (по ним же ловим нажатия).
CB_CATALOG = "menu:catalog"
CB_DISCOUNT = "menu:discount"
CB_PAYMENTS = "menu:payments"
CB_DELIVERIES = "menu:deliveries"
CB_HELP = "menu:help"
CB_CONFIRM = "order:confirm"
CB_PHONE_OK = "phone:ok"
CB_PHONE_RETRY = "phone:retry"
CB_PHONE_MANUAL = "phone:manual"
CB_CANCEL = "order:cancel"
CB_MAT_CONFIRM = "materials:confirm"
CB_MAT_REDO = "materials:redo"
CB_MAT_FILES_DONE = "materials:files_done"
CB_MAT_SKIP_DESC = "materials:skip_desc"
CB_MAT_EDIT_FILES = "materials:edit_files"
CB_MAT_EDIT_DESC = "materials:edit_desc"


def _help_row():
    return CallbackButton(text=BTN_HELP, payload=CB_HELP)


def contact_kb():
    """Запрос телефона. Номер аккаунта бывает не тем, на который заказывают, —
    поэтому рядом кнопка ввода другого номера вручную."""
    b = InlineKeyboardBuilder()
    b.row(RequestContactButton(text="📱 Поделиться контактом"))
    b.row(CallbackButton(text="✏️ Ввести другой номер", payload=CB_PHONE_MANUAL))
    b.row(_help_row())
    return b.as_markup()


def phone_confirm_kb():
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Да, верно", payload=CB_PHONE_OK),
        CallbackButton(text="✏️ Ввести заново", payload=CB_PHONE_RETRY),
    )
    return b.as_markup()


def main_menu_kb(bot_username: str | None, bot_id: int | None):
    b = InlineKeyboardBuilder()
    # Каталог — мини-приложение (OpenApp). Username: MAX_BOT_USERNAME или bot.me.
    # Без username — callback с той же подсказкой, что и у Telegram без WEBAPP_URL.
    if bot_username:
        b.row(
            OpenAppButton(
                text=BTN_CATALOG,
                web_app=f"https://max.ru/{bot_username}",
                contact_id=bot_id,
            )
        )
    else:
        b.row(CallbackButton(text=BTN_CATALOG, payload=CB_CATALOG))
    b.row(CallbackButton(text=BTN_DISCOUNT, payload=CB_DISCOUNT))
    b.row(
        CallbackButton(text=BTN_PAYMENTS, payload=CB_PAYMENTS),
        CallbackButton(text=BTN_DELIVERIES, payload=CB_DELIVERIES),
    )
    b.row(_help_row())
    return b.as_markup()


def confirm_kb():
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Подтвердить", payload=CB_CONFIRM),
        CallbackButton(text="↩️ Назад", payload=CB_CANCEL),
    )
    b.row(_help_row())
    return b.as_markup()


def materials_files_done_kb():
    b = InlineKeyboardBuilder()
    b.row(CallbackButton(text="✅ Готово, дальше", payload=CB_MAT_FILES_DONE))
    b.row(_help_row())
    return b.as_markup()


def materials_skip_desc_kb():
    b = InlineKeyboardBuilder()
    b.row(CallbackButton(text="Без описания", payload=CB_MAT_SKIP_DESC))
    b.row(_help_row())
    return b.as_markup()


def materials_confirm_kb():
    b = InlineKeyboardBuilder()
    b.row(CallbackButton(text="✅ Подтвердить", payload=CB_MAT_CONFIRM))
    b.row(
        CallbackButton(text="🖼 Изменить фото", payload=CB_MAT_EDIT_FILES),
        CallbackButton(text="✏️ Изменить описание", payload=CB_MAT_EDIT_DESC),
    )
    b.row(
        CallbackButton(text="🔄 Прислать заново", payload=CB_MAT_REDO),
        _help_row(),
    )
    return b.as_markup()


def pick_order_kb(order_ids: list[int]):
    b = InlineKeyboardBuilder()
    for oid in order_ids[:8]:
        b.row(CallbackButton(text=f"Заказ #{oid}", payload=f"order:pick:{oid}"))
    return b.as_markup()


def pay_kb(buttons: Sequence[PayButton]):
    """Кнопки оплаты — по одной на шлюз. Ссылка в кнопке, а не в тексте (иначе
    мессенджер рисует превью страницы шлюза)."""
    b = InlineKeyboardBuilder()
    for btn in buttons:
        b.row(LinkButton(text=btn.label, url=btn.url))
    b.row(_help_row())
    return b.as_markup()


def mockup_kb(order_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        CallbackButton(text="✅ Подтвердить", payload=f"mockup:approve:{order_id}"),
        CallbackButton(text="🔄 Переделать", payload=f"mockup:redo:{order_id}"),
    )
    b.row(_help_row())
    return b.as_markup()


def delivery_service_kb(order_id: int, services: list):
    labels = {"cdek": "СДЭК", "yandex": "Яндекс Доставка", "ozon": "Ozon Доставка"}
    b = InlineKeyboardBuilder()
    for s in services:
        if s in labels:
            b.row(CallbackButton(text=labels[s], payload=f"dlv:svc:{order_id}:{s}"))
    b.row(_help_row())
    return b.as_markup()


def delivery_mode_kb(order_id: int, service: str | None = None):
    b = InlineKeyboardBuilder()
    if service == "ozon":
        b.row(CallbackButton(text="📦 Пункт выдачи", payload=f"dlv:pvz:{order_id}"))
    else:
        b.row(
            CallbackButton(text="📦 Пункт выдачи", payload=f"dlv:pvz:{order_id}"),
            CallbackButton(text="🚚 Курьер до двери", payload=f"dlv:door:{order_id}"),
        )
    b.row(_help_row())
    return b.as_markup()


def delivery_points_kb(order_id: int, points: list, service: str | None = None):
    b = InlineKeyboardBuilder()
    row = []
    for i in range(len(points)):
        row.append(CallbackButton(text=str(i + 1), payload=f"dlv:n:{order_id}:{i}"))
        if len(row) == 4:
            b.row(*row)
            row = []
    if row:
        b.row(*row)
    if service != "ozon":
        b.row(CallbackButton(text="🚚 Курьер до двери", payload=f"dlv:door:{order_id}"))
    b.row(_help_row())
    return b.as_markup()


def delivery_start_kb(order_id: int):
    b = InlineKeyboardBuilder()
    b.row(CallbackButton(text="📦 Оформить доставку", payload=f"dlv:go:{order_id}"))
    b.row(_help_row())
    return b.as_markup()


def delivery_orders_kb(orders: list):
    b = InlineKeyboardBuilder()
    for o in orders[:5]:
        b.row(CallbackButton(text=f"#{o['id']} оформить доставку", payload=f"dlv:go:{o['id']}"))
    b.row(_help_row())
    return b.as_markup()
