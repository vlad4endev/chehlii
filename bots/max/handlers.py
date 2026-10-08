"""Хендлеры MAX-бота (паритет с Telegram Фазы 1: вход → заказ → имя/материалы).

Один backend обслуживает все платформы — здесь только адаптер MAX. Отличия канала
от Telegram (по итогам spike, docs/MAX_SPIKE.md):
- R1 «Поделиться контактом»: используем текстовый ввод телефона как надёжный путь,
  дополнительно предлагаем нативную кнопку RequestContact (best-effort).
- R2 нет аналога WebApp.sendData: выбор из мини-приложения приходит через backend —
  мини-приложение создаёт заказ и открывает бота с deep-link payload `order_<id>`,
  бот подхватывает заказ по id.
"""

from __future__ import annotations

import logging
import re

import httpx
from maxapi import F, Router
from maxapi.context.base import BaseContext
from maxapi.types import (
    BotStarted,
    CommandStart,
    MessageCallback,
    MessageCreated,
)

from bots.core import consult, delivery, payments, review
from bots.core.backend import backend
from bots.core.config import settings
from bots.core.phone import normalize_phone
from bots.core.texts import texts
from bots.max.chat_map import remember_async
from bots.max.keyboards import (
    CB_CANCEL,
    CB_CATALOG,
    CB_CONFIRM,
    CB_DELIVERIES,
    CB_DISCOUNT,
    CB_HELP,
    CB_MAT_CONFIRM,
    CB_MAT_REDO,
    CB_PAYMENTS,
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
from bots.max.states import OrderFlow

router = Router()
CHANNEL = "max"

_PAYLOAD_ORDER_RE = re.compile(r"order[_-](\d+)")


def _fmt_price(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _bot_identity(bot) -> tuple[str | None, int | None]:
    """username из .env (MAX_BOT_USERNAME) надёжнее, чем me после холодного старта."""
    me = getattr(bot, "me", None) or getattr(bot, "_me", None)
    bot_id = getattr(me, "user_id", None) if me else None
    username = settings.max_bot_username or (
        getattr(me, "username", None) if me else None
    )
    return username, bot_id


async def _send_menu(bot, chat_id: int, text: str) -> None:
    username, bot_id = _bot_identity(bot)
    await bot.send_message(chat_id=chat_id, text=text, attachments=[main_menu_kb(username, bot_id)])


def _pay_atts(block: payments.PayBlock):
    return [pay_kb(block.buttons)] if block.buttons else []


async def _replace(event: MessageCallback, text: str, attachments=None) -> None:
    """Клик по кнопкам — всегда новое сообщение.

    Не редактируем исходное: в MAX edit затирает текст и inline-блоки сценария
    (меню, оплата, подтверждение). Историю шагов оставляем как есть.
    attachments=None → без вложений; [] тоже без вложений.
    """
    atts = None if attachments is None else (attachments or None)
    chat_id = event.message.recipient.chat_id
    await event.bot.send_message(chat_id=chat_id, text=text, attachments=atts)


async def _replace_menu(event: MessageCallback, text: str) -> None:
    username, bot_id = _bot_identity(event.bot)
    await _replace(event, text, [main_menu_kb(username, bot_id)])


async def _persist_files(order_id: int, urls: list[str]) -> list[str]:
    """Скачать файлы клиента по URL из MAX и залить на Яндекс Диск через backend."""
    links: list[str] = []
    async with httpx.AsyncClient(timeout=30) as http:
        for i, url in enumerate(urls):
            try:
                r = await http.get(url)
                r.raise_for_status()
                res = await backend.add_client_file(order_id, f"file_{i + 1}", r.content)
                links.append(res["url"])
            except Exception as e:  # noqa: BLE001
                logging.warning("client file (max) upload failed: %s", e)
    return links


async def _send_pay(bot, chat_id: int, order_id: int, code: str, event: MessageCallback | None = None) -> None:
    b = await payments.block(order_id)
    text = f"{texts.get(code)}\n\n{b.text}"
    atts = _pay_atts(b)
    if event is not None:
        await _replace(event, text, atts)
        return
    await bot.send_message(chat_id=chat_id, text=text, attachments=atts or None)


async def _send_delivery_pay(
    bot, chat_id: int, order_id: int, quote: dict, event: MessageCallback | None = None
) -> None:
    async def _out(text: str, attachments=None) -> None:
        if event is not None:
            await _replace(event, text, attachments or [])
            return
        await bot.send_message(chat_id=chat_id, text=text, attachments=attachments or None)

    if (quote.get("delivery_sum") or 0) <= 0:
        try:
            await backend.delivery_fulfill(order_id)
            await _out("Доставка бесплатная — заявку создаём сейчас.")
        except Exception as e:  # noqa: BLE001
            await _out(delivery.api_error(e))
        return
    b = await payments.block(order_id, "delivery")
    await _out(f"{delivery.quote_text(quote)}\n\n{b.text}", _pay_atts(b) or None)


async def _ask_ozon_city(
    bot, chat_id: int, order_id: int, context: BaseContext, phone: str | None,
    event: MessageCallback | None = None,
) -> None:
    blocked = await delivery.ozon_blocked(phone)

    async def _out(text: str, attachments=None) -> None:
        if event is not None:
            await _replace(event, text, attachments or [])
            return
        await bot.send_message(chat_id=chat_id, text=text, attachments=attachments or None)

    if blocked:
        await _out(blocked)
        return
    await context.set_state(OrderFlow.delivery_city)
    await context.update_data(
        order_id=order_id,
        delivery_service="ozon",
        delivery_mode="pvz",
        delivery_points=[],
    )
    await _out(
        "Ozon доставляет только в пункт выдачи. Напишите город или индекс, где заберёте заказ."
    )


async def _start_delivery(
    bot, chat_id: int, order_id: int, context: BaseContext, event: MessageCallback | None = None,
    phone: str | None = None,
) -> None:
    services = await delivery.configured_services()
    await context.update_data(
        order_id=order_id,
        delivery_mode=None,
        delivery_city=None,
        delivery_points=[],
        delivery_service=services[0] if len(services) == 1 else None,
    )

    async def _out(text: str, attachments=None) -> None:
        if event is not None:
            await _replace(event, text, attachments or [])
            return
        await bot.send_message(chat_id=chat_id, text=text, attachments=attachments or None)

    if not services:
        await _out("Доставка ещё не настроена. Напишите нам — отправим вручную.")
        return
    await context.set_state(OrderFlow.delivery_mode)
    if len(services) > 1:
        await _out("Выберите службу доставки.", [delivery_service_kb(order_id, services)])
        return
    if services[0] == "ozon":
        await _ask_ozon_city(bot, chat_id, order_id, context, phone, event=event)
        return
    await _out("Как удобнее получить заказ?", [delivery_mode_kb(order_id, services[0])])


async def _ask_mode(
    bot, chat_id: int, order_id: int, service: str, context: BaseContext,
    event: MessageCallback | None = None, phone: str | None = None,
) -> None:
    if service == "ozon":
        await _ask_ozon_city(bot, chat_id, order_id, context, phone, event=event)
        return
    await context.set_state(OrderFlow.delivery_mode)
    await context.update_data(
        order_id=order_id,
        delivery_service=service,
        delivery_mode=None,
        delivery_points=[],
    )
    text = "Как удобнее получить заказ?"
    atts = [delivery_mode_kb(order_id, service)]
    if event is not None:
        await _replace(event, text, atts)
        return
    await bot.send_message(chat_id=chat_id, text=text, attachments=atts)


async def _quote_point(
    bot, chat_id: int, context: BaseContext, point: dict, event: MessageCallback | None = None
) -> None:
    data = await context.get_data()
    order_id = int(data["order_id"])
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        quote = await delivery.quote_pvz(order_id, point, service)
    except Exception as e:  # noqa: BLE001
        if event is not None:
            await _replace(event, delivery.api_error(e))
        else:
            await bot.send_message(chat_id=chat_id, text=delivery.api_error(e))
        return
    await context.clear()
    await _send_delivery_pay(bot, chat_id, order_id, quote, event=event)


async def _ask_contact_for_order(bot, chat_id: int, order_id: int, client_id: int, context: BaseContext) -> None:
    """Запрос контакта на моменте заказа: запоминаем заказ, просим телефон."""
    await context.set_state(OrderFlow.waiting_contact)
    await context.update_data(pending_order_id=order_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Отличный выбор! 🎉\n\n"
            + texts.get("msg_002")
            + "\n\nОтправьте номер в формате +7XXXXXXXXXX или нажмите кнопку ниже."
        ),
        attachments=[contact_kb()],
    )
    await backend.mark_journey(client_id, "msg_002")


async def _show_order_confirm(bot, chat_id: int, order_id: int, client_id: int, context: BaseContext) -> None:
    """Показать подтверждение заказа (тип+модель+цена)."""
    try:
        order = await backend.get_order(order_id)
    except Exception:
        order = None
    if not order:
        await _send_menu(bot, chat_id, "Не нашли заказ. Откройте каталог и выберите снова.")
        return
    await context.set_state(OrderFlow.confirming)
    await context.update_data(
        order_id=order["id"], is_custom=order["is_custom"], pending_order_id=None
    )
    await bot.send_message(
        chat_id=chat_id,
        text=texts.get(
            "msg_005аб",
            type=order["case_name"],
            model=order["model_name"],
            price=_fmt_price(order["client_price"]),
        ),
        attachments=[confirm_kb()],
    )
    await backend.mark_journey(client_id, "msg_005аб")


async def _resume_after_pay(bot, chat_id: int, payment_id: int) -> None:
    """Возврат со страницы Robokassa: сверить счёт и не сбрасывать диалог в приветствие."""
    try:
        res = await backend.sync_payment(payment_id)
    except Exception:
        logging.warning("max: не удалось сверить оплату %s", payment_id, exc_info=True)
        res = None
    if res and res.get("status") == "paid":
        await bot.send_message(
            chat_id=chat_id, text="Оплата получена ✅ Продолжаем в следующем сообщении."
        )
        return
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Платёж ещё подтверждаем. Если деньги уже списались, подождите минуту "
            "и откройте бота по кнопке ещё раз."
        ),
    )


