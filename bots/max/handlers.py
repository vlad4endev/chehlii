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

from bots.core.backend import backend
from bots.core.texts import texts
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
    main_menu_kb,
    materials_confirm_kb,
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


async def _pay_line(order_id: int) -> str:
    """Ссылка на предоплату (Robokassa); фолбэк если оплата не настроена."""
    try:
        p = await backend.payment_link(order_id, "prepayment")
        return f"\n\n💳 Внести предоплату {int(p['amount'])} ₽:\n{p['url']}"
    except Exception:
        return "\n\n(ссылка на оплату появится после настройки Robokassa)"


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
        await event.message.answer(texts.get("msg_006б"))
        code = "msg_006б"
    else:
        await context.set_state(OrderFlow.waiting_name)
        await event.message.answer(texts.get("msg_006а"))
        code = "msg_006а"
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], code)


@dp.message_callback(F.callback.payload == CB_CANCEL)
async def on_cancel(event: MessageCallback, context: MemoryContext) -> None:
    await context.clear()
    await event.answer(notification="Заказ отменён")
    await _send_menu(event.bot, event.message.recipient.chat_id, "Вы в главном меню.")


# ── Пункты меню ────────────────────────────────────────
@dp.message_callback(F.callback.payload == CB_CATALOG)
async def on_catalog_stub(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer(
        notification="Каталог откроется в мини-приложении после публикации в MAX."
    )


# В MAX нет постоянной reply-клавиатуры (как в Telegram): чтобы навигация не
# «терялась», каждый ответ пункта меню отправляется новым сообщением со свежим
# меню (гарантированно валидная inline-клавиатура).
@dp.message_callback(F.callback.payload == CB_DISCOUNT)
async def on_discount(event: MessageCallback, context: MemoryContext) -> None:
    c = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    await event.answer()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        f"Ваша скидка: {int(c.get('total_discount', 0))}%\n"
        f"Ваш промокод для друга: {c.get('slave_code') or '—'}\n\n"
        "Приглашайте друзей — за каждого начисляется скидка (задаёт администратор).",
    )


@dp.message_callback(F.callback.payload == CB_PAYMENTS)
async def on_payments(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        "Раздел «Мои оплаты» появится после подключения платёжного шлюза.",
    )


@dp.message_callback(F.callback.payload == CB_DELIVERIES)
async def on_deliveries(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        "Раздел «Мои доставки» появится после подключения служб доставки.",
    )


@dp.message_callback(F.callback.payload == CB_HELP)
async def on_help(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        "Скоро поможем подобрать лучший вариант ✨ (в разработке).",
    )


# ── Ввод имени / материалов ────────────────────────────
@dp.message_created(OrderFlow.waiting_name)
async def on_name(event: MessageCreated, context: MemoryContext) -> None:
    data = await context.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=event.message.body.text or "")
    await context.clear()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        texts.get("msg_007а") + await _pay_line(order_id),
    )
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
        await _send_menu(event.bot, event.message.recipient.chat_id, "Выберите раздел в меню.")
        return
    await event.answer(notification="Принято ✅")
    links = await _persist_files(order_id, data.get("materials_files", []))
    await backend.update_order(
        order_id,
        materials_text=data.get("materials_text", ""),
        materials_files=links,
    )
    await context.clear()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        texts.get("msg_007б") + await _pay_line(order_id),
    )
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_007б")


@dp.message_callback(F.callback.payload == CB_MAT_REDO)
async def on_materials_redo(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.waiting_materials)
    await event.message.answer(texts.get("msg_006б"))
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
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        "Спасибо! Макет согласован — переходим к оплате."
        if approved
        else "Принято! Дизайнер доработает макет и пришлёт заново.",
    )


# Фолбэк: любое сообщение вне сценария → в меню. Регистрируется последним.
@dp.message_created(F.message.body.text)
async def on_fallback(event: MessageCreated, context: MemoryContext) -> None:
    await _send_menu(event.bot, event.message.recipient.chat_id, "Выберите раздел в меню.")
