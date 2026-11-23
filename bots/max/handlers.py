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
from maxapi.filters.state import StateFilter
from maxapi.types import (
    BotStarted,
    Command,
    CommandStart,
    MessageCallback,
    MessageCreated,
)
from maxapi.enums.upload_type import UploadType
from maxapi.types.input_media import InputMediaBuffer

from bots.core import consult, delivery, payments, review
from bots.core.backend import backend
from bots.core.config import settings
from bots.core.fetch_media import fetch_bytes
from bots.core.phone import format_phone, is_russian_mobile, normalize_any_phone
from bots.core.texts import texts
from bots.max.chat_map import remember_async
from bots.max.keyboards import (
    CB_CANCEL,
    CB_CATALOG,
    CB_CONFIRM,
    CB_DELIVERIES,
    CB_DISCOUNT,
    CB_HELP,
    CB_HUMAN,
    CB_MAT_CONFIRM,
    CB_MAT_EDIT_DESC,
    CB_MAT_EDIT_FILES,
    CB_MAT_FILES_DONE,
    CB_MAT_REDO,
    CB_MAT_SKIP_DESC,
    CB_PAYMENTS,
    CB_PHONE_MANUAL,
    CB_PHONE_OK,
    CB_PHONE_RETRY,
    confirm_kb,
    contact_kb,
    phone_confirm_kb,
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
    pick_order_kb,
)
from bots.max.states import OrderFlow

router = Router()
CHANNEL = "max"

_PAYLOAD_ORDER_RE = re.compile(r"order[_-](\d+)")

# Состояния, где свободный текст — не ввод сценария (переслать менеджеру).
# tuple: State в maxapi нехешируемый, set падает при импорте.
_OFFSCRIPT_STATES = (
    OrderFlow.confirming,
    OrderFlow.confirming_materials,
    OrderFlow.delivery_mode,
    OrderFlow.delivery_pvz,
    OrderFlow.waiting_contact,
)


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


async def _offer_order_pick(
    bot, chat_id: int, context: BaseContext, *, hint: str | None = None
) -> bool:
    """Если заказов > 1 — спросить «К какому?» и показать кнопки. True = показали."""
    data = await context.get_data()
    ids = _parallel_order_ids(data)
    if len(ids) < 2:
        return False
    text = hint or "К какому заказу относится сообщение? Выберите кнопкой:"
    await bot.send_message(chat_id=chat_id, text=text, attachments=[pick_order_kb(ids)])
    return True


def _order_prefix(order_id: int | str | None) -> str:
    if not order_id:
        return ""
    return f"Заказ #{order_id}: "


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


async def _send_pay(
    bot,
    chat_id: int,
    order_id: int,
    code: str,
    event: MessageCallback | None = None,
    *,
    order_label: bool = False,
) -> None:
    b = await payments.block(order_id)
    prefix = _order_prefix(order_id) if order_label else ""
    text = f"{prefix}{texts.get(code)}\n\n{b.text}"
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
            + "\n\nНажмите «Поделиться контактом» или введите номер вручную (с кодом страны)."
        ),
        attachments=[contact_kb()],
    )
    await backend.mark_journey(client_id, "msg_002")


