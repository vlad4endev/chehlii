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
from maxapi import Dispatcher, F
from maxapi.context import MemoryContext
from maxapi.types import (
    BotStarted,
    CommandStart,
    MessageCallback,
    MessageCreated,
)

from bots.core import consult, delivery, payments
from bots.core.backend import backend
from bots.core.texts import texts
from bots.max.chat_map import remember
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

dp = Dispatcher()
CHANNEL = "max"

_PHONE_RE = re.compile(r"(?:\+?7|8)?\s*\(?(\d{3})\)?\s*(\d{3})[\s-]?(\d{2})[\s-]?(\d{2})")
_PAYLOAD_ORDER_RE = re.compile(r"order[_-](\d+)")


def _fmt_price(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _normalize_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text or "")
    if not m:
        return None
    return "+7" + "".join(m.groups())


def _bot_identity(bot) -> tuple[str | None, int | None]:
    me = getattr(bot, "me", None) or getattr(bot, "_me", None)
    if me is None:
        return None, None
    return getattr(me, "username", None), getattr(me, "user_id", None)


async def _send_menu(bot, chat_id: int, text: str) -> None:
    username, bot_id = _bot_identity(bot)
    await bot.send_message(chat_id=chat_id, text=text, attachments=[main_menu_kb(username, bot_id)])


def _pay_atts(block: payments.PayBlock):
    return [pay_kb(block.buttons)] if block.buttons else []


async def _replace(event: MessageCallback, text: str, attachments=None) -> None:
    """Клик по кнопкам — правим это же сообщение, а не копим новые в чате.

    attachments=[] снимает старые кнопки. None тоже очищает: иначе MAX оставит
    прежнюю клавиатуру.
    """
    atts = [] if attachments is None else attachments
    try:
        await event.message.edit(text=text, attachments=atts, notify=False)
        return
    except Exception:
        logging.debug("max: не удалось заменить сообщение, шлём новое", exc_info=True)
    chat_id = event.message.recipient.chat_id
    await event.bot.send_message(
        chat_id=chat_id, text=text, attachments=atts or None
    )


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
    bot, chat_id: int, order_id: int, context: MemoryContext, phone: str | None,
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
    bot, chat_id: int, order_id: int, context: MemoryContext, event: MessageCallback | None = None,
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
    bot, chat_id: int, order_id: int, service: str, context: MemoryContext,
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
    bot, chat_id: int, context: MemoryContext, point: dict, event: MessageCallback | None = None
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


async def _ask_contact_for_order(bot, chat_id: int, order_id: int, client_id: int, context: MemoryContext) -> None:
    """Запрос контакта на моменте заказа: запоминаем заказ, просим телефон."""
    await context.set_state(OrderFlow.waiting_phone)
    await context.update_data(pending_order_id=order_id)
    await bot.send_message(
        chat_id=chat_id,
        text="Отличный выбор! 🎉\n\n" + texts.get("msg_002")
        + "\n\nОтправьте номер в формате +7XXXXXXXXXX или нажмите кнопку ниже.",
        attachments=[contact_kb()],
    )
    await backend.mark_journey(client_id, "msg_002")


async def _show_order_confirm(bot, chat_id: int, order_id: int, client_id: int, context: MemoryContext) -> None:
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


async def _enter(bot, chat_id: int, user_id: int, nickname: str | None, payload: str | None,
                 context: MemoryContext) -> None:
    """Единый вход: /start, первый старт бота или возврат из мини-приложения."""
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
@dp.bot_started()
async def on_bot_started(event: BotStarted, context: MemoryContext) -> None:
    await context.clear()
    await _enter(
        event.bot, event.chat_id, event.user.user_id, event.user.username, event.payload, context
    )


@dp.message_created(CommandStart())
async def on_start_cmd(event: MessageCreated, context: MemoryContext) -> None:
    await context.clear()
    sender = event.message.sender
    text = event.message.body.text or ""
    payload = text.partition(" ")[2].strip() or None  # аргумент после /start
    await _enter(
        event.bot, event.message.recipient.chat_id, sender.user_id,
        sender.username or sender.full_name, payload, context,
    )


def _extract_contact_phone(event: MessageCreated) -> str | None:
    """Best-effort: телефон из вложения-контакта (vCard), если MAX его прислал."""
    for att in event.message.body.attachments or []:
        payload = getattr(att, "payload", None)
        vcf = getattr(payload, "vcf_info", None)
        if vcf:
            phone = _normalize_phone(re.sub(r"[^\d+]", "", vcf.replace("TEL", " ")))
            if phone:
                return phone
    return None


@dp.message_created(OrderFlow.waiting_phone)
async def on_phone(event: MessageCreated, context: MemoryContext) -> None:
    sender = event.message.sender
    phone = _extract_contact_phone(event) or _normalize_phone(event.message.body.text or "")
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
@dp.message_callback(F.callback.payload == CB_CONFIRM)
async def on_confirm(event: MessageCallback, context: MemoryContext) -> None:
    data = await context.get_data()
    is_custom = data.get("is_custom", False)
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


@dp.message_callback(F.callback.payload == CB_CANCEL)
async def on_cancel(event: MessageCallback, context: MemoryContext) -> None:
    await context.clear()
    await event.answer(notification="Заказ отменён")
    await _replace_menu(event, "Вы в главном меню.")


