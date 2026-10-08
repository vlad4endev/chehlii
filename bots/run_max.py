"""Точка входа MAX-бота (long polling). Запуск: python -m bots.run_max (из корня репо).

Требуется MAX_BOT_TOKEN в bots/.env. Единое ядро (core/) и backend — общие с Telegram.
FSM в Redis (как у Telegram) — сценарий не теряется при рестарте.
"""

from __future__ import annotations

import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.context import RedisContext
from maxapi.enums.sender_action import SenderAction
from maxapi.enums.upload_type import UploadType
from maxapi.types.input_media import InputMediaBuffer
from redis.asyncio import from_url as redis_from_url

from bots.core import delivery, payments
from bots.core.backend import backend
from bots.core.config import settings
from bots.core.fetch_media import fetch_bytes, looks_like_image, looks_like_pdf
from bots.core.scenario import (
    STATE_CLEAR,
    STATE_CONSULTING,
    STATE_WAITING_CONTACT,
    STATE_WAITING_MATERIALS,
    STATE_WAITING_NAME,
    pending_payload,
)
from bots.core.texts import texts
from bots.max.chat_map import bind_redis, chat_for_async, known_chat_async
from bots.max.handlers import router
from bots.max.keyboards import (
    contact_kb,
    delivery_mode_kb,
    delivery_service_kb,
    delivery_start_kb,
    main_menu_kb,
    mockup_kb,
    pay_kb,
)
from bots.max.pending_fsm import PendingFsmMiddleware, apply_pending_fsm
from bots.max.states import OrderFlow

_MAX_STATE = {
    STATE_WAITING_CONTACT: OrderFlow.waiting_contact,
    STATE_WAITING_NAME: OrderFlow.waiting_name,
    STATE_WAITING_MATERIALS: OrderFlow.waiting_materials,
    STATE_CONSULTING: OrderFlow.consulting,
}


async def _fetch_media(path_or_url: str) -> bytes | None:
    return await fetch_bytes(path_or_url)


def _media_of(item: dict) -> list[dict]:
    """Список вложений рассылки. Старый одиночный photo нормализуем к списку."""
    media = list(item.get("media") or [])
    if not media and item.get("kind") == "photo" and item.get("attachment_url"):
        media = [{"url": item["attachment_url"], "type": "image"}]
    return [m for m in media[:10] if isinstance(m, dict) and m.get("url")]


async def _deliver_mockup(bot: Bot, item: dict) -> None:
    """Макет — картинка в чате с кнопками, не ссылка на Яндекс.Диск."""
    uid = int(item["channel_user_id"])
    text = item.get("text") or "Ваш макет готов."
    url = item.get("attachment_url") or ""
    kb = [mockup_kb(item["order_id"])] if item.get("order_id") else []
    data = await fetch_bytes(url)
    if data and looks_like_image(data):
        atts = [
            InputMediaBuffer(buffer=data, filename="mockup.jpg", type=UploadType.IMAGE),
            *kb,
        ]
        await bot.send_message(user_id=uid, text=text, attachments=atts)
        return
    if data:
        file_type = getattr(UploadType, "FILE", None)
        name = "mockup.pdf" if looks_like_pdf(data) else "mockup.bin"
        if file_type is not None:
            atts = [InputMediaBuffer(buffer=data, filename=name, type=file_type), *kb]
            await bot.send_message(user_id=uid, text=text, attachments=atts)
            return
    extra = f"\n\n📎 {url}" if url else ""
    await bot.send_message(
        user_id=uid, text=f"{text}{extra}", attachments=kb or None
    )


async def _scenario_attachments(bot: Bot, state: str | None) -> list:
    me = getattr(bot, "me", None) or getattr(bot, "_me", None)
    username = settings.max_bot_username or (
        getattr(me, "username", None) if me else None
    )
    bot_id = getattr(me, "user_id", None) if me else None
    if state == STATE_WAITING_CONTACT:
        return [contact_kb()]
    return [main_menu_kb(username, bot_id)]


async def _set_redis_fsm(dp: Dispatcher, item: dict) -> None:
    """Сразу выставить FSM в Redis при доставке scenario (паритет с Telegram).

    Ключ контекста — (chat_id, user_id). Если chat_id ещё неизвестен, оставляем
    pending_fsm backend'у: outer middleware применит на следующем апдейте.
    """
    pending = pending_payload(item)
    if not pending.get("state"):
        return
    uid = int(item["channel_user_id"])
    chat_id = await known_chat_async(uid)
    if chat_id is None:
        logging.debug(
            "max outbox scenario: chat_id для user %s неизвестен — FSM через middleware",
            uid,
        )
        return
    # STATE_CLEAR тоже применяем сразу.
    if pending["state"] == STATE_CLEAR or pending["state"] in _MAX_STATE:
        ctx = dp.fsm.get_context(chat_id=chat_id, user_id=uid)
        await apply_pending_fsm(ctx, pending)


