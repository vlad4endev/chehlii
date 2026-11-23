"""Хендлеры Telegram-бота: заказ, оплата, оформление доставки.

Вся бизнес-логика и данные — в едином backend; здесь только Telegram-адаптер.
"""

from __future__ import annotations

import contextlib
import json
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
    ReplyKeyboardRemove,
    User,
)

from bots.core import consult, delivery, payments, review
from bots.core.backend import backend
from bots.core.fetch_media import fetch_bytes
from bots.core.phone import format_phone, is_russian_mobile, normalize_any_phone
from bots.core.promo import MAX_PROMO_ATTEMPTS, looks_like_promo_code
from bots.core.texts import texts
from bots.tg.keyboards import (
    BTN_CATALOG,
    BTN_DELIVERIES,
    BTN_DISCOUNT,
    BTN_HELP,
    BTN_PAYMENTS,
    BTN_PHONE_MANUAL,
    confirm_kb,
    contact_kb,
    delivery_mode_kb,
    delivery_orders_kb,
    delivery_points_kb,
    delivery_service_kb,
    delivery_start_kb,
    main_menu_kb,
    materials_confirm_kb,
    materials_files_done_kb,
    materials_skip_desc_kb,
    pay_kb,
    phone_confirm_kb,
    pick_order_kb,
)
from bots.tg.states import OrderFlow

router = Router()
CHANNEL = "tg"
_MENU_TEXTS = {BTN_HELP, BTN_CATALOG, BTN_DISCOUNT, BTN_PAYMENTS, BTN_DELIVERIES}

# Состояния, где свободный текст — не ввод сценария (переслать менеджеру).
_OFFSCRIPT_STATES = {
    OrderFlow.confirming,
    OrderFlow.confirming_materials,
    OrderFlow.delivery_mode,
    OrderFlow.delivery_pvz,
    OrderFlow.waiting_contact,
}