async def _show_order_confirm(bot, chat_id: int, order_id: int, client_id: int, context: BaseContext) -> None:
    """Показать подтверждение заказа. Предыдущий незавершённый сценарий
    сохраняем в paused_orders — клиент может вести несколько заказов параллельно."""
    try:
        order = await backend.get_order(order_id)
    except Exception:
        order = None
    if not order:
        await _send_menu(bot, chat_id, "Не нашли заказ. Откройте каталог и выберите снова.")
        return
    data = await context.get_data()
    paused = list(data.get("paused_orders") or [])
    prev_id = data.get("order_id")
    prev_state = await context.get_state()
    if (
        prev_id
        and prev_state
        and prev_state != str(OrderFlow.consulting)
        and int(prev_id) != int(order["id"])
    ):
        paused.append(
            {
                "order_id": prev_id,
                "is_custom": data.get("is_custom"),
                "fsm": prev_state,
                "materials_text": data.get("materials_text"),
                "materials_files": data.get("materials_files"),
            }
        )
    await context.set_state(OrderFlow.confirming)
    await context.update_data(
        order_id=order["id"],
        is_custom=order["is_custom"],
        pending_order_id=None,
        paused_orders=paused,
        materials_text="",
        materials_files=[],
    )
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{_order_prefix(order['id'])}"
            + texts.get(
                "msg_005аб",
                type=order["case_name"],
                model=order["model_name"],
                price=_fmt_price(order["client_price"]),
            )
        ),
        attachments=[confirm_kb()],
    )
    await backend.mark_journey(client_id, "msg_005аб")
    if paused:
        await bot.send_message(
            chat_id=chat_id,
            text="Предыдущий заказ на паузе. Чтобы вернуться к нему — нажмите кнопку:",
            attachments=[pick_order_kb(_parallel_order_ids(await context.get_data()))],
        )


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
    await _send_start_media(bot, chat_id, code, greeting)
    await backend.mark_journey(client["id"], code)


async def _send_start_media(bot, chat_id: int, code: str, greeting: str) -> None:
    """В MAX кружков нет — шлём обычное видео; при ошибке только текст (не ломаем /start)."""
    meta = texts.meta(code)
    fmt = (meta.get("media_format") or "text").strip()
    url = meta.get("media_url")
    if fmt in ("video_note", "video_note_text") and url:
        try:
            data = await fetch_bytes(url)
            if data:
                username, bot_id = _bot_identity(bot)
                follow = (
                    greeting
                    if fmt == "video_note_text"
                    else (texts.get("msg_001_hint") or greeting)
                )
                await bot.send_message(
                    chat_id=chat_id,
                    text=follow,
                    attachments=[
                        InputMediaBuffer(buffer=data, filename="start.mp4", type=UploadType.VIDEO),
                        main_menu_kb(username, bot_id),
                    ],
                )
                return
        except Exception:  # noqa: BLE001
            logging.warning("max: не удалось отправить видео %s", code, exc_info=True)
    await _send_menu(bot, chat_id, greeting)


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
            phone = normalize_any_phone(tel, trusted_digits=True)
            if phone:
                return phone
        raw = getattr(payload, "vcf_info", None)
        if not raw:
            continue
        for line in str(raw).replace("\r\n", "\n").split("\n"):
            if not line.upper().startswith("TEL"):
                continue
            _, _, value = line.partition(":")
            phone = normalize_any_phone(value.strip(), trusted_digits=True)
            if phone:
                return phone
    return None



_PHONE_FORMAT_HINT = "Пришлите номер с кодом страны, например +79001234567 или +380501234567."
_DELIVERY_RU_PHONE_TEXT = (
    "Для доставки по России нужен российский мобильный получателя (+79XXXXXXXXX). "
    "Нажмите «Ввести другой номер» или пришлите номер."
)


async def _complete_phone(bot, chat_id: int, user, context: BaseContext, phone: str) -> None:
    """Сохранить телефон и продолжить прерванный сценарий (заказ/доставка/меню)."""
    client = await backend.upsert_client(
        CHANNEL,
        str(user.user_id),
        nickname=(getattr(user, "username", None) or getattr(user, "full_name", None)),
        phone=phone,
    )
    # Контакт получен на моменте заказа → сразу показываем подтверждение заказа.
    data = await context.get_data()
    pending = data.get("pending_order_id")
    if pending:
        await _show_order_confirm(bot, chat_id, int(pending), client["id"], context)
        return
    pending_delivery = data.get("pending_delivery_order_id")
    if pending_delivery:
        if not is_russian_mobile(phone):
            # Контактный номер мог быть иностранным, но службы доставки принимают
            # только российский мобильный получателя.
            await bot.send_message(chat_id=chat_id, text=_DELIVERY_RU_PHONE_TEXT, attachments=[contact_kb()])
            return
        await _start_delivery(bot, chat_id, int(pending_delivery), context, phone=phone)
        return
    await context.clear()
    await _send_menu(bot, chat_id, texts.get("msg_003"))
    await backend.mark_journey(client["id"], "msg_003")


