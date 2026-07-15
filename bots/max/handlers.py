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

import re

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


async def _enter(bot, chat_id: int, user_id: int, nickname: str | None, payload: str | None,
                 context: MemoryContext) -> None:
    """Единый вход: /start, первый старт бота или возврат из мини-приложения."""
    client = await backend.upsert_client(CHANNEL, str(user_id), nickname=nickname)

    # Возврат из мини-приложения: заказ уже создан, показываем подтверждение.
    if payload and (m := _PAYLOAD_ORDER_RE.search(payload)):
        try:
            order = await backend.get_order(int(m.group(1)))
        except Exception:
            order = None
        if order:
            await context.set_state(OrderFlow.confirming)
            await context.update_data(order_id=order["id"], is_custom=order["is_custom"])
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
            return

    if not client.get("phone"):
        await context.set_state(OrderFlow.waiting_phone)
        await bot.send_message(chat_id=chat_id, text=texts.get("msg_001"))
        await bot.send_message(
            chat_id=chat_id,
            text=texts.get("msg_002") + "\n\nОтправьте номер в формате +7XXXXXXXXXX "
            "или нажмите кнопку ниже.",
            attachments=[contact_kb()],
        )
        return

    await _send_menu(
        bot, chat_id, texts.get("welcome_back", discount=int(client.get("total_discount", 0)))
    )


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
    await backend.upsert_client(
        CHANNEL, str(sender.user_id), nickname=(sender.username or sender.full_name), phone=phone
    )
    await context.clear()
    await _send_menu(event.bot, event.message.recipient.chat_id, texts.get("msg_003"))


# ── Подтверждение заказа ───────────────────────────────
@dp.message_callback(F.callback.payload == CB_CONFIRM)
async def on_confirm(event: MessageCallback, context: MemoryContext) -> None:
    data = await context.get_data()
    is_custom = data.get("is_custom", False)
    await event.answer(notification="Принято ✅")
    if is_custom:
        await context.set_state(OrderFlow.waiting_materials)
        await event.message.answer(texts.get("msg_006б"))
    else:
        await context.set_state(OrderFlow.waiting_name)
        await event.message.answer(texts.get("msg_006а"))


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
    await backend.update_order(data["order_id"], custom_text=event.message.body.text or "")
    await context.clear()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        texts.get("msg_007а") + "\n\n(ссылка на оплату — после подключения шлюза)",
    )


@dp.message_created(OrderFlow.waiting_materials)
async def on_materials(event: MessageCreated, context: MemoryContext) -> None:
    text = event.message.body.text or ""
    files: list[str] = []
    for att in event.message.body.attachments or []:
        payload = getattr(att, "payload", None)
        token = getattr(payload, "token", None) or getattr(payload, "url", None)
        if token:
            files.append(token)
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
    await backend.update_order(
        order_id,
        materials_text=data.get("materials_text", ""),
        materials_files=data.get("materials_files", []),
    )
    await context.clear()
    await _send_menu(
        event.bot,
        event.message.recipient.chat_id,
        texts.get("msg_007б") + "\n\n(ссылка на оплату — после подключения шлюза)",
    )


@dp.message_callback(F.callback.payload == CB_MAT_REDO)
async def on_materials_redo(event: MessageCallback, context: MemoryContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.waiting_materials)
    await event.message.answer(texts.get("msg_006б"))


# Фолбэк: любое сообщение вне сценария → в меню. Регистрируется последним.
@dp.message_created(F.message.body.text)
async def on_fallback(event: MessageCreated, context: MemoryContext) -> None:
    await _send_menu(event.bot, event.message.recipient.chat_id, "Выберите раздел в меню.")