def _fmt_price(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _parallel_order_ids(data: dict) -> list[int]:
    """Текущий заказ + paused — уникальные id для кнопок выбора."""
    ids: list[int] = []
    cur = data.get("order_id")
    if cur:
        ids.append(int(cur))
    for p in data.get("paused_orders") or []:
        oid = p.get("order_id")
        if oid and int(oid) not in ids:
            ids.append(int(oid))
    return ids


async def _offer_order_pick(msg: Message, state: FSMContext, *, hint: str | None = None) -> bool:
    """Если заказов > 1 — спросить «К какому?» и показать кнопки. True = показали."""
    data = await state.get_data()
    ids = _parallel_order_ids(data)
    if len(ids) < 2:
        return False
    text = hint or "К какому заказу относится сообщение? Выберите кнопкой:"
    await msg.answer(text, reply_markup=pick_order_kb(ids))
    return True


async def _client(msg: Message) -> dict:
    u = msg.from_user
    nickname = u.username or u.full_name if u else None
    return await backend.upsert_client(CHANNEL, str(u.id), nickname=nickname)


def _pay_markup(block: payments.PayBlock):
    return pay_kb(block.buttons) if block.buttons else None


async def _replace_or_send(message: Message | None, text: str, markup=None) -> None:
    """Клик по кнопкам — правим это же сообщение, а не копим новые в чате."""
    if message is None:
        return
    is_bot = bool(getattr(getattr(message, "from_user", None), "is_bot", False))
    if is_bot:
        try:
            has_media = bool(
                getattr(message, "photo", None)
                or getattr(message, "document", None)
                or getattr(message, "video", None)
                or getattr(message, "animation", None)
            )
            if has_media:
                await message.edit_caption(caption=text[:1024], reply_markup=markup)
            else:
                await message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            logging.debug("tg: не удалось заменить сообщение, шлём новое", exc_info=True)
    await message.answer(text, reply_markup=markup)


# ── Вход ───────────────────────────────────────────────
async def _resume_after_pay(msg: Message, payment_id: int) -> None:
    """Возврат со страницы Robokassa: сверить счёт и не сбрасывать диалог в приветствие."""
    try:
        res = await backend.sync_payment(payment_id)
    except Exception:
        logging.warning("tg: не удалось сверить оплату %s", payment_id, exc_info=True)
        res = None
    if res and res.get("status") == "paid":
        await msg.answer("Оплата получена ✅ Продолжаем в следующем сообщении.")
        return
    await msg.answer(
        "Платёж ещё подтверждаем. Если деньги уже списались, подождите минуту "
        "и откройте бота по кнопке ещё раз."
    )


async def _send_start_media(msg: Message, code: str, greeting: str) -> None:
    """Кружок (video_note) + текст отдельно — у кружка нет caption."""
    meta = texts.meta(code)
    fmt = (meta.get("media_format") or "text").strip()
    if fmt not in ("video_note", "video_note_text"):
        await msg.answer(greeting, reply_markup=main_menu_kb())
        return
    file_id = meta.get("media_file_id_tg")
    url = meta.get("media_url")
    try:
        sent = None
        if file_id:
            sent = await msg.answer_video_note(file_id)
        elif url:
            data = await fetch_bytes(url)
            if data:
                sent = await msg.answer_video_note(BufferedInputFile(data, "note.mp4"))
                note = getattr(sent, "video_note", None) if sent else None
                if note and note.file_id:
                    await backend.cache_bot_file_id(code, note.file_id)
                    meta["media_file_id_tg"] = note.file_id
        follow = greeting if fmt == "video_note_text" else (texts.get("msg_001_hint") or greeting)
        await msg.answer(follow, reply_markup=main_menu_kb())
        if sent is not None:
            return
    except Exception:  # noqa: BLE001
        logging.warning("tg: не удалось отправить video_note %s", code, exc_info=True)
    await msg.answer(greeting, reply_markup=main_menu_kb())


@router.message(CommandStart())
async def on_start(msg: Message, state: FSMContext) -> None:
    # Контакт на входе НЕ просим — чтобы не отпугивать. Пользователь свободно
    # смотрит каталог; телефон запросим только при оформлении заказа.
    await state.clear()
    args = msg.text.split(maxsplit=1)[1].strip() if msg.text and " " in msg.text else ""
    pay_id = payments.pay_start_id(args)
    if pay_id is not None:
        await _resume_after_pay(msg, pay_id)
        return
    client = await _client(msg)
    code = "welcome_back" if client.get("phone") else "msg_001"
    greeting = (
        texts.get("welcome_back", discount=int(client.get("total_discount", 0)))
        if client.get("phone")
        else texts.get("msg_001")
    )
    await _send_start_media(msg, code, greeting)
    await backend.mark_journey(client["id"], code)


async def _apply_phone(
    msg: Message, state: FSMContext, phone: str, *, user: User | None = None
) -> None:
    """Общий путь после контакта/текста телефона — как в MAX.

    user — для вызова из callback: там msg.from_user это бот, а не клиент."""
    u = user or msg.from_user
    client = await backend.upsert_client(
        CHANNEL, str(u.id), nickname=(u.username or u.full_name), phone=phone
    )
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
        if not is_russian_mobile(phone):
            # Контактный номер мог быть иностранным, но службы доставки принимают
            # только российский мобильный получателя.
            await msg.answer(_DELIVERY_RU_PHONE_TEXT, reply_markup=contact_kb())
            return
        await _start_delivery(msg, state, int(pending_delivery), client.get("phone"))
        return
    await state.clear()
    await msg.answer(texts.get("msg_003"), reply_markup=main_menu_kb())
    await backend.mark_journey(client["id"], "msg_003")


_PHONE_FORMAT_HINT = (
    "Пришлите номер с кодом страны, например +79001234567 или +380501234567."
)
_DELIVERY_RU_PHONE_TEXT = (
    "Для доставки по России нужен российский мобильный получателя (+79XXXXXXXXX). "
    "Нажмите «✏️ Ввести другой номер» или пришлите номер."
)


@router.message(F.contact)
async def on_contact(msg: Message, state: FSMContext) -> None:
    phone = normalize_any_phone(
        msg.contact.phone_number if msg.contact else None, trusted_digits=True
    )
    if not phone:
        await msg.answer(
            "Не разобрал номер из контакта. Нажмите «✏️ Ввести другой номер» "
            f"и введите его вручную. {_PHONE_FORMAT_HINT}",
            reply_markup=contact_kb(),
        )
        return
    await _apply_phone(msg, state, phone)


# ── Приём выбора из мини-приложения ────────────────────
async def _begin_order(
    msg: Message, state: FSMContext, client_id: int, case_id: int, case_type: str, model: str
) -> None:
    """Создать заказ и показать подтверждение. Предыдущий незавершённый сценарий
    сохраняем в paused_orders — клиент может вести несколько заказов параллельно."""
    data = await state.get_data()
    paused = list(data.get("paused_orders") or [])
    prev_id = data.get("order_id")
    prev_state = await state.get_state()
    if prev_id and prev_state and prev_state != OrderFlow.consulting.state:
        paused.append(
            {
                "order_id": prev_id,
                "is_custom": data.get("is_custom"),
                "fsm": prev_state,
                "materials_text": data.get("materials_text"),
                "materials_files": data.get("materials_files"),
            }
        )
    order = await backend.create_order(client_id, case_id, case_type, model)
    await state.set_state(OrderFlow.confirming)
    await state.update_data(
        order_id=order["id"],
        is_custom=order["is_custom"],
        paused_orders=paused,
        materials_text="",
        materials_files=[],
        pending_case_id=None,
        pending_case_type=None,
        pending_model=None,
    )
    await msg.answer(
        f"{_order_prefix(order['id'])}"
        + texts.get(
            "msg_005аб",
            type=order["case_name"],
            model=order["model_name"],
            price=_fmt_price(order["client_price"]),
        ),
        reply_markup=confirm_kb(),
    )
    await backend.mark_journey(client_id, "msg_005аб")
    if paused:
        await msg.answer(
            "Предыдущий заказ на паузе. Чтобы вернуться к нему — нажмите кнопку:",
            reply_markup=pick_order_kb(_parallel_order_ids(await state.get_data())),
        )


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
            "Отличный выбор! 🎉\n\n"
            + texts.get("msg_002")
            + "\n\nИли отправьте номер в формате +7XXXXXXXXXX.",
            reply_markup=contact_kb(),
        )
        await backend.mark_journey(client["id"], "msg_002")
        return

    await _begin_order(msg, state, client["id"], case_id, case_type, model)