async def _enter(bot, chat_id: int, user_id: int, nickname: str | None, payload: str | None,
                 context: BaseContext) -> None:
    """Единый вход: /start, первый старт бота или возврат из мини-приложения."""
    await remember_async(user_id, chat_id)
    pay_id = payments.pay_start_id(payload)
    if pay_id is not None:
        await _resume_after_pay(bot, chat_id, pay_id)
        return
    client = await backend.upsert_client(CHANNEL, str(user_id), nickname=nickname)

    # Возврат из мини-приложения с заказом. Контакт просим ТОЛЬКО здесь (на заказе):
    # нет телефона → просим поделиться, заказ покажем сразу после.
    if payload and (m := _PAYLOAD_ORDER_RE.search(payload)):
        order_id = int(m.group(1))
        if not client.get("phone"):
            await _ask_contact_for_order(bot, chat_id, order_id, client["id"], context)
        else:
            await _show_order_confirm(bot, chat_id, order_id, client["id"], context)
        return

    # Обычный вход — БЕЗ запроса контакта, чтобы не отпугивать: сразу меню/каталог.
    code = "welcome_back" if client.get("phone") else "msg_001"
    greeting = (
        texts.get("welcome_back", discount=int(client.get("total_discount", 0)))
        if client.get("phone")
        else texts.get("msg_001")
    )
    await _send_menu(bot, chat_id, greeting)
    await backend.mark_journey(client["id"], code)


