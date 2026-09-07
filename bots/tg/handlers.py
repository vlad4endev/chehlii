"""Хендлеры Telegram-бота: заказ, оплата, оформление доставки.

Вся бизнес-логика и данные — в едином backend; здесь только Telegram-адаптер.
"""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bots.core import delivery, payments
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
    delivery_mode_kb,
    delivery_orders_kb,
    delivery_points_kb,
    delivery_service_kb,
    delivery_start_kb,
    main_menu_kb,
    materials_confirm_kb,
    pay_kb,
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
    pending_delivery = data.get("pending_delivery_order_id")
    if pending_delivery is not None:
        await _start_delivery(msg, state, int(pending_delivery))
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
    if approved:
        await cb.message.answer("Спасибо! Макет согласован — переходим к оплате.")
        b = await payments.block(order_id, "postpayment")
        await cb.message.answer(b.text, reply_markup=pay_kb(b.buttons) if b.buttons else None)
    else:
        await cb.message.answer("Принято! Дизайнер доработает макет и пришлёт заново.")
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
async def on_deliveries(msg: Message, state: FSMContext) -> None:
    client = await _client(msg)
    try:
        orders = await backend.client_orders(client["id"])
    except Exception:  # noqa: BLE001
        orders = []
    await msg.answer(delivery.orders_text(orders), reply_markup=main_menu_kb())
    pending = [
        o
        for o in orders
        if o.get("status") in delivery.NEEDS_CHECKOUT and not o.get("tracking_code")
    ]
    if len(pending) == 1:
        await msg.answer(
            "Нажмите, чтобы оформить доставку.",
            reply_markup=delivery_start_kb(pending[0]["id"]),
        )
    elif pending:
        await msg.answer("Выберите заказ:", reply_markup=delivery_orders_kb(pending))


@router.message(F.text == BTN_HELP)
async def on_help(msg: Message) -> None:
    await msg.answer("Скоро поможем подобрать лучший вариант ✨ (в разработке).")


async def _send_pay(message: Message, order_id: int, code: str) -> None:
    """«Заказ принят» + отдельная карточка оплаты с кнопкой.

    Двумя сообщениями: reply-меню и inline-кнопку Telegram в одном не отдаёт.
    """
    await message.answer(texts.get(code), reply_markup=main_menu_kb())
    b = await payments.block(order_id)
    await message.answer(b.text, reply_markup=pay_kb(b.buttons) if b.buttons else None)


async def _send_delivery_pay(message: Message, order_id: int, quote: dict) -> None:
    await message.answer(delivery.quote_text(quote), reply_markup=main_menu_kb())
    if (quote.get("delivery_sum") or 0) <= 0:
        try:
            await backend.delivery_fulfill(order_id)
            await message.answer("Доставка бесплатная — заявку создаём сейчас.")
        except Exception as e:  # noqa: BLE001
            await message.answer(delivery.api_error(e))
        return
    b = await payments.block(order_id, "delivery")
    await message.answer(b.text, reply_markup=pay_kb(b.buttons) if b.buttons else None)


async def _start_delivery(message: Message, state: FSMContext, order_id: int) -> None:
    services = await delivery.configured_services()
    await state.update_data(
        order_id=order_id,
        delivery_mode=None,
        delivery_city=None,
        delivery_points=[],
        delivery_service=services[0] if len(services) == 1 else None,
    )
    if not services:
        await message.answer("Доставка ещё не настроена. Напишите нам — отправим вручную.")
        return
    if len(services) > 1:
        await state.set_state(OrderFlow.delivery_mode)
        await message.answer(
            "Выберите службу доставки.",
            reply_markup=delivery_service_kb(order_id, services),
        )
        return
    await state.set_state(OrderFlow.delivery_mode)
    await message.answer(
        "Как удобнее получить заказ?",
        reply_markup=delivery_mode_kb(order_id),
    )


async def _ask_mode(message: Message, state: FSMContext, order_id: int, service: str) -> None:
    await state.set_state(OrderFlow.delivery_mode)
    await state.update_data(
        order_id=order_id,
        delivery_service=service,
        delivery_mode=None,
        delivery_points=[],
    )
    await message.answer(
        "Как удобнее получить заказ?",
        reply_markup=delivery_mode_kb(order_id),
    )


async def _quote_point(message: Message, state: FSMContext, point: dict) -> None:
    data = await state.get_data()
    order_id = int(data["order_id"])
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        quote = await delivery.quote_pvz(order_id, point, service)
    except Exception as e:  # noqa: BLE001
        await message.answer(delivery.api_error(e))
        return
    await state.clear()
    await _send_delivery_pay(message, order_id, quote)