@router.message_created(OrderFlow.waiting_contact)
async def on_phone(event: MessageCreated, context: BaseContext) -> None:
    """Контакт (vCard) принимаем сразу, текстовый номер — через подтверждение."""
    sender = event.message.sender
    chat_id = event.message.recipient.chat_id
    phone = _extract_contact_phone(event)
    if phone:
        await _complete_phone(event.bot, chat_id, sender, context, phone)
        return
    phone = normalize_any_phone(event.message.body.text or "")
    if not phone:
        await event.message.answer(
            f"Не разобрал номер. {_PHONE_FORMAT_HINT}",
            attachments=[contact_kb()],
        )
        return
    await context.update_data(pending_phone=phone)
    await event.message.answer(
        f"Ваш номер {format_phone(phone)}. Всё верно?", attachments=[phone_confirm_kb()]
    )


@router.message_callback(F.callback.payload == CB_PHONE_OK)
async def on_phone_confirmed(event: MessageCallback, context: BaseContext) -> None:
    data = await context.get_data()
    phone = data.get("pending_phone")
    await event.answer()
    chat_id = event.message.recipient.chat_id
    if not phone:
        await event.bot.send_message(
            chat_id=chat_id, text=f"Введите номер ещё раз. {_PHONE_FORMAT_HINT}"
        )
        return
    await context.update_data(pending_phone=None)
    await _complete_phone(event.bot, chat_id, event.callback.user, context, phone)


@router.message_callback(F.callback.payload.in_({CB_PHONE_RETRY, CB_PHONE_MANUAL}))
async def on_phone_retry(event: MessageCallback, context: BaseContext) -> None:
    await context.update_data(pending_phone=None)
    await event.answer()
    await event.bot.send_message(
        chat_id=event.message.recipient.chat_id,
        text=f"Введите номер телефона. {_PHONE_FORMAT_HINT}",
    )


# ── Подтверждение заказа ───────────────────────────────
@router.message_callback(F.callback.payload == CB_CONFIRM)
async def on_confirm(event: MessageCallback, context: BaseContext) -> None:
    data = await context.get_data()
    order_id = data.get("order_id")
    # is_custom берём из заказа, а не только из FSM: после рестарта
    # контекст мог быть пуст → иначе кастом уходит без материалов.
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
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    if is_custom:
        await context.set_state(OrderFlow.waiting_materials)
        await context.update_data(materials_text="", materials_files=[])
        code = "msg_006б"
        await _replace(
            event,
            f"{_order_prefix(order_id)}{texts.get(code)}",
            [materials_files_done_kb()],
        )
        await backend.mark_journey(client["id"], code)
        return
    # Стандарт: без имени/буквы, сразу полная оплата (100%).
    await context.clear()
    code = "msg_007а"
    await _send_pay(
        event.bot, event.message.recipient.chat_id, int(order_id), code, event=event, order_label=True
    )
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


@router.message_callback(F.callback.payload == CB_DISCOUNT)
async def on_discount(event: MessageCallback, context: BaseContext) -> None:
    c = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    await event.answer()
    await _replace_menu(event, _discount_text(c))
    if not c.get("master_code"):
        await context.set_state(OrderFlow.entering_promo)


@router.message_created(OrderFlow.entering_promo)
async def on_promo_code(event: MessageCreated, context: BaseContext) -> None:
    text = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id
    if not text:
        await _send_menu(event.bot, chat_id, "Пришлите промокод друга текстом.")
        return
    c = await backend.upsert_client(
        CHANNEL, str(event.message.sender.user_id),
        nickname=event.message.sender.username or event.message.sender.full_name,
    )
    try:
        res = await backend.activate_promo(c["id"], text)
    except ValueError as e:
        await _send_menu(event.bot, chat_id, str(e) or "Не удалось активировать код.")
        return
    except Exception:  # noqa: BLE001
        logging.warning("max: promo activate failed", exc_info=True)
        await _send_menu(event.bot, chat_id, "Не удалось активировать код. Попробуйте позже.")
        return
    await context.clear()
    await _send_menu(
        event.bot,
        chat_id,
        f"Промокод активирован! Скидка по коду друга: {int(res.get('discount_master_code', 0))}%. "
        f"Итого: {int(res.get('total_discount', 0))}%.",
    )