# ── Вход ───────────────────────────────────────────────
@router.bot_started()
async def on_bot_started(event: BotStarted, context: BaseContext) -> None:
    await context.clear()
    await _enter(
        event.bot, event.chat_id, event.user.user_id, event.user.username, event.payload, context
    )


@router.message_created(CommandStart())
async def on_start_cmd(event: MessageCreated, context: BaseContext) -> None:
    await context.clear()
    sender = event.message.sender
    text = event.message.body.text or ""
    payload = text.partition(" ")[2].strip() or None  # аргумент после /start
    await _enter(
        event.bot, event.message.recipient.chat_id, sender.user_id,
        sender.username or sender.full_name, payload, context,
    )


def _extract_contact_phone(event: MessageCreated) -> str | None:
    """Телефон из вложения-контакта MAX (vCard).

    Важно: нельзя склеивать весь vCard в одну строку цифр — VERSION:3.0 даёт
    префикс «30» и normalize превращает 8900… в мусор вроде +73089…, а Яндекс
    отвечает «Recipient's phone is invalid».
    """
    for att in event.message.body.attachments or []:
        payload = getattr(att, "payload", None)
        if payload is None:
            continue
        structured = getattr(payload, "vcf", None)
        tel = getattr(structured, "phone", None) if structured is not None else None
        if tel:
            phone = normalize_phone(tel)
            if phone:
                return phone
        raw = getattr(payload, "vcf_info", None)
        if not raw:
            continue
        for line in str(raw).replace("\r\n", "\n").split("\n"):
            if not line.upper().startswith("TEL"):
                continue
            _, _, value = line.partition(":")
            phone = normalize_phone(value.strip())
            if phone:
                return phone
    return None