async def _deliver_scenario(bot: Bot, dp: Dispatcher, item: dict) -> None:
    uid = int(item["channel_user_id"])
    pending = pending_payload(item)
    text = item.get("text") or "Новое сообщение"
    atts = await _scenario_attachments(bot, pending.get("state"))
    await bot.send_message(user_id=uid, text=text, attachments=atts)
    await _set_redis_fsm(dp, item)


async def _deliver(bot: Bot, dp: Dispatcher, item: dict) -> None:
    text = item.get("text") or ""
    kind = item.get("kind")
    uid = int(item["channel_user_id"])
    if kind == "typing":
        # channel_user_id = user_id; send_action нужен chat_id диалога.
        await bot.send_action(
            chat_id=await chat_for_async(uid), action=SenderAction.TYPING_ON
        )
        return
    if kind == "mockup":
        await _deliver_mockup(bot, item)
        return
    if kind == "scenario":
        await _deliver_scenario(bot, dp, item)
        return
    if kind == "pay" and item.get("order_id"):
        b = await payments.block(int(item["order_id"]), payments.pay_kind_of(item))
        body = f"{text}\n\n{b.text}".strip() if text else b.text
        atts = [pay_kb(b.buttons)] if b.buttons else None
        await bot.send_message(user_id=uid, text=body or "Оплата", attachments=atts)
        return

    # Рассылка с медиа → одно сообщение с несколькими вложениями (фото/видео).
    media = _media_of(item)
    if media:
        atts = []
        for i, mm in enumerate(media):
            data = await _fetch_media(mm.get("url", ""))
            if data:
                t = mm.get("type")
                if t in ("video", "video_note"):
                    utype = UploadType.VIDEO
                elif t == "audio":
                    utype = getattr(UploadType, "AUDIO", None) or getattr(
                        UploadType, "FILE", UploadType.IMAGE
                    )
                elif t == "file":
                    utype = getattr(UploadType, "FILE", UploadType.IMAGE)
                else:
                    utype = UploadType.IMAGE
                atts.append(InputMediaBuffer(buffer=data, filename=f"m{i}", type=utype))
        if atts:
            await bot.send_message(user_id=uid, text=(text or None), attachments=atts)
            return

    atts2 = None
    if kind == "delivery" and item.get("order_id"):
        oid = item["order_id"]
        services = await delivery.configured_services()
        if not services:
            atts2 = [delivery_start_kb(oid)]
        elif len(services) > 1:
            atts2 = [delivery_service_kb(oid, services)]
        else:
            atts2 = [delivery_mode_kb(oid, services[0])]
        # Прогрев FSM: иначе callback dlv:pvz/door не знает службу.
        chat_id = await known_chat_async(uid)
        if chat_id is not None:
            ctx = dp.fsm.get_context(chat_id=chat_id, user_id=uid)
            await ctx.set_state(OrderFlow.delivery_mode)
            data = {"order_id": oid, "delivery_mode": None, "delivery_points": []}
            if len(services) == 1:
                data["delivery_service"] = services[0]
            await ctx.update_data(**data)
    await bot.send_message(user_id=uid, text=text or "Новое сообщение", attachments=atts2)


# Ошибки, после которых повтор бесполезен — иначе яд блокирует outbox.
_OUTBOX_DROP = (
    "chat not found",
    "user is deactivated",
    "bot was blocked",
    "peer_id_invalid",
    "chat_id is empty",
)


def _outbox_drop(item: dict, err: BaseException) -> bool:
    uid = str(item.get("channel_user_id") or "")
    if uid in ("", "0"):
        return True
    low = str(err).lower()
    return any(p in low for p in _OUTBOX_DROP)


async def _outbox_loop(bot: Bot, dp: Dispatcher) -> None:
    """Забирает исходящие сообщения из backend и доставляет клиентам в MAX."""
    while True:
        try:
            for item in await backend.get_outbox("max"):
                try:
                    await _deliver(bot, dp, item)
                    await backend.mark_outbox_sent(item["id"])
                except Exception as e:  # noqa: BLE001
                    if _outbox_drop(item, e):
                        logging.warning("outbox max: отброшено (постоянная ошибка): %s", e)
                        try:
                            await backend.mark_outbox_sent(item["id"])
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        logging.warning("outbox max: доставка не удалась: %s", e)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1.5)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.max_bot_token:
        raise SystemExit(
            "MAX_BOT_TOKEN не задан в bots/.env — получите токен MAX-бота у @MasterBot."
        )

    await texts.load()
    redis = redis_from_url(settings.redis_url)
    bind_redis(redis)
    # Отдельный prefix, чтобы не пересекаться с aiogram FSM на том же Redis DB.
    dp = Dispatcher(
        storage=RedisContext,
        redis_client=redis,
        key_prefix="maxbot",
    )
    dp.include_routers(router)
    dp.register_outer_middleware(PendingFsmMiddleware())

    bot = Bot(settings.max_bot_token)
    outbox = asyncio.create_task(_outbox_loop(bot, dp))
    try:
        await dp.start_polling(bot)
    finally:
        outbox.cancel()
        await backend.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