@router.message(OrderFlow.waiting_contact, F.text)
async def on_waiting_contact_text(msg: Message, state: FSMContext) -> None:
    """Ввод номера вручную: разобрать → показать → попросить подтвердить."""
    if msg.text == BTN_PHONE_MANUAL:
        await msg.answer(
            f"Введите номер телефона. {_PHONE_FORMAT_HINT}", reply_markup=ReplyKeyboardRemove()
        )
        return
    phone = normalize_any_phone(msg.text)
    if not phone:
        await msg.answer(
            "Не разобрал номер. Нажмите «📱 Поделиться контактом» или введите его "
            f"вручную. {_PHONE_FORMAT_HINT}",
            reply_markup=contact_kb(),
        )
        return
    await state.update_data(pending_phone=phone)
    await msg.answer(f"Ваш номер {format_phone(phone)}. Всё верно?", reply_markup=phone_confirm_kb())


@router.callback_query(OrderFlow.waiting_contact, F.data == "phone:ok")
async def on_phone_confirmed(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    phone = data.get("pending_phone")
    await cb.answer()
    if not phone:
        await cb.message.answer(f"Введите номер ещё раз. {_PHONE_FORMAT_HINT}")
        return
    await state.update_data(pending_phone=None)
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.edit_reply_markup(reply_markup=None)
    await _apply_phone(cb.message, state, phone, user=cb.from_user)


@router.callback_query(OrderFlow.waiting_contact, F.data == "phone:retry")
async def on_phone_retry(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(pending_phone=None)
    await cb.answer()
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"Введите номер ещё раз. {_PHONE_FORMAT_HINT}")


@router.message(OrderFlow.waiting_contact)
async def on_waiting_contact_other(msg: Message) -> None:
    await msg.answer(
        "Чтобы оформить заказ, нажмите «📱 Поделиться контактом» "
        f"или введите номер вручную. {_PHONE_FORMAT_HINT}",
        reply_markup=contact_kb(),
    )


def _order_prefix(order_id: int | str | None) -> str:
    if not order_id:
        return ""
    return f"Заказ #{order_id}: "


@router.callback_query(F.data == "order:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    is_custom = bool(data.get("is_custom", False))
    if order_id:
        try:
            order = await backend.get_order(int(order_id))
            if order is not None:
                is_custom = bool(order.get("is_custom", is_custom))
                await state.update_data(is_custom=is_custom, order_id=int(order_id))
        except Exception:  # noqa: BLE001
            logging.warning("tg: не удалось перечитать заказ #%s", order_id, exc_info=True)
    if not order_id:
        await state.clear()
        await _replace_or_send(
            cb.message, "Сессия истекла. Выберите чехол в каталоге ещё раз.", main_menu_kb()
        )
        await cb.answer("Сессия истекла", show_alert=True)
        return
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    if is_custom:
        await state.set_state(OrderFlow.waiting_materials)
        await state.update_data(materials_text="", materials_files=[])
        code = "msg_006б"
        await _replace_or_send(
            cb.message,
            f"{_order_prefix(order_id)}{texts.get(code)}",
            materials_files_done_kb(),
        )
        await backend.mark_journey(client["id"], code)
        await cb.answer()
        return
    # Стандарт: без имени/буквы, сразу полная оплата (100%).
    await state.clear()
    code = "msg_007а"
    await _send_pay(cb.message, int(order_id), code, order_label=True)
    await backend.mark_journey(client["id"], code)
    await cb.answer()


@router.callback_query(F.data == "order:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _replace_or_send(cb.message, "Заказ отменён. Вы в главном меню.")
    await cb.answer()


@router.callback_query(F.data.startswith("order:pick:"))
async def on_pick_order(cb: CallbackQuery, state: FSMContext) -> None:
    """Выбор заказа, когда ввод ждут несколько параллельных сценариев."""
    try:
        oid = int((cb.data or "").split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    data = await state.get_data()
    paused = list(data.get("paused_orders") or [])
    chosen = None
    rest = []
    for p in paused:
        if int(p.get("order_id") or 0) == oid:
            chosen = p
        else:
            rest.append(p)
    if chosen is None and int(data.get("order_id") or 0) == oid:
        await cb.answer("Уже работаем с этим заказом")
        return
    if chosen is None:
        await cb.answer("Заказ не найден в сессии", show_alert=True)
        return
    # Текущий уводим в паузу, восстанавливаем выбранный.
    cur = {
        "order_id": data.get("order_id"),
        "is_custom": data.get("is_custom"),
        "fsm": await state.get_state(),
        "materials_text": data.get("materials_text"),
        "materials_files": data.get("materials_files"),
    }
    if cur["order_id"]:
        rest.append(cur)
    await state.set_state(chosen.get("fsm") or OrderFlow.confirming)
    await state.update_data(
        order_id=chosen["order_id"],
        is_custom=chosen.get("is_custom"),
        materials_text=chosen.get("materials_text") or "",
        materials_files=chosen.get("materials_files") or [],
        paused_orders=rest,
    )
    await cb.message.answer(
        f"Продолжаем заказ #{oid}. Пришлите то, что бот просил на этом шаге.",
        reply_markup=main_menu_kb(),
    )
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
    if approved:
        b = await payments.block(order_id, "postpayment")
        await _replace_or_send(
            cb.message,
            f"Спасибо! Макет согласован — переходим к оплате.\n\n{b.text}",
            _pay_markup(b),
        )
    else:
        await _replace_or_send(
            cb.message, "Принято! Дизайнер доработает макет и пришлёт заново."
        )
    await cb.answer()


# ── Главное меню ───────────────────────────────────────
@router.message(F.text == BTN_CATALOG)
async def on_catalog_fallback(msg: Message, state: FSMContext) -> None:
    await state.clear()
    # Срабатывает только если WebApp-URL не задан (иначе кнопка открывает мини-приложение).
    await msg.answer(
        "Каталог открывается в мини-приложении. Оно подключится после публикации фронтенда "
        "по HTTPS (задать WEBAPP_URL)."
    )


def _discount_text(c: dict) -> str:
    return (
        f"Ваша итоговая скидка: {int(c.get('total_discount', 0))}%\n"
        f"• лояльность: {int(c.get('loyal_discount', 0))}%\n"
        f"• за друзей: {int(c.get('discount_for_slave', 0))}% "
        f"(приглашено: {int(c.get('number_slave', 0))})\n"
        f"• по коду друга: {int(c.get('discount_master_code', 0))}%\n\n"
        f"Ваш промокод для друга: {c.get('slave_code') or '—'}\n"
        f"Друзья получают: {int(c.get('discount_slave_code', 0))}%\n\n"
        + (
            f"Вы уже активировали код: {c['master_code']}"
            if c.get("master_code")
            else "Чтобы получить скидку друга — пришлите его промокод следующим сообщением."
        )
    )


@router.message(F.text == BTN_DISCOUNT)
async def on_discount(msg: Message, state: FSMContext) -> None:
    c = await _client(msg)
    await msg.answer(_discount_text(c), reply_markup=main_menu_kb())
    if not c.get("master_code"):
        await state.set_state(OrderFlow.entering_promo)


@router.message(OrderFlow.entering_promo, F.text, ~F.text.in_(_MENU_TEXTS))
async def on_promo_code(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    if not looks_like_promo_code(text):
        # Не код (фраза, вопрос) — выходим из режима и обрабатываем как обычное сообщение:
        # уйдёт менеджеру/в отзыв, а не в проверку промокода.
        await state.set_state(None)
        await on_fallback(msg, state)
        return
    c = await _client(msg)
    try:
        res = await backend.activate_promo(c["id"], text)
    except ValueError as e:
        data = await state.get_data()
        attempts = int(data.get("promo_attempts") or 0) + 1
        if attempts >= MAX_PROMO_ATTEMPTS:
            await state.set_state(None)
            await state.update_data(promo_attempts=0)
            await msg.answer(
                f"{e or 'Не удалось активировать код.'}\n"
                "Попытки закончились — выберите пункт меню или нажмите «Позвать человека».",
                reply_markup=main_menu_kb(),
            )
            return
        await state.update_data(promo_attempts=attempts)
        await msg.answer(
            f"{e or 'Не удалось активировать код.'}\n"
            "Пришлите другой код или выберите пункт меню.",
            reply_markup=main_menu_kb(),
        )
        return
    except Exception:  # noqa: BLE001
        logging.warning("tg: promo activate failed", exc_info=True)
        await state.set_state(None)
        await msg.answer("Не удалось активировать код. Попробуйте позже.", reply_markup=main_menu_kb())
        return
    await state.clear()
    await msg.answer(
        f"Промокод активирован! Скидка по коду друга: {int(res.get('discount_master_code', 0))}%. "
        f"Итого: {int(res.get('total_discount', 0))}%.",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == BTN_PAYMENTS)
async def on_payments(msg: Message, state: FSMContext) -> None:
    client = await _client(msg)
    try:
        orders = await backend.client_orders(client["id"])
    except Exception:  # noqa: BLE001
        orders = []
    if not orders:
        await msg.answer("Пока нет заказов.", reply_markup=main_menu_kb())
        return
    lines = ["Ваши заказы и оплаты:\n"]
    for o in orders[:20]:
        price = o.get("final_price") or o.get("client_price") or "—"
        pay = o.get("payment_status") or "—"
        lines.append(
            f"#{o['id']} · {o.get('status_label') or o.get('status')} · {price} · оплата: {pay}"
        )
    await msg.answer("\n".join(lines), reply_markup=main_menu_kb())


@router.message(F.text == BTN_DELIVERIES)
async def on_deliveries(msg: Message, state: FSMContext) -> None:
    await state.clear()
    client = await _client(msg)
    try:
        orders = await backend.client_orders(client["id"])
    except Exception:  # noqa: BLE001
        orders = []
    pending = [
        o
        for o in orders
        if o.get("status") in delivery.NEEDS_CHECKOUT and not o.get("tracking_code")
    ]
    text = delivery.orders_text(orders)
    if len(pending) == 1:
        await msg.answer(text, reply_markup=delivery_start_kb(pending[0]["id"]))
    elif pending:
        await msg.answer(text, reply_markup=delivery_orders_kb(pending))
    else:
        await msg.answer(text, reply_markup=main_menu_kb())


async def _call_human(msg: Message, state: FSMContext) -> None:
    """Позвать менеджера, не сбрасывая шаг оформления заказа."""
    client = await _client(msg)
    current = await state.get_state()
    # Если сценария нет — переводим в consulting; иначе только открываем тред.
    if current is None:
        await state.set_state(OrderFlow.consulting)
    try:
        await consult.ingest(client["id"], "[Клиент нажал «Позвать человека»]", [])
    except Exception as e:  # noqa: BLE001
        logging.warning("call human failed: %s", e)
    await backend.mark_journey(client["id"], "msg_help")
    await msg.answer(texts.get("msg_help"), reply_markup=main_menu_kb())


@router.message(F.text == BTN_HELP)
async def on_help(msg: Message, state: FSMContext) -> None:
    await _call_human(msg, state)


@router.message(Command("human"))
async def on_human_cmd(msg: Message, state: FSMContext) -> None:
    await _call_human(msg, state)


async def _send_pay(
    message: Message, order_id: int, code: str, *, order_label: bool = False
) -> None:
    b = await payments.block(order_id)
    prefix = _order_prefix(order_id) if order_label else ""
    await _replace_or_send(
        message, f"{prefix}{texts.get(code)}\n\n{b.text}", _pay_markup(b)
    )


async def _send_delivery_pay(message: Message, order_id: int, quote: dict) -> None:
    if (quote.get("delivery_sum") or 0) <= 0:
        try:
            await backend.delivery_fulfill(order_id)
            await _replace_or_send(message, "Доставка бесплатная — заявку создаём сейчас.")
        except Exception as e:  # noqa: BLE001
            await _replace_or_send(message, delivery.api_error(e))
        return
    b = await payments.block(order_id, "delivery")
    await _replace_or_send(
        message, f"{delivery.quote_text(quote)}\n\n{b.text}", _pay_markup(b)
    )


async def _ask_ozon_city(
    message: Message, state: FSMContext, order_id: int, phone: str | None
) -> None:
    blocked = await delivery.ozon_blocked(phone)
    if blocked:
        await _replace_or_send(message, blocked)
        return
    await state.set_state(OrderFlow.delivery_city)
    await state.update_data(
        order_id=order_id,
        delivery_service="ozon",
        delivery_mode="pvz",
        delivery_points=[],
    )
    await _replace_or_send(
        message,
        "Ozon доставляет только в пункт выдачи. Напишите город или индекс, где заберёте заказ.",
    )


async def _start_delivery(
    message: Message, state: FSMContext, order_id: int, phone: str | None = None
) -> None:
    services = await delivery.configured_services()
    await state.update_data(
        order_id=order_id,
        delivery_mode=None,
        delivery_city=None,
        delivery_points=[],
        delivery_service=services[0] if len(services) == 1 else None,
    )
    if not services:
        await _replace_or_send(
            message, "Доставка ещё не настроена. Напишите нам — отправим вручную."
        )
        return
    if len(services) > 1:
        await state.set_state(OrderFlow.delivery_mode)
        await _replace_or_send(
            message, "Выберите службу доставки.", delivery_service_kb(order_id, services)
        )
        return
    if services[0] == "ozon":
        await _ask_ozon_city(message, state, order_id, phone)
        return
    await state.set_state(OrderFlow.delivery_mode)
    await _replace_or_send(
        message, "Как удобнее получить заказ?", delivery_mode_kb(order_id, services[0])
    )


async def _ask_mode(
    message: Message,
    state: FSMContext,
    order_id: int,
    service: str,
    phone: str | None = None,
) -> None:
    if service == "ozon":
        await _ask_ozon_city(message, state, order_id, phone)
        return
    await state.set_state(OrderFlow.delivery_mode)
    await state.update_data(
        order_id=order_id,
        delivery_service=service,
        delivery_mode=None,
        delivery_points=[],
    )
    await _replace_or_send(
        message, "Как удобнее получить заказ?", delivery_mode_kb(order_id, service)
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
    phone = client.get("phone")
    if not is_russian_mobile(phone):
        await state.set_state(OrderFlow.waiting_contact)
        await state.update_data(pending_delivery_order_id=order_id)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.message.answer(
            _DELIVERY_RU_PHONE_TEXT,
            reply_markup=contact_kb(),
        )
        await cb.answer()
        return

    if action == "go":
        await _start_delivery(cb.message, state, order_id, phone)
        await cb.answer()
        return
    if action == "svc" and len(parts) >= 4:
        svc = parts[3]
        if svc not in delivery.SERVICE_LABELS:
            await cb.answer()
            return
        await _ask_mode(cb.message, state, order_id, svc, phone)
        await cb.answer()
        return
    if action in ("pvz", "door"):
        data = await state.get_data()
        service = await delivery.resolve_service(data.get("delivery_service"))
        if action == "door" and not delivery.has_door(service):
            await cb.answer("Ozon доставляет только в пункт выдачи", show_alert=True)
            return
        if service == "ozon":
            await _ask_ozon_city(cb.message, state, order_id, phone)
            await cb.answer()
            return
        await state.set_state(OrderFlow.delivery_city)
        await state.update_data(
            order_id=order_id,
            delivery_mode=action,
            delivery_service=service,
            delivery_points=[],
        )
        hint = (
            delivery.pvz_prompt(service)
            if action == "pvz"
            else "Напишите город или индекс для курьера."
        )
        await _replace_or_send(cb.message, hint)
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
            reply_markup=delivery_mode_kb(order_id, service),
        )
        return
    await state.update_data(delivery_city=city, delivery_points=points, delivery_service=service)
    await state.set_state(OrderFlow.delivery_pvz)
    await msg.answer(
        delivery.points_text(city, points, service),
        reply_markup=delivery_points_kb(order_id, points, service),
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


@router.message(OrderFlow.confirming)
async def on_early_content(msg: Message, state: FSMContext) -> None:
    # Фото/текст прислали, не нажав «Подтвердить»: для кастома это уже материалы —
    # не теряем их и не заставляем слать заново, для стандарта — просим подтвердить.
    data = await state.get_data()
    is_custom = bool(data.get("is_custom", False))
    order_id = data.get("order_id")
    if order_id:
        try:
            order = await backend.get_order(int(order_id))
            if order is not None:
                is_custom = bool(order.get("is_custom", is_custom))
        except Exception:  # noqa: BLE001
            logging.warning("tg: не удалось перечитать заказ #%s", order_id, exc_info=True)
    if is_custom:
        await state.set_state(OrderFlow.waiting_materials)
        await on_materials(msg, state)
        return
    await msg.answer("Сначала подтвердите заказ кнопкой «Подтвердить» выше.")


def _collect_material_files(msg: Message) -> list[dict]:
    files: list[dict] = []
    if msg.photo:
        files.append({"id": msg.photo[-1].file_id, "name": "photo.jpg"})
    if msg.document:
        files.append({"id": msg.document.file_id, "name": msg.document.file_name or "file"})
    if msg.voice:
        files.append({"id": msg.voice.file_id, "name": "voice.ogg"})
    if msg.video:
        files.append({"id": msg.video.file_id, "name": "video.mp4"})
    return files


async def _show_materials_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    desc = (data.get("materials_text") or "").strip() or "—"
    n = len(data.get("materials_files") or [])
    await state.set_state(OrderFlow.confirming_materials)
    body = texts.get("msg_006б_summary", desc=desc, files=n)
    await message.answer(
        f"{_order_prefix(order_id)}{body}\n\n"
        "Всё верно? После подтверждения внесёте предоплату — дизайнер пришлёт макет.",
        reply_markup=materials_confirm_kb(),
    )


@router.message(OrderFlow.waiting_materials)
async def on_materials(msg: Message, state: FSMContext) -> None:
    """Шаг 1: только файлы. Подпись фото → сразу в описание, шаг 2 пропускаем."""
    if msg.text in _MENU_TEXTS:
        return
    data = await state.get_data()
    existing: list[dict] = list(data.get("materials_files") or [])
    new_files = _collect_material_files(msg)
    caption = (msg.caption or "").strip()
    # Чистый текст без файлов на шаге фото — вне сценария → менеджеру.
    if not new_files and (msg.text or "").strip():
        await _relay_offscript(msg, state)
        return
    if not new_files:
        await msg.answer(
            "Пришлите фото или файлы, затем нажмите «Готово, дальше».",
            reply_markup=materials_files_done_kb(),
        )
        return
    existing.extend(new_files)
    updates: dict = {"materials_files": existing}
    if caption:
        updates["materials_text"] = caption
    await state.update_data(**updates)
    if caption:
        await _show_materials_summary(msg, state)
        return
    await msg.answer(
        f"Добавлено вложений: {len(existing)}. Можно прислать ещё или нажать «Готово, дальше».",
        reply_markup=materials_files_done_kb(),
    )


@router.callback_query(OrderFlow.waiting_materials, F.data == "materials:files_done")
async def on_materials_files_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    files = data.get("materials_files") or []
    if not files:
        await cb.answer("Сначала пришлите хотя бы одно фото или файл", show_alert=True)
        return
    if (data.get("materials_text") or "").strip():
        await _show_materials_summary(cb.message, state)
        await cb.answer()
        return
    await state.set_state(OrderFlow.waiting_materials_desc)
    await _replace_or_send(
        cb.message,
        f"{_order_prefix(data.get('order_id'))}{texts.get('msg_006б_desc')}",
        materials_skip_desc_kb(),
    )
    await cb.answer()


@router.message(OrderFlow.waiting_materials_desc)
async def on_materials_desc(msg: Message, state: FSMContext) -> None:
    if msg.text in _MENU_TEXTS:
        return
    # Пока ждём описание — новое фото дописывается к вложениям.
    new_files = _collect_material_files(msg)
    data = await state.get_data()
    if new_files:
        files = list(data.get("materials_files") or [])
        files.extend(new_files)
        await state.update_data(materials_files=files)
        await msg.answer(
            f"Фото добавлено (всего {len(files)}). Теперь опишите пожелание или нажмите «Без описания».",
            reply_markup=materials_skip_desc_kb(),
        )
        return
    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.answer(
            texts.get("msg_006б_desc"),
            reply_markup=materials_skip_desc_kb(),
        )
        return
    await state.update_data(materials_text=text)
    await _show_materials_summary(msg, state)


@router.callback_query(OrderFlow.waiting_materials_desc, F.data == "materials:skip_desc")
async def on_materials_skip_desc(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(materials_text="")
    await _show_materials_summary(cb.message, state)
    await cb.answer()


async def _persist_files(bot, order_id: int, files: list[dict]) -> list[str]:
    """Скачать файлы из Telegram и загрузить на Яндекс Диск через backend."""
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
    await cb.answer()
    links = await _persist_files(cb.bot, order_id, data.get("materials_files", []))
    await backend.update_order(
        order_id,
        materials_text=data.get("materials_text", ""),
        materials_files=links,
    )
    await state.clear()
    await _send_pay(cb.message, order_id, "msg_007б", order_label=True)
    u = cb.from_user
    client = await backend.upsert_client(CHANNEL, str(u.id), nickname=(u.username or u.full_name))
    await backend.mark_journey(client["id"], "msg_007б")


@router.callback_query(OrderFlow.confirming_materials, F.data == "materials:edit_files")
async def on_materials_edit_files(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(materials_files=[])
    await state.set_state(OrderFlow.waiting_materials)
    await _replace_or_send(
        cb.message,
        f"{_order_prefix((await state.get_data()).get('order_id'))}{texts.get('msg_006б')}",
        materials_files_done_kb(),
    )
    await cb.answer()


@router.callback_query(OrderFlow.confirming_materials, F.data == "materials:edit_desc")
async def on_materials_edit_desc(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderFlow.waiting_materials_desc)
    await _replace_or_send(
        cb.message,
        f"{_order_prefix((await state.get_data()).get('order_id'))}{texts.get('msg_006б_desc')}",
        materials_skip_desc_kb(),
    )
    await cb.answer()


@router.callback_query(OrderFlow.confirming_materials, F.data == "materials:redo")
async def on_materials_redo(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(materials_text="", materials_files=[])
    await state.set_state(OrderFlow.waiting_materials)
    await _replace_or_send(
        cb.message,
        f"{_order_prefix((await state.get_data()).get('order_id'))}{texts.get('msg_006б')}",
        materials_files_done_kb(),
    )
    await cb.answer()


async def _consult_files(msg: Message) -> list[tuple[str, bytes]]:
    """Скачать вложения сообщения для консультации."""
    bot = msg.bot
    wanted: list[tuple[str, str]] = []
    if msg.photo:
        wanted.append((msg.photo[-1].file_id, "photo.jpg"))
    if msg.document:
        wanted.append((msg.document.file_id, msg.document.file_name or "file"))
    if msg.voice:
        wanted.append((msg.voice.file_id, "voice.ogg"))
    if msg.video:
        wanted.append((msg.video.file_id, "video.mp4"))
    if msg.video_note:
        wanted.append((msg.video_note.file_id, "note.mp4"))
    if msg.audio:
        wanted.append((msg.audio.file_id, msg.audio.file_name or "audio.mp3"))
    out: list[tuple[str, bytes]] = []
    for fid, name in wanted:
        try:
            buf = await bot.download(fid)
            out.append((name, buf.read()))
        except Exception as e:  # noqa: BLE001
            logging.warning("consult tg download failed: %s", e)
    return out


async def _relay_review(msg: Message, client: dict, state: FSMContext | None = None) -> bool:
    """True, если сообщение обработано как отзыв (или отказ из‑за пустоты)."""
    if not await review.has_pending(client["id"]):
        return False
    try:
        ok = await review.ingest(
            client["id"], msg.caption or msg.text, await _consult_files(msg)
        )
    except Exception as e:  # noqa: BLE001
        logging.warning("review send failed: %s", e)
        await msg.answer("Не получилось сохранить отзыв, попробуйте ещё раз.")
        return True
    if not ok:
        await msg.answer("Напишите текст отзыва или пришлите фото чехла.")
        return True
    if state is not None:
        await state.clear()
    await backend.mark_journey(client["id"], "msg_017")
    return True


async def _relay_consult(
    msg: Message,
    client: dict,
    state: FSMContext | None = None,
    *,
    force_consulting: bool = True,
    ack: bool = False,
) -> bool:
    """Сохранить в переписку. True если удалось. Не ломает текущий шаг, если force_consulting=False."""
    if await _relay_review(msg, client, state):
        return True
    try:
        ok = await consult.ingest(
            client["id"], msg.caption or msg.text, await _consult_files(msg)
        )
    except Exception as e:  # noqa: BLE001
        logging.warning(
            "consult send failed client=%s: %s", client.get("id"), e, exc_info=True
        )
        await msg.answer("Не получилось передать сообщение, попробуйте ещё раз.")
        return False
    if not ok:
        await msg.answer("Напишите текст или пришлите фото — передадим администратору.")
        return False
    if state is not None and force_consulting:
        current = await state.get_state()
        if current is None:
            await state.set_state(OrderFlow.consulting)
    if ack:
        await msg.answer(texts.get("msg_offscript") or texts.get("msg_help_ack"))
    return True


async def _relay_offscript(msg: Message, state: FSMContext) -> None:
    """Неожиданное сообщение на шаге сценария → менеджеру, кнопки шага остаются."""
    client = await _client(msg)
    data = await state.get_data()
    order_id = data.get("order_id")
    step = await state.get_state()
    logging.info(
        "offscript client=%s step=%s order=%s text=%r",
        client.get("id"),
        step,
        order_id,
        (msg.text or msg.caption or "")[:80],
    )
    if await _relay_review(msg, client, state):
        return
    # Номер заказа в тексте — видно в админке без отдельной колонки.
    raw = (msg.caption or msg.text or "").strip()
    tagged = f"[Заказ #{order_id}] {raw}".strip() if order_id else raw
    try:
        ok = await consult.ingest(client["id"], tagged or None, await _consult_files(msg))
    except Exception as e:  # noqa: BLE001
        logging.warning("offscript consult failed: %s", e, exc_info=True)
        await msg.answer("Не получилось передать сообщение, попробуйте ещё раз.")
        return
    if ok:
        await msg.answer(texts.get("msg_offscript") or texts.get("msg_help_ack"))
    else:
        await msg.answer("Напишите текст или пришлите фото — передадим администратору.")
    # Несколько активных заказов — предложить переключиться на нужный сценарий.
    await _offer_order_pick(msg, state)


@router.message(OrderFlow.consulting)
async def on_consult(msg: Message, state: FSMContext) -> None:
    if msg.text in _MENU_TEXTS:
        return
    await _relay_consult(msg, await _client(msg), state, ack=False)


# Неожиданный ввод на шагах, где ждут кнопку (не текст).
@router.message(StateFilter(*_OFFSCRIPT_STATES))
async def on_offscript_busy(msg: Message, state: FSMContext) -> None:
    if msg.text in _MENU_TEXTS:
        return
    # confirming + кастом: фото уже обрабатывает on_early_content (более специфичный фильтр).
    # Здесь — всё остальное.
    data = await state.get_data()
    current = await state.get_state()
    if current == OrderFlow.confirming.state and bool(data.get("is_custom")):
        # Пусть сработает on_early_content, если он зарегистрирован раньше… иначе материалы.
        if msg.photo or msg.document or msg.voice or msg.video or msg.caption:
            await state.set_state(OrderFlow.waiting_materials)
            await on_materials(msg, state)
            return
    await _relay_offscript(msg, state)


# Фолбэк: отзыв (если заказ ждёт) или свободный текст/фото → админу.
@router.message(StateFilter(None))
async def on_fallback(msg: Message, state: FSMContext) -> None:
    if msg.text in _MENU_TEXTS:
        return
    client = await _client(msg)
    if await _relay_review(msg, client, state):
        return
    if not await consult.allowed_to_write(client):
        await msg.answer(
            "Выберите раздел в меню или нажмите «Позвать человека».",
            reply_markup=main_menu_kb(),
        )
        return
    await _relay_consult(msg, client, state)