@router.message_created(OrderFlow.waiting_contact)
async def on_phone(event: MessageCreated, context: BaseContext) -> None:
    sender = event.message.sender
    phone = _extract_contact_phone(event) or normalize_phone(event.message.body.text or "")
    if not phone:
        await event.message.answer(
            "Не разобрал номер. Пришлите его в формате +7XXXXXXXXXX.",
            attachments=[contact_kb()],
        )
        return
    client = await backend.upsert_client(
        CHANNEL, str(sender.user_id), nickname=(sender.username or sender.full_name), phone=phone
    )
    # Контакт получен на моменте заказа → сразу показываем подтверждение заказа.
    data = await context.get_data()
    pending = data.get("pending_order_id")
    if pending:
        await _show_order_confirm(
            event.bot, event.message.recipient.chat_id, int(pending), client["id"], context
        )
        return
    pending_delivery = data.get("pending_delivery_order_id")
    if pending_delivery:
        await _start_delivery(
            event.bot,
            event.message.recipient.chat_id,
            int(pending_delivery),
            context,
            phone=phone,
        )
        return
    await context.clear()
    await _send_menu(event.bot, event.message.recipient.chat_id, texts.get("msg_003"))
    await backend.mark_journey(client["id"], "msg_003")


# ── Подтверждение заказа ───────────────────────────────
@router.message_callback(F.callback.payload == CB_CONFIRM)
async def on_confirm(event: MessageCallback, context: BaseContext) -> None:
    data = await context.get_data()
    order_id = data.get("order_id")
    # is_custom берём из заказа, а не только из FSM: после рестарта
    # контекст мог быть пуст → иначе кастом уходит в «имя/букву» без материалов.
    is_custom = bool(data.get("is_custom", False))
    if order_id:
        try:
            order = await backend.get_order(int(order_id))
            if order is not None:
                is_custom = bool(order.get("is_custom", is_custom))
                await context.update_data(is_custom=is_custom, order_id=int(order_id))
        except Exception:  # noqa: BLE001
            logging.warning("max: не удалось перечитать заказ #%s", order_id, exc_info=True)
    if not order_id:
        await event.answer(notification="Сессия истекла")
        await context.clear()
        await _replace_menu(event, "Выберите чехол в каталоге ещё раз.")
        return
    await event.answer(notification="Принято ✅")
    if is_custom:
        await context.set_state(OrderFlow.waiting_materials)
        code = "msg_006б"
    else:
        await context.set_state(OrderFlow.waiting_name)
        code = "msg_006а"
    await _replace(event, texts.get(code))
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], code)