@router.message_callback(F.callback.payload == CB_PAYMENTS)
async def on_payments(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    client = await backend.upsert_client(CHANNEL, str(event.callback.user.user_id))
    try:
        orders = await backend.client_orders(client["id"])
    except Exception:  # noqa: BLE001
        orders = []
    if not orders:
        await _replace_menu(event, "Пока нет заказов.")
        return
    lines = ["Ваши заказы и оплаты:\n"]
    for o in orders[:20]:
        price = o.get("final_price") or o.get("client_price") or "—"
        pay = o.get("payment_status") or "—"
        lines.append(
            f"#{o['id']} · {o.get('status_label') or o.get('status')} · {price} · оплата: {pay}"
        )
    await _replace_menu(event, "\n".join(lines))


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


async def _call_human(
    bot,
    chat_id: int,
    user_id: int,
    nickname: str | None,
    context: BaseContext,
    *,
    event: MessageCallback | None = None,
) -> None:
    """Позвать менеджера, не сбрасывая шаг оформления заказа."""
    client = await backend.upsert_client(CHANNEL, str(user_id), nickname=nickname)
    current = await context.get_state()
    if current is None:
        await context.set_state(OrderFlow.consulting)
    try:
        await consult.ingest(client["id"], "[Клиент нажал «Позвать человека»]", [])
    except Exception as e:  # noqa: BLE001
        logging.warning("call human failed: %s", e)
    await backend.mark_journey(client["id"], "msg_help")
    if event is not None:
        await _replace_menu(event, texts.get("msg_help"))
        return
    await _send_menu(bot, chat_id, texts.get("msg_help"))


@router.message_callback(F.callback.payload.in_({CB_HELP, CB_HUMAN}))
async def on_help(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    u = event.callback.user
    await _call_human(
        event.bot,
        event.message.recipient.chat_id,
        u.user_id,
        u.username,
        context,
        event=event,
    )


@router.message_created(Command("human"))
async def on_human_cmd(event: MessageCreated, context: BaseContext) -> None:
    s = event.message.sender
    await remember_async(s.user_id, event.message.recipient.chat_id)
    await _call_human(
        event.bot,
        event.message.recipient.chat_id,
        s.user_id,
        s.username or s.full_name,
        context,
    )


# ── Ввод имени / материалов ────────────────────────────
@router.message_created(OrderFlow.waiting_name)
async def on_name(event: MessageCreated, context: BaseContext) -> None:
    """Устарело: стандарт больше не спрашивает имя — на всякий случай ведём к оплате."""
    data = await context.get_data()
    order_id = data["order_id"]
    await backend.update_order(order_id, custom_text=event.message.body.text or "")
    await context.clear()
    await _send_pay(
        event.bot, event.message.recipient.chat_id, order_id, "msg_007а", order_label=True
    )
    s = event.message.sender
    client = await backend.upsert_client(CHANNEL, str(s.user_id), nickname=(s.username or s.full_name))
    await backend.mark_journey(client["id"], "msg_007а")


def _collect_material_urls(event: MessageCreated) -> list[str]:
    files: list[str] = []
    for att in event.message.body.attachments or []:
        payload = getattr(att, "payload", None)
        url = getattr(payload, "url", None)
        if url:
            files.append(url)
    return files


async def _show_materials_summary(event: MessageCreated, context: BaseContext) -> None:
    data = await context.get_data()
    order_id = data.get("order_id")
    desc = (data.get("materials_text") or "").strip() or "—"
    n = len(data.get("materials_files") or [])
    await context.set_state(OrderFlow.confirming_materials)
    body = texts.get("msg_006б_summary", desc=desc, files=n)
    await event.message.answer(
        f"{_order_prefix(order_id)}{body}\n\n"
        "Всё верно? После подтверждения внесёте предоплату — дизайнер пришлёт макет.",
        attachments=[materials_confirm_kb()],
    )


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
    """Шаг 1: только файлы. Подпись к фото → сразу в описание, шаг 2 пропускаем."""
    data = await context.get_data()
    existing: list[str] = list(data.get("materials_files") or [])
    new_files = _collect_material_urls(event)
    text = (event.message.body.text or "").strip()
    # Чистый текст без файлов на шаге фото — вне сценария → менеджеру.
    if not new_files and text:
        await _relay_offscript(event, context)
        return
    if not new_files:
        await event.message.answer(
            "Пришлите фото или файлы, затем нажмите «Готово, дальше».",
            attachments=[materials_files_done_kb()],
        )
        return
    existing.extend(new_files)
    updates: dict = {"materials_files": existing}
    # Текст вместе с файлами считаем подписью → описание.
    if text:
        updates["materials_text"] = text
    await context.update_data(**updates)
    if text:
        await _show_materials_summary(event, context)
        return
    await event.message.answer(
        f"Добавлено вложений: {len(existing)}. Можно прислать ещё или нажать «Готово, дальше».",
        attachments=[materials_files_done_kb()],
    )


@router.message_callback(F.callback.payload == CB_MAT_FILES_DONE)
async def on_materials_files_done(event: MessageCallback, context: BaseContext) -> None:
    data = await context.get_data()
    files = data.get("materials_files") or []
    if not files:
        await event.answer(notification="Сначала пришлите хотя бы одно фото или файл")
        return
    if (data.get("materials_text") or "").strip():
        # Сводку шлём новым сообщением (как TG edit → answer).
        await event.answer()
        chat_id = event.message.recipient.chat_id
        # Переиспользуем MessageCreated-путь через прямую отправку.
        desc = (data.get("materials_text") or "").strip() or "—"
        n = len(files)
        await context.set_state(OrderFlow.confirming_materials)
        body = texts.get("msg_006б_summary", desc=desc, files=n)
        await _replace(
            event,
            f"{_order_prefix(data.get('order_id'))}{body}\n\n"
            "Всё верно? После подтверждения внесёте предоплату — дизайнер пришлёт макет.",
            [materials_confirm_kb()],
        )
        return
    await context.set_state(OrderFlow.waiting_materials_desc)
    await event.answer()
    await _replace(
        event,
        f"{_order_prefix(data.get('order_id'))}{texts.get('msg_006б_desc')}",
        [materials_skip_desc_kb()],
    )


@router.message_created(OrderFlow.waiting_materials_desc)
async def on_materials_desc(event: MessageCreated, context: BaseContext) -> None:
    new_files = _collect_material_urls(event)
    data = await context.get_data()
    if new_files:
        files = list(data.get("materials_files") or [])
        files.extend(new_files)
        await context.update_data(materials_files=files)
        await event.message.answer(
            f"Фото добавлено (всего {len(files)}). Теперь опишите пожелание или нажмите «Без описания».",
            attachments=[materials_skip_desc_kb()],
        )
        return
    text = (event.message.body.text or "").strip()
    if not text:
        await event.message.answer(
            texts.get("msg_006б_desc"),
            attachments=[materials_skip_desc_kb()],
        )
        return
    await context.update_data(materials_text=text)
    await _show_materials_summary(event, context)


@router.message_callback(F.callback.payload == CB_MAT_SKIP_DESC)
async def on_materials_skip_desc(event: MessageCallback, context: BaseContext) -> None:
    await context.update_data(materials_text="")
    await event.answer()
    data = await context.get_data()
    desc = "—"
    n = len(data.get("materials_files") or [])
    await context.set_state(OrderFlow.confirming_materials)
    body = texts.get("msg_006б_summary", desc=desc, files=n)
    await _replace(
        event,
        f"{_order_prefix(data.get('order_id'))}{body}\n\n"
        "Всё верно? После подтверждения внесёте предоплату — дизайнер пришлёт макет.",
        [materials_confirm_kb()],
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
    await _send_pay(
        event.bot,
        event.message.recipient.chat_id,
        order_id,
        "msg_007б",
        event=event,
        order_label=True,
    )
    u = event.callback.user
    client = await backend.upsert_client(CHANNEL, str(u.user_id), nickname=u.username)
    await backend.mark_journey(client["id"], "msg_007б")


@router.message_callback(F.callback.payload == CB_MAT_EDIT_FILES)
async def on_materials_edit_files(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(materials_files=[])
    await context.set_state(OrderFlow.waiting_materials)
    data = await context.get_data()
    await _replace(
        event,
        f"{_order_prefix(data.get('order_id'))}{texts.get('msg_006б')}",
        [materials_files_done_kb()],
    )


@router.message_callback(F.callback.payload == CB_MAT_EDIT_DESC)
async def on_materials_edit_desc(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.set_state(OrderFlow.waiting_materials_desc)
    data = await context.get_data()
    await _replace(
        event,
        f"{_order_prefix(data.get('order_id'))}{texts.get('msg_006б_desc')}",
        [materials_skip_desc_kb()],
    )


@router.message_callback(F.callback.payload == CB_MAT_REDO)
async def on_materials_redo(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(materials_text="", materials_files=[])
    await context.set_state(OrderFlow.waiting_materials)
    data = await context.get_data()
    await _replace(
        event,
        f"{_order_prefix(data.get('order_id'))}{texts.get('msg_006б')}",
        [materials_files_done_kb()],
    )


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
    phone = client.get("phone")
    if not is_russian_mobile(phone):
        await context.set_state(OrderFlow.waiting_contact)
        await context.update_data(pending_delivery_order_id=order_id)
        await event.answer()
        await _replace(
            event,
            _DELIVERY_RU_PHONE_TEXT,
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
    event: MessageCreated,
    client: dict,
    context: BaseContext | None = None,
    *,
    force_consulting: bool = True,
    ack: bool = False,
) -> bool:
    """Сохранить в переписку. True если удалось. Не ломает текущий шаг, если force_consulting=False."""
    if await _relay_review(event, client, context):
        return True
    text = event.message.body.text or ""
    try:
        ok = await consult.ingest(client["id"], text, await _consult_files_max(event))
    except Exception as e:  # noqa: BLE001
        logging.warning(
            "consult send failed client=%s: %s", client.get("id"), e, exc_info=True
        )
        await event.message.answer("Не получилось передать сообщение, попробуйте ещё раз.")
        return False
    if not ok:
        await event.message.answer("Напишите текст или пришлите фото — передадим администратору.")
        return False
    if context is not None and force_consulting:
        current = await context.get_state()
        if current is None:
            await context.set_state(OrderFlow.consulting)
    if ack:
        await event.message.answer(texts.get("msg_offscript") or texts.get("msg_help_ack"))
    return True


async def _relay_offscript(event: MessageCreated, context: BaseContext) -> None:
    """Неожиданное сообщение на шаге сценария → менеджеру, кнопки шага остаются."""
    s = event.message.sender
    await remember_async(s.user_id, event.message.recipient.chat_id)
    client = await backend.upsert_client(
        CHANNEL, str(s.user_id), nickname=(s.username or s.full_name)
    )
    data = await context.get_data()
    order_id = data.get("order_id")
    step = await context.get_state()
    raw = (event.message.body.text or "").strip()
    logging.info(
        "offscript client=%s step=%s order=%s text=%r",
        client.get("id"),
        step,
        order_id,
        raw[:80],
    )
    if await _relay_review(event, client, context):
        return
    tagged = f"[Заказ #{order_id}] {raw}".strip() if order_id else raw
    # Подменяем текст для ingest: передаём через временный атрибут не получится —
    # пишем напрямую с тегом заказа.
    try:
        files = await _consult_files_max(event)
        ok = await consult.ingest(client["id"], tagged or None, files)
    except Exception as e:  # noqa: BLE001
        logging.warning("offscript consult failed: %s", e, exc_info=True)
        await event.message.answer("Не получилось передать сообщение, попробуйте ещё раз.")
        return
    if ok:
        await event.message.answer(texts.get("msg_offscript") or texts.get("msg_help_ack"))
    else:
        await event.message.answer("Напишите текст или пришлите фото — передадим администратору.")
    await _offer_order_pick(event.bot, event.message.recipient.chat_id, context)


@router.message_callback(F.callback.payload.startswith("order:pick:"))
async def on_pick_order(event: MessageCallback, context: BaseContext) -> None:
    """Выбор заказа при нескольких параллельных сценариях (паритет TG)."""
    payload = event.callback.payload or ""
    try:
        oid = int(payload.split(":")[-1])
    except ValueError:
        await event.answer(notification="Ошибка")
        return
    data = await context.get_data()
    paused = list(data.get("paused_orders") or [])
    chosen = None
    rest = []
    for p in paused:
        if int(p.get("order_id") or 0) == oid:
            chosen = p
        else:
            rest.append(p)
    if chosen is None and int(data.get("order_id") or 0) == oid:
        await event.answer(notification="Уже работаем с этим заказом")
        return
    if chosen is None:
        await event.answer(notification="Заказ не найден в сессии")
        return
    cur = {
        "order_id": data.get("order_id"),
        "is_custom": data.get("is_custom"),
        "fsm": await context.get_state(),
        "materials_text": data.get("materials_text"),
        "materials_files": data.get("materials_files"),
    }
    if cur["order_id"]:
        rest.append(cur)
    restore_fsm = chosen.get("fsm") or str(OrderFlow.confirming)
    await context.set_state(restore_fsm)
    await context.update_data(
        order_id=chosen["order_id"],
        is_custom=chosen.get("is_custom"),
        materials_text=chosen.get("materials_text") or "",
        materials_files=chosen.get("materials_files") or [],
        paused_orders=rest,
    )
    await event.answer(notification=f"Заказ #{oid}")
    await event.bot.send_message(
        chat_id=event.message.recipient.chat_id,
        text=f"Продолжаем заказ #{oid}. Пришлите то, что бот просил на этом шаге.",
        attachments=[main_menu_kb()],
    )


@router.message_created(OrderFlow.consulting)
async def on_consult(event: MessageCreated, context: BaseContext) -> None:
    s = event.message.sender
    await remember_async(s.user_id, event.message.recipient.chat_id)
    client = await backend.upsert_client(
        CHANNEL, str(s.user_id), nickname=(s.username or s.full_name)
    )
    await _relay_consult(event, client, context, ack=False)


# Неожиданный ввод на шагах, где ждут кнопку (не текст).
@router.message_created(StateFilter(*_OFFSCRIPT_STATES))
async def on_offscript_busy(event: MessageCreated, context: BaseContext) -> None:
    # confirming + кастом: on_early_content обычно перехватывает раньше;
    # здесь — запасной путь, если специфичный хендлер не сработал.
    data = await context.get_data()
    current = await context.get_state()
    if current == str(OrderFlow.confirming) and bool(data.get("is_custom")):
        if _collect_material_urls(event):
            await context.set_state(OrderFlow.waiting_materials)
            await on_materials(event, context)
            return
    await _relay_offscript(event, context)


# Фолбэк: отзыв (если заказ ждёт) или свободный текст/фото → админу.
# Регистрируется последним. Busy-состояния обрабатывает on_offscript_busy /
# точечные хендлеры — здесь не дропаем сообщения.
@router.message_created()
async def on_fallback(event: MessageCreated, context: BaseContext) -> None:
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
    # Состояния с собственными хендлерами (материалы, доставка city/address, promo…)
    # сюда не должны попадать. Если всё же попали — offscript без сброса FSM.
    current = await context.get_state()
    if current is not None:
        await _relay_offscript(event, context)
        return
    if not await consult.allowed_to_write(client):
        await _send_menu(
            event.bot,
            event.message.recipient.chat_id,
            "Выберите раздел в меню или нажмите «Позвать человека».",
        )
        return
    await _relay_consult(event, client, context)
