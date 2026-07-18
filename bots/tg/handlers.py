"""Хендлеры Telegram-бота (Фаза 1: вход → заказ → имя/материалы).

Оплата, макет, доставка — следующие фазы (нужен выбор платёжного шлюза).
Вся бизнес-логика и данные — в едином backend; здесь только Telegram-адаптер.
"""

from __future__ import annotations

import json
import logging

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
    materials_confirm_kb,
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
    # Контакт на входе НЕ просим — чтобы не отпугивать. Пользователь свободно
    # смотрит каталог; телефон запросим только при оформлении заказа.
    await state.clear()
    client = await _client(msg)
    code = "welcome_back" if client.get("phone") else "msg_001"
    greeting = (
        texts.get("welcome_back", discount=int(client.get("total_discount", 0)))
        if client.get("phone")
        else texts.get("msg_001")
    )
    await msg.answer(greeting, reply_markup=main_menu_kb())
    await backend.mark_journey(client["id"], code)


@router.message(F.contact)
async def on_contact(msg: Message, state: FSMContext) -> None:
    u = msg.from_user
    client = await backend.upsert_client(
        CHANNEL, str(u.id), nickname=(u.username or u.full_name), phone=msg.contact.phone_number
    )
    # Если контакт запрошен в момент заказа — продолжаем оформление сразу.
    data = await state.get_data()
    if data.get("pending_case_id") is not None:
        await _begin_order(
            msg,
            state,
            client["id"],
            int(data["pending_case_id"]),
            data["pending_case_type"],
            data["pending_model"],
        )
        return
    await msg.answer(texts.get("msg_003"), reply_markup=main_menu_kb())
    await backend.mark_journey(client["id"], "msg_003")


# ── Приём выбора из мини-приложения ────────────────────
async def _begin_order(
    msg: Message, state: FSMContext, client_id: int, case_id: int, case_type: str, model: str
) -> None:
    """Создать заказ и показать подтверждение (тип+модель+цена)."""
    order = await backend.create_order(client_id, case_id, case_type, model)
    await state.set_state(OrderFlow.confirming)
    await state.update_data(
        order_id=order["id"],
        is_custom=order["is_custom"],
        pending_case_id=None,
        pending_case_type=None,
        pending_model=None,
    )
    await msg.answer(
        texts.get(
            "msg_005аб",
            type=order["case_name"],
            model=order["model_name"],
            price=_fmt_price(order["client_price"]),
        ),
        reply_markup=confirm_kb(),
    )
    await backend.mark_journey(client_id, "msg_005аб")


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
    # Контакт просим именно здесь — на моменте заказа. Нет телефона → запоминаем
    # выбор и просим поделиться контактом; заказ оформим сразу после этого.
    if not client.get("phone"):
        await state.set_state(OrderFlow.waiting_contact)
        await state.update_data(
            pending_case_id=case_id, pending_case_type=case_type, pending_model=model
        )
        await msg.answer(
            "Отличный выбор! 🎉\n\n" + texts.get("msg_002"),
            reply_markup=contact_kb(),
        )
        await backend.mark_journey(client["id"], "msg_002")
        return

    await _begin_order(msg, state, client["id"], case_id, case_type, model)


@router.message(OrderFlow.waiting_contact)
async def on_waiting_contact_other(msg: Message) -> None:
    # В ожидании контакта пришло не «поделиться контактом» — напоминаем про кнопку.
    await msg.answer(
        "Чтобы оформить заказ, нажмите кнопку «📱 Поделиться контактом» ниже.",
        reply_markup=contact_kb(),
    )


@router.callback_query(F.data == "order:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    is_custom = data.get("is_custom", False)
    await cb.message.edit_reply_markup(reply_markup=None)
    if is_custom:
        await state.set_state(OrderFlow.waiting_materials)
        await cb.message.answer(texts.get("msg_006б"))
        code = "msg_006б"
    else:
        await state.set_state(OrderFlow.waiting_name)
        await cb.message.answer(texts.get("msg_006а"))
        code = "msg_006а"
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    await backend.mark_journey(client["id"], code)
    await cb.answer()


@router.callback_query(F.data == "order:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Заказ отменён. Вы в главном меню.", reply_markup=main_menu_kb())
    await cb.answer()


# ── Ответ клиента на макет («Подтвердить» / «Переделать») ──
@router.callback_query(F.data.startswith("mockup:"))
async def on_mockup_response(cb: CallbackQuery) -> None:
    try:
        _, action, oid = cb.data.split(":")
        order_id = int(oid)
    except (ValueError, AttributeError):
        await cb.answer()
        return
    approved = action == "approve"
    try:
        await backend.mockup_response(order_id, approved)
    except Exception:
        await cb.answer("Не получилось сохранить, попробуйте ещё раз", show_alert=True)
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "Спасибо! Макет согласован — переходим к оплате."
        if approved
        else "Принято! Дизайнер доработает макет и пришлёт заново."
    )
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