@router.message_callback(F.callback.payload == CB_CANCEL)
async def on_cancel(event: MessageCallback, context: BaseContext) -> None:
    await context.clear()
    await event.answer(notification="Заказ отменён")
    await _replace_menu(event, "Вы в главном меню.")


# ── Пункты меню ────────────────────────────────────────
@router.message_callback(F.callback.payload == CB_CATALOG)
async def on_catalog_stub(event: MessageCallback, context: BaseContext) -> None:
    # Срабатывает только если OpenApp недоступен (нет username бота).
    await event.answer()
    await _replace_menu(
        event,
        "Каталог открывается в мини-приложении. Задайте MAX_BOT_USERNAME в "
        "bots/.env и перезапустите бота — появится кнопка «Каталог».",
    )


# В MAX нет постоянной reply-клавиатуры — меню дублируем на новом сообщении,
# не затирая предыдущие блоки сценария.
@router.message_callback(F.callback.payload == CB_DISCOUNT)
async def on_discount(event: MessageCallback, context: BaseContext) -> None:
    c = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    await event.answer()
    await _replace_menu(
        event,
        f"Ваша скидка: {int(c.get('total_discount', 0))}%\n"
        f"Ваш промокод для друга: {c.get('slave_code') or '—'}\n\n"
        "Приглашайте друзей — за каждого начисляется скидка (задаёт администратор).",
    )