# ── Пункты меню ────────────────────────────────────────
@dp.message_callback(F.callback.payload == CB_CATALOG)
async def on_catalog_stub(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer(
        notification="Каталог откроется в мини-приложении после публикации в MAX."
    )


# В MAX нет постоянной reply-клавиатуры, поэтому меню держим на том же
# сообщении: пункт меню заменяет текст и кнопки, а не шлёт ещё одну карточку.
@dp.message_callback(F.callback.payload == CB_DISCOUNT)
async def on_discount(event: MessageCallback, context: MemoryContext) -> None:
    c = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    await event.answer()
    await _replace_menu(
        event,
        f"Ваша скидка: {int(c.get('total_discount', 0))}%\n"
        f"Ваш промокод для друга: {c.get('slave_code') or '—'}\n\n"
        "Приглашайте друзей — за каждого начисляется скидка (задаёт администратор).",
    )


@dp.message_callback(F.callback.payload == CB_PAYMENTS)
async def on_payments(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await _replace_menu(
        event,
        "Раздел «Мои оплаты» появится после подключения платёжного шлюза.",
    )


@dp.message_callback(F.callback.payload == CB_DELIVERIES)
async def on_deliveries(event: MessageCallback, context: MemoryContext) -> None:
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


@dp.message_callback(F.callback.payload == CB_HELP)
async def on_help(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.consulting)
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_help")
    await _replace_menu(event, texts.get("msg_help"))


# ── Ввод имени / материалов ────────────────────────────
@dp.message_created(OrderFlow.waiting_name)
async def on_name(event: MessageCreated, context: MemoryContext) -> None:
    data = await context.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=event.message.body.text or "")
    await context.clear()
    await _send_pay(event.bot, event.message.recipient.chat_id, order_id, "msg_007а")
    s = event.message.sender
    client = await backend.upsert_client(CHANNEL, str(s.user_id), nickname=(s.username or s.full_name))
    await backend.mark_journey(client["id"], "msg_007а")


@dp.message_created(OrderFlow.waiting_materials)
async def on_materials(event: MessageCreated, context: MemoryContext) -> None:
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
        "Всё верно? Нажмите «Подтвердить» — и чехол уйдёт в работу.",
        attachments=[materials_confirm_kb()],
    )


@dp.message_callback(F.callback.payload == CB_MAT_CONFIRM)
async def on_materials_confirm(event: MessageCallback, context: MemoryContext) -> None:
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


@dp.message_callback(F.callback.payload == CB_MAT_REDO)
async def on_materials_redo(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.waiting_materials)
    await _replace(event, texts.get("msg_006б"))
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_006б")


# ── Ответ клиента на макет («Подтвердить» / «Переделать») ──
@dp.message_callback(F.callback.payload.startswith("mockup:"))
async def on_mockup_response(event: MessageCallback, context: MemoryContext) -> None:
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


@dp.message_callback(F.callback.payload.startswith("dlv:"))
async def on_delivery_cb(event: MessageCallback, context: MemoryContext) -> None:
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
    if not client.get("phone"):
        await context.set_state(OrderFlow.waiting_phone)
        await context.update_data(pending_delivery_order_id=order_id)
        await event.answer()
        await _replace(
            event,
            "Для доставки нужен телефон получателя. Пришлите номер в формате +7XXXXXXXXXX.",
            [contact_kb()],
        )
        return
    if action == "go":
        await event.answer()
        await _start_delivery(
            event.bot, chat_id, order_id, context, event=event, phone=client.get("phone")
        )
        return
    if action == "svc" and len(parts) >= 4:
        svc = parts[3]
        if svc not in delivery.SERVICE_LABELS:
            await event.answer()
            return
        await event.answer()
        await _ask_mode(
            event.bot, chat_id, order_id, svc, context, event=event, phone=client.get("phone")
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
                event.bot, chat_id, order_id, context, client.get("phone"), event=event
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
            "Напишите город или индекс, где заберёте заказ."
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


@dp.message_created(OrderFlow.delivery_city)
async def on_delivery_city(event: MessageCreated, context: MemoryContext) -> None:
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


@dp.message_created(OrderFlow.delivery_address)
async def on_delivery_address(event: MessageCreated, context: MemoryContext) -> None:
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


@dp.message_created(OrderFlow.delivery_pvz)
async def on_delivery_pvz_text(event: MessageCreated, context: MemoryContext) -> None:
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


@dp.message_created(OrderFlow.consulting)
async def on_consult(event: MessageCreated, context: MemoryContext) -> None:
    s = event.message.sender
    remember(s.user_id, event.message.recipient.chat_id)
    client = await backend.upsert_client(
        CHANNEL, str(s.user_id), nickname=(s.username or s.full_name)
    )
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
    # Без автоответа: «печатает…» появится, когда админ начнёт набирать ответ.


# Фолбэк: любое сообщение вне сценария → в меню. Регистрируется последним.
@dp.message_created(F.message.body.text)
async def on_fallback(event: MessageCreated, context: MemoryContext) -> None:
    await _send_menu(event.bot, event.message.recipient.chat_id, "Выберите раздел в меню.")