async def _pay_line(order_id: int) -> str:
    """Ссылка на предоплату (Robokassa) для сообщения клиенту; фолбэк если не настроено."""
    try:
        p = await backend.payment_link(order_id, "prepayment")
        return f"\n\n💳 Внести предоплату {int(p['amount'])} ₽:\n{p['url']}"
    except Exception:
        return " Ссылка на оплату придёт следующим сообщением."


# ── Ввод имени / материалов ────────────────────────────
@router.message(OrderFlow.waiting_name, F.text)
async def on_name(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=msg.text)
    await state.clear()
    await msg.answer(
        texts.get("msg_007а") + await _pay_line(order_id),
        reply_markup=main_menu_kb(),
    )
    u = msg.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    await backend.mark_journey(client["id"], "msg_007а")


@router.message(OrderFlow.waiting_materials)
async def on_materials(msg: Message, state: FSMContext) -> None:
    # Фиксируем file_id + имя; на подтверждении скачаем и зальём на Яндекс Диск.
    files: list[dict] = []
    if msg.photo:
        files.append({"id": msg.photo[-1].file_id, "name": "photo.jpg"})
    if msg.document:
        files.append({"id": msg.document.file_id, "name": msg.document.file_name or "file"})
    if msg.voice:
        files.append({"id": msg.voice.file_id, "name": "voice.ogg"})
    text = msg.caption or msg.text or ""
    if not text and not files:
        await msg.answer("Пришлите фото/файлы и/или опишите пожелание.")
        return
    # Не финализируем сразу — показываем сводку и ждём подтверждения (клиент
    # может передумать/переслать заново).
    await state.update_data(materials_text=text, materials_files=files)
    await state.set_state(OrderFlow.confirming_materials)
    await msg.answer(
        "Проверьте кастом-чехол:\n\n"
        f"📝 Описание: {text or '—'}\n"
        f"📎 Вложений: {len(files)}\n\n"
        "Всё верно? Нажмите «Подтвердить» — и чехол уйдёт в работу.",
        reply_markup=materials_confirm_kb(),
    )


async def _persist_files(bot, order_id: int, files: list[dict]) -> list[str]:
    """Скачать файлы из Telegram и загрузить на Яндекс Диск через backend.
    Возвращает публичные ссылки (для materials_files)."""
    links: list[str] = []
    for i, f in enumerate(files):
        fid = f.get("id") if isinstance(f, dict) else f
        name = f.get("name", f"file_{i + 1}") if isinstance(f, dict) else f"file_{i + 1}"
        try:
            buf = await bot.download(fid)
            res = await backend.add_client_file(order_id, name, buf.read())
            links.append(res["url"])
        except Exception as e:  # noqa: BLE001
            logging.warning("client file upload failed: %s", e)
    return links


@router.callback_query(OrderFlow.confirming_materials, F.data == "materials:confirm")
async def on_materials_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
    links = await _persist_files(cb.bot, order_id, data.get("materials_files", []))
    await backend.update_order(
        order_id,
        materials_text=data.get("materials_text", ""),
        materials_files=links,
    )
    await state.clear()
    await cb.message.answer(
        texts.get("msg_007б") + await _pay_line(order_id),
        reply_markup=main_menu_kb(),
    )
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    await backend.mark_journey(client["id"], "msg_007б")


@router.callback_query(OrderFlow.confirming_materials, F.data == "materials:redo")
async def on_materials_redo(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderFlow.waiting_materials)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.get("msg_006б"))
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    await backend.mark_journey(client["id"], "msg_006б")
    await cb.answer()


# Фолбэк: любое сообщение вне сценария → в меню.
@router.message(StateFilter(None), F.text)
async def on_fallback(msg: Message) -> None:
    await msg.answer("Выберите раздел в меню.", reply_markup=main_menu_kb())