@router.message_callback(F.callback.payload == CB_PAYMENTS)
async def on_payments(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await _replace_menu(
        event,
        "Раздел «Мои оплаты» появится после подключения платёжного шлюза.",
    )


@router.message_callback(F.callback.payload == CB_DELIVERIES)
async def on_deliveries(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    c = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    try:
        orders = await backend.client_orders(c["id"])
    except Exception:  # noqa: BLE001
        orders = []
    pending = [
        o
        for o in orders
        if o.get("status") in delivery.NEEDS_CHECKOUT and not o.get("tracking_code")
    ]
    text = delivery.orders_text(orders)
    if len(pending) == 1:
        await _replace(event, text, [delivery_start_kb(pending[0]["id"])])
    elif pending:
        await _replace(event, text, [delivery_orders_kb(pending)])
    else:
        await _replace_menu(event, text)


@router.message_callback(F.callback.payload == CB_HELP)
async def on_help(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.consulting)
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_help")
    await _replace_menu(event, texts.get("msg_help"))


# ── Ввод имени / материалов ────────────────────────────
@router.message_created(OrderFlow.waiting_name)
async def on_name(event: MessageCreated, context: BaseContext) -> None:
    data = await context.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=event.message.body.text or "")
    await context.clear()
    await _send_pay(event.bot, event.message.recipient.chat_id, order_id, "msg_007а")
    s = event.message.sender
    client = await backend.upsert_client(CHANNEL, str(s.user_id), nickname=(s.username or s.full_name))
    await backend.mark_journey(client["id"], "msg_007а")


@router.message_created(OrderFlow.confirming)
async def on_early_content(event: MessageCreated, context: BaseContext) -> None:
    # Фото/текст прислали, не нажав «Подтвердить»: для кастома это уже материалы —
    # не теряем их, для стандарта — просим подтвердить.
    data = await context.get_data()
    is_custom = bool(data.get("is_custom", False))
    order_id = data.get("order_id")
    if order_id:
        try:
            order = await backend.get_order(int(order_id))
            if order is not None:
                is_custom = bool(order.get("is_custom", is_custom))
        except Exception:  # noqa: BLE001
            logging.warning("max: не удалось перечитать заказ #%s", order_id, exc_info=True)
    if is_custom:
        await context.set_state(OrderFlow.waiting_materials)
        await on_materials(event, context)
        return
    await event.message.answer("Сначала подтвердите заказ кнопкой «Подтвердить» выше.")


@router.message_created(OrderFlow.waiting_materials)
async def on_materials(event: MessageCreated, context: BaseContext) -> None:
    text = event.message.body.text or ""
    files: list[str] = []
    for att in event.message.body.attachments or []:
        payload = getattr(att, "payload", None)
        url = getattr(payload, "url", None)
        if url:
            files.append(url)
    if not text and not files:
        await event.message.answer("Пришлите фото/файлы и/или опишите пожелание.")
        return
    # Не финализируем сразу — показываем сводку и ждём подтверждения (клиент
    # может передумать/переслать заново).
    await context.update_data(materials_text=text, materials_files=files)
    await context.set_state(OrderFlow.confirming_materials)
    await event.message.answer(
        "Проверьте кастом-чехол:\n\n"
        f"📝 Описание: {text or '—'}\n"
        f"📎 Вложений: {len(files)}\n\n"
        "Всё верно? Нажмите «Подтвердить» — внесёте предоплату, "
        "после этого дизайнер пришлёт макет на согласование.",
        attachments=[materials_confirm_kb()],
    )


@router.message_callback(F.callback.payload == CB_MAT_CONFIRM)
async def on_materials_confirm(event: MessageCallback, context: BaseContext) -> None:
    data = await context.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await event.answer(notification="Сессия истекла, начните заново")
        await _replace_menu(event, "Выберите раздел в меню.")
        return
    await event.answer(notification="Принято ✅")
    links = await _persist_files(order_id, data.get("materials_files", []))
    await backend.update_order(
        order_id,
        materials_text=data.get("materials_text", ""),
        materials_files=links,
    )
    await context.clear()
    await _send_pay(event.bot, event.message.recipient.chat_id, order_id, "msg_007б", event=event)
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_007б")


@router.message_callback(F.callback.payload == CB_MAT_REDO)
async def on_materials_redo(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.waiting_materials)
    await _replace(event, texts.get("msg_006б"))
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_006б")


# ── Ответ клиента на макет («Подтвердить» / «Переделать») ──
@router.message_callback(F.callback.payload.startswith("mockup:"))
async def on_mockup_response(event: MessageCallback, context: BaseContext) -> None:
    try:
        _, action, oid = event.callback.payload.split(":")
        order_id = int(oid)
    except (ValueError, AttributeError):
        await event.answer()
        return
    approved = action == "approve"
    try:
        await backend.mockup_response(order_id, approved)
    except Exception:
        await event.answer(notification="Не получилось, попробуйте ещё раз")
        return
    await event.answer(notification="Принято ✅")
    if approved:
        b = await payments.block(order_id, "postpayment")
        await _replace(
            event,
            f"Спасибо! Макет согласован — переходим к оплате.\n\n{b.text}",
            _pay_atts(b),
        )
    else:
        await _replace(event, "Принято! Дизайнер доработает макет и пришлёт заново.")


@router.message_callback(F.callback.payload.startswith("dlv:"))
async def on_delivery_cb(event: MessageCallback, context: BaseContext) -> None:
    parts = (event.callback.payload or "").split(":")
    if len(parts) < 3:
        await event.answer()
        return
    action, oid_s = parts[1], parts[2]
    try:
        order_id = int(oid_s)
    except ValueError:
        await event.answer()
        return
    chat_id = event.message.recipient.chat_id
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    phone = normalize_phone(client.get("phone"))
    if not phone:
        await context.set_state(OrderFlow.waiting_contact)
        await context.update_data(pending_delivery_order_id=order_id)
        await event.answer()
        await _replace(
            event,
            "Для доставки нужен мобильный телефон получателя (+79XXXXXXXXX). "
            "Пришлите номер или нажмите «Поделиться контактом».",
            [contact_kb()],
        )
        return

    if action == "go":
        await event.answer()
        await _start_delivery(
            event.bot, chat_id, order_id, context, event=event, phone=phone
        )
        return
    if action == "svc" and len(parts) >= 4:
        svc = parts[3]
        if svc not in delivery.SERVICE_LABELS:
            await event.answer()
            return
        await event.answer()
        await _ask_mode(
            event.bot, chat_id, order_id, svc, context, event=event, phone=phone
        )
        return
    if action in ("pvz", "door"):
        data = await context.get_data()
        service = await delivery.resolve_service(data.get("delivery_service"))
        if action == "door" and not delivery.has_door(service):
            await event.answer(notification="Ozon доставляет только в пункт выдачи")
            return
        if service == "ozon":
            await event.answer()
            await _ask_ozon_city(
                event.bot, chat_id, order_id, context, phone, event=event
            )
            return
        await context.set_state(OrderFlow.delivery_city)
        await context.update_data(
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
        await event.answer()
        await _replace(event, hint)
        return
    if action == "n" and len(parts) >= 4:
        try:
            idx = int(parts[3])
        except ValueError:
            await event.answer()
            return
        points = (await context.get_data()).get("delivery_points") or []
        if idx < 0 or idx >= len(points):
            await event.answer(notification="Список устарел — напишите город ещё раз")
            return
        await event.answer()
        await _quote_point(event.bot, chat_id, context, points[idx], event=event)
        return
    await event.answer()


@router.message_created(OrderFlow.delivery_city)
async def on_delivery_city(event: MessageCreated, context: BaseContext) -> None:
    city = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id
    if not city:
        await event.message.answer("Напишите город или индекс.")
        return
    data = await context.get_data()
    mode = data.get("delivery_mode")
    order_id = int(data["order_id"])
    if mode == "door":
        await context.update_data(delivery_city=city)
        await context.set_state(OrderFlow.delivery_address)
        await event.message.answer("Напишите улицу, дом и квартиру.")
        return
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        points = await delivery.pickup_points(city, service)
    except Exception as e:  # noqa: BLE001
        await event.message.answer(delivery.api_error(e))
        return
    if not points:
        await event.bot.send_message(
            chat_id=chat_id,
            text=delivery.empty_points_text(service),
            attachments=[delivery_mode_kb(order_id, service)],
        )
        return
    await context.update_data(
        delivery_city=city, delivery_points=points, delivery_service=service
    )
    await context.set_state(OrderFlow.delivery_pvz)
    await event.bot.send_message(
        chat_id=chat_id,
        text=delivery.points_text(city, points, service),
        attachments=[delivery_points_kb(order_id, points, service)],
    )


@router.message_created(OrderFlow.delivery_address)
async def on_delivery_address(event: MessageCreated, context: BaseContext) -> None:
    street = (event.message.body.text or "").strip()
    if not street:
        await event.message.answer("Напишите улицу, дом и квартиру.")
        return
    data = await context.get_data()
    order_id = int(data["order_id"])
    service = await delivery.resolve_service(data.get("delivery_service"))
    try:
        quote = await delivery.quote_door(
            order_id, data.get("delivery_city") or "", street, service
        )
    except Exception as e:  # noqa: BLE001
        await event.message.answer(delivery.api_error(e))
        return
    await context.clear()
    await _send_delivery_pay(event.bot, event.message.recipient.chat_id, order_id, quote)


@router.message_created(OrderFlow.delivery_pvz)
async def on_delivery_pvz_text(event: MessageCreated, context: BaseContext) -> None:
    text = (event.message.body.text or "").strip()
    points = (await context.get_data()).get("delivery_points") or []
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(points):
            await _quote_point(event.bot, event.message.recipient.chat_id, context, points[idx])
            return
        await event.message.answer("Нет такого номера. Нажмите кнопку или напишите город заново.")
        return
    await context.set_state(OrderFlow.delivery_city)
    await on_delivery_city(event, context)


async def _consult_files_max(event: MessageCreated) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    async with httpx.AsyncClient(timeout=40) as http:
        for i, att in enumerate(event.message.body.attachments or []):
            payload = getattr(att, "payload", None)
            url = getattr(payload, "url", None)
            if not url:
                continue
            try:
                r = await http.get(url)
                r.raise_for_status()
                name = getattr(payload, "file_name", None) or f"file_{i + 1}"
                files.append((name, r.content))
            except Exception as e:  # noqa: BLE001
                logging.warning("consult max download failed: %s", e)
    return files


_BUSY_STATES = frozenset(OrderFlow.states())


async def _relay_review(
    event: MessageCreated, client: dict, context: BaseContext | None = None
) -> bool:
    """True, если сообщение обработано как отзыв (или отказ из‑за пустоты)."""
    if not await review.has_pending(client["id"]):
        return False
    text = event.message.body.text or ""
    try:
        ok = await review.ingest(client["id"], text, await _consult_files_max(event))
    except Exception as e:  # noqa: BLE001
        logging.warning("review send failed: %s", e)
        await event.message.answer("Не получилось сохранить отзыв, попробуйте ещё раз.")
        return True
    if not ok:
        await event.message.answer("Напишите текст отзыва или пришлите фото чехла.")
        return True
    if context is not None:
        await context.clear()
    await backend.mark_journey(client["id"], "msg_017")
    return True


async def _relay_consult(
    event: MessageCreated, client: dict, context: BaseContext | None = None
) -> None:
    if await _relay_review(event, client, context):
        return
    text = event.message.body.text or ""
    try:
        ok = await consult.ingest(client["id"], text, await _consult_files_max(event))
    except Exception as e:  # noqa: BLE001
        logging.warning("consult send failed: %s", e)
        await event.message.answer("Не получилось передать сообщение, попробуйте ещё раз.")
        return
    if not ok:
        await event.message.answer("Напишите текст или пришлите фото — передадим администратору.")
        return
    if context is not None:
        await context.set_state(OrderFlow.consulting)
    # Без автоответа: «печатает…» появится, когда админ начнёт набирать ответ.


@router.message_created(OrderFlow.consulting)
async def on_consult(event: MessageCreated, context: BaseContext) -> None:
    s = event.message.sender
    await remember_async(s.user_id, event.message.recipient.chat_id)
    client = await backend.upsert_client(
        CHANNEL, str(s.user_id), nickname=(s.username or s.full_name)
    )
    await _relay_consult(event, client, context)


# Фолбэк: отзыв (если заказ ждёт) или свободный текст/фото → админу.
# Регистрируется последним, шаги заказа/доставки не перехватываем.
@router.message_created()
async def on_fallback(event: MessageCreated, context: BaseContext) -> None:
    current = await context.get_state()
    if current is not None and str(current) in _BUSY_STATES:
        return
    text = event.message.body.text or ""
    if text.startswith("/"):
        return
    s = event.message.sender
    await remember_async(s.user_id, event.message.recipient.chat_id)
    client = await backend.upsert_client(
        CHANNEL, str(s.user_id), nickname=(s.username or s.full_name)
    )
    if await _relay_review(event, client, context):
        return
    if not await consult.allowed_to_write(client):
        await _send_menu(
            event.bot,
            event.message.recipient.chat_id,
            "Выберите раздел в меню или нажмите «Поможем выбрать».",
        )
        return
    await _relay_consult(event, client, context)
