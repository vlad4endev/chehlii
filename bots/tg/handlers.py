"""Хендлеры Telegram-бота (Фаза 1: вход → заказ → имя/материалы).

Оплата, макет, доставка — следующие фазы (нужен выбор платёжного шлюза).
Вся бизнес-логика и данные — в едином backend; здесь только Telegram-адаптер.
"""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bots.core.backend import backend
from bots.core.texts import texts
from bots.tg.keyboards import (
    BTN_CATALOG,
    BTN_DELIVERIES,
    BTN_DISCOUNT,
    BTN_HELP,
    BTN_PAYMENTS,
    confirm_kb,
    contact_kb,
    main_menu_kb,
)
from bots.tg.states import OrderFlow

router = Router()
CHANNEL = "tg"


def _fmt_price(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


async def _client(msg: Message) -> dict:
    u = msg.from_user
    nickname = u.username or u.full_name if u else None
    return await backend.upsert_client(CHANNEL, str(u.id), nickname=nickname)


# ── Вход ───────────────────────────────────────────────
@router.message(CommandStart())
async def on_start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    client = await _client(msg)
    if client.get("phone"):
        await msg.answer(
            texts.get("welcome_back", discount=int(client.get("total_discount", 0))),
            reply_markup=main_menu_kb(),
        )
        return
    await msg.answer(texts.get("msg_001"))
    await msg.answer(texts.get("msg_002"), reply_markup=contact_kb())


@router.message(F.contact)
async def on_contact(msg: Message) -> None:
    u = msg.from_user
    await backend.upsert_client(
        CHANNEL, str(u.id), nickname=(u.username or u.full_name), phone=msg.contact.phone_number
    )
    await msg.answer(texts.get("msg_003"), reply_markup=main_menu_kb())


# ── Приём выбора из мини-приложения ────────────────────
@router.message(F.web_app_data)
async def on_web_app_data(msg: Message, state: FSMContext) -> None:
    try:
        data = json.loads(msg.web_app_data.data)
        case_id = int(data["case_id"])
        case_type = data["case_type"]  # standard | custom
        model = str(data["model"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        await msg.answer("Не удалось прочитать выбор. Откройте каталог и попробуйте снова.")
        return

    client = await _client(msg)
    order = await backend.create_order(client["id"], case_id, case_type, model)

    await state.set_state(OrderFlow.confirming)
    await state.update_data(order_id=order["id"], is_custom=order["is_custom"])
    await msg.answer(
        texts.get(
            "msg_005аб",
            type=order["case_name"],
            model=order["model_name"],
            price=_fmt_price(order["client_price"]),
        ),
        reply_markup=confirm_kb(),
    )


@router.callback_query(F.data == "order:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    is_custom = data.get("is_custom", False)
    await cb.message.edit_reply_markup(reply_markup=None)
    if is_custom:
        await state.set_state(OrderFlow.waiting_materials)
        await cb.message.answer(texts.get("msg_006б"))
    else:
        await state.set_state(OrderFlow.waiting_name)
        await cb.message.answer(texts.get("msg_006а"))
    await cb.answer()


@router.callback_query(F.data == "order:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Заказ отменён. Вы в главном меню.", reply_markup=main_menu_kb())
    await cb.answer()


# ── Главное меню ───────────────────────────────────────
@router.message(F.text == BTN_CATALOG)
async def on_catalog_fallback(msg: Message) -> None:
    # Срабатывает только если WebApp-URL не задан (иначе кнопка открывает мини-приложение).
    await msg.answer(
        "Каталог открывается в мини-приложении. Оно подключится после публикации фронтенда "
        "по HTTPS (задать WEBAPP_URL)."
    )


@router.message(F.text == BTN_DISCOUNT)
async def on_discount(msg: Message) -> None:
    c = await _client(msg)
    await msg.answer(
        f"Ваша скидка: {int(c.get('total_discount', 0))}%\n"
        f"Ваш промокод для друга: {c.get('slave_code') or '—'}\n\n"
        "Приглашайте друзей — за каждого начисляется скидка (задаёт администратор)."
    )


@router.message(F.text == BTN_PAYMENTS)
async def on_payments(msg: Message) -> None:
    await msg.answer("Раздел «Мои оплаты» появится после подключения платёжного шлюза.")


@router.message(F.text == BTN_DELIVERIES)
async def on_deliveries(msg: Message) -> None:
    await msg.answer("Раздел «Мои доставки» появится после подключения служб доставки.")


@router.message(F.text == BTN_HELP)
async def on_help(msg: Message) -> None:
    await msg.answer("Скоро поможем подобрать лучший вариант ✨ (в разработке).")


# ── Ввод имени / материалов ────────────────────────────
@router.message(OrderFlow.waiting_name, F.text)
async def on_name(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await backend.update_order(data["order_id"], custom_text=msg.text)
    await state.clear()
    await msg.answer(
        texts.get("msg_007а") + "\n\n(ссылка на оплату — после подключения шлюза)",
        reply_markup=main_menu_kb(),
    )


@router.message(OrderFlow.waiting_materials)
async def on_materials(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    # Файлы (фото/аудио/документы) пока фиксируем как file_id; загрузка на Яндекс Диск — далее.
    files: list[str] = []
    if msg.photo:
        files.append(msg.photo[-1].file_id)
    if msg.document:
        files.append(msg.document.file_id)
    if msg.voice:
        files.append(msg.voice.file_id)
    await backend.update_order(
        data["order_id"],
        materials_text=msg.caption or msg.text or "",
        materials_files=files,
    )
    await state.clear()
    await msg.answer(
        texts.get("msg_007б") + "\n\n(ссылка на оплату — после подключения шлюза)",
        reply_markup=main_menu_kb(),
    )


# Фолбэк: любое сообщение вне сценария → в меню.
@router.message(StateFilter(None), F.text)
async def on_fallback(msg: Message) -> None:
    await msg.answer("Выберите раздел в меню.", reply_markup=main_menu_kb())