# ── Доставка: служба, ПВЗ, адрес ───────────────────────
@router.callback_query(F.data.startswith("dlv:"))
async def on_delivery_cb(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) < 3 or cb.message is None:
        await cb.answer()
        return
    action, oid_s = parts[1], parts[2]
    try:
        order_id = int(oid_s)
    except ValueError:
        await cb.answer()
        return
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    if not client.get("phone"):
        await state.set_state(OrderFlow.waiting_contact)
        await state.update_data(pending_delivery_order_id=order_id)
        await cb.message.answer(
            "Для доставки нужен телефон получателя.",
            reply_markup=contact_kb(),
        )
        await cb.answer()
        return

    if action == "go":
        await _start_delivery(cb.message, state, order_id)
        await cb.answer()
        return
    if action == "svc" and len(parts) >= 4:
        svc = parts[3]
        if svc not in delivery.SERVICE_LABELS:
            await cb.answer()
            return
        await _ask_mode(cb.message, state, order_id, svc)
        await cb.answer()
        return
    if action in ("pvz", "door"):
        data = await state.get_data()
        service = await delivery.resolve_service(data.get("delivery_service"))
        await state.set_state(OrderFlow.delivery_city)
        await state.update_data(
            order_id=order_id,
            delivery_mode=action,
            delivery_service=service,
            delivery_points=[],
        )
        hint = (
            "Напишите город или индекс, где заберёте заказ."
            if action == "pvz"
            else "Напишите город или индекс для курьера."
        )
        await cb.message.answer(hint)
        await cb.answer()
        return
    if action == "n" and len(parts) >= 4:
        try:
            idx = int(parts[3])
        except ValueError:
            await cb.answer()
            return
        points = (await state.get_data()).get("delivery_points") or []
        if idx < 0 or idx >= len(points):
            await cb.answer("Список устарел — напишите город ещё раз", show_alert=True)
            return
        await _quote_point(cb.message, state, points[idx])
        await cb.answer()
        return
    await cb.answer()


@router.message(OrderFlow.delivery_city, F.text)
async def on_delivery_city(msg: Message, state: FSMContext) -> None:
    city = (msg.text or "").strip()
    if not city:
        await msg.answer("Напишите город или индекс.")
        return
    data = await state.get_data()
    mode = data.get("delivery_mode")
    order_id = int(data["order_id"])
    if mode == "door":
        await state.update_data(delivery_city=city)
        await state.set_state(OrderFlow.delivery_address)
        await msg.answer("Напишите улицу, дом и квартиру.")
        return
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        points = await delivery.pickup_points(city, service)
    except Exception as e:  # noqa: BLE001
        await msg.answer(delivery.api_error(e))
        return
    if not points:
        await msg.answer(
            delivery.empty_points_text(service),
            reply_markup=delivery_mode_kb(order_id),
        )
        return
    await state.update_data(delivery_city=city, delivery_points=points, delivery_service=service)
    await state.set_state(OrderFlow.delivery_pvz)
    await msg.answer(
        delivery.points_text(city, points, service),
        reply_markup=delivery_points_kb(order_id, points),
    )


@router.message(OrderFlow.delivery_address, F.text)
async def on_delivery_address(msg: Message, state: FSMContext) -> None:
    street = (msg.text or "").strip()
    if not street:
        await msg.answer("Напишите улицу, дом и квартиру.")
        return
    data = await state.get_data()
    order_id = int(data["order_id"])
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        quote = await delivery.quote_door(
            order_id, data.get("delivery_city") or "", street, service
        )
    except Exception as e:  # noqa: BLE001
        await msg.answer(delivery.api_error(e))
        return
    await state.clear()
    await _send_delivery_pay(msg, order_id, quote)


@router.message(OrderFlow.delivery_pvz, F.text)
async def on_delivery_pvz_text(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    points = (await state.get_data()).get("delivery_points") or []
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(points):
            await _quote_point(msg, state, points[idx])
            return
        await msg.answer("Нет такого номера. Нажмите кнопку или напишите город заново.")
        return
    await state.set_state(OrderFlow.delivery_city)
    await on_delivery_city(msg, state)


# ── Ввод имени / материалов ────────────────────────────
@router.message(OrderFlow.waiting_name, F.text)
async def on_name(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=msg.text)
    await state.clear()
    await _send_pay(msg, order_id, "msg_007а")
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
    await _send_pay(cb.message, order_id, "msg_007б")
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
