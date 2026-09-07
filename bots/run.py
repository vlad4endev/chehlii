"""Точка входа Telegram-бота (long polling). Запуск: python -m bots.run (из корня репо)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo, LinkPreviewOptions

from bots.core import delivery
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
from bots.tg.handlers import router
from bots.tg.keyboards import (
    contact_kb,
    delivery_mode_kb,
    delivery_service_kb,
    delivery_start_kb,
    main_menu_kb,
    mockup_kb,
)
from bots.tg.pending_fsm import PendingFsmMiddleware
from bots.tg.states import OrderFlow


async def _fetch_media(path_or_url: str) -> bytes | None:
    return await fetch_bytes(path_or_url)


def _media_of(item: dict) -> list[dict]:
    """Список вложений рассылки. Старый одиночный photo нормализуем к списку."""
    media = list(item.get("media") or [])
    if not media and item.get("kind") == "photo" and item.get("attachment_url"):
        media = [{"url": item["attachment_url"], "type": "image"}]
    # meta scenario без url — не медиа для альбома
    return [m for m in media[:10] if isinstance(m, dict) and m.get("url")]


async def _deliver_mockup(bot: Bot, item: dict) -> None:
    """Макет — фото в чате с кнопками, не карточка Яндекс.Диска."""
    chat_id = int(item["channel_user_id"])
    text = item.get("text") or "Ваш макет готов."
    url = item.get("attachment_url") or ""
    kb = mockup_kb(item["order_id"]) if item.get("order_id") else None
    data = await fetch_bytes(url)
    caption = text[:1024]
    if data and looks_like_image(data):
        name = "mockup.png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "mockup.jpg"
        await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(data, name),
            caption=caption,
            reply_markup=kb,
        )
        return
    if data:
        name = "mockup.pdf" if looks_like_pdf(data) else "mockup.bin"
        await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(data, name),
            caption=caption,
            reply_markup=kb,
        )
        return
    extra = f"\n\n📎 {url}" if url else ""
    await bot.send_message(
        chat_id=chat_id,
        text=f"{text}{extra}",
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


_TG_STATE = {
    STATE_WAITING_CONTACT: OrderFlow.waiting_contact,
    STATE_WAITING_NAME: OrderFlow.waiting_name,
    STATE_WAITING_MATERIALS: OrderFlow.waiting_materials,
    STATE_CONSULTING: OrderFlow.consulting,
}


async def _set_redis_fsm(bot: Bot, storage: RedisStorage, item: dict) -> None:
    """Сразу выставить FSM в Redis при доставке scenario (не ждать следующего апдейта)."""
    pending = pending_payload(item)
    if not pending.get("state"):
        return
    chat_id = int(item["channel_user_id"])
    key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
    name = pending["state"]
    if name == STATE_CLEAR:
        await storage.set_state(key, None)
        await storage.set_data(key, {})
        return
    mapped = _TG_STATE.get(name)
    if mapped is None:
        return
    await storage.set_state(key, mapped)
    data: dict = {}
    if pending.get("order_id") is not None:
        data["order_id"] = pending["order_id"]
    await storage.set_data(key, data)


def _scenario_kb(state: str | None):
    if state == STATE_WAITING_CONTACT:
        return contact_kb()
    return main_menu_kb()


async def _deliver_scenario(bot: Bot, storage: RedisStorage | None, item: dict) -> None:
    chat_id = int(item["channel_user_id"])
    pending = pending_payload(item)
    text = item.get("text") or "Новое сообщение"
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_scenario_kb(pending.get("state")),
    )
    if storage is not None:
        await _set_redis_fsm(bot, storage, item)


async def _deliver(bot: Bot, item: dict, storage: RedisStorage | None = None) -> None:
    text = item.get("text") or ""
    kind = item.get("kind")
    chat_id = int(item["channel_user_id"])
    if kind == "mockup":
        await _deliver_mockup(bot, item)
        return
    if kind == "scenario":
        await _deliver_scenario(bot, storage, item)
        return

    # Рассылка с медиа: фото/видео — альбомом; кружки (video note) — отдельно.
    media = _media_of(item)
    if media:
        notes = [m for m in media if m.get("type") == "video_note"]
        rest = [m for m in media if m.get("type") in ("image", "video")]
        extras = [m for m in media if m.get("type") in ("audio", "file")]
        sent_any = False
        text_sent = False

        files = []
        for i, mm in enumerate(rest):
            data = await _fetch_media(mm.get("url", ""))
            if data:
                files.append((mm.get("type"), BufferedInputFile(data, f"m{i}")))
        if files:
            caption = text if 0 < len(text) <= 1024 else None
            if len(files) == 1:
                mtype, f = files[0]
                if mtype == "video":
                    await bot.send_video(chat_id=chat_id, video=f, caption=caption)
                else:
                    await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
            else:
                group = [
                    InputMediaVideo(media=f, caption=(caption if idx == 0 else None))
                    if mtype == "video"
                    else InputMediaPhoto(media=f, caption=(caption if idx == 0 else None))
                    for idx, (mtype, f) in enumerate(files)
                ]
                await bot.send_media_group(chat_id=chat_id, media=group)
            sent_any = True
            if caption:
                text_sent = True

        for i, mm in enumerate(notes):
            data = await _fetch_media(mm.get("url", ""))
            if data:
                await bot.send_video_note(
                    chat_id=chat_id, video_note=BufferedInputFile(data, f"n{i}.mp4")
                )
                sent_any = True

        for i, mm in enumerate(extras):
            data = await _fetch_media(mm.get("url", ""))
            if not data:
                continue
            name = mm.get("name") or ("voice.ogg" if mm.get("type") == "audio" else f"file_{i}")
            buf = BufferedInputFile(data, name)
            cap = text if not text_sent and 0 < len(text) <= 1024 else None
            if mm.get("type") == "audio":
                await bot.send_voice(chat_id=chat_id, voice=buf, caption=cap)
            else:
                await bot.send_document(chat_id=chat_id, document=buf, caption=cap)
            sent_any = True
            if cap:
                text_sent = True

        if sent_any:
            if text and not text_sent:
                await bot.send_message(chat_id=chat_id, text=text)
            return

    kb = None
    if kind == "delivery" and item.get("order_id"):
        oid = item["order_id"]
        services = await delivery.configured_services()
        if not services:
            kb = delivery_start_kb(oid)
        elif len(services) > 1:
            kb = delivery_service_kb(oid, services)
        else:
            kb = delivery_mode_kb(oid)
    await bot.send_message(chat_id=chat_id, text=text or "Новое сообщение", reply_markup=kb)


async def _outbox_loop(bot: Bot, storage: RedisStorage) -> None:
    """Забирает исходящие сообщения из backend и доставляет клиентам (backend
    не ходит в Telegram напрямую — TG заблокирован на сервере)."""
    while True:
        try:
            for item in await backend.get_outbox("tg"):
                try:
                    await _deliver(bot, item, storage)
                    await backend.mark_outbox_sent(item["id"])
                except Exception as e:  # noqa: BLE001
                    logging.warning("outbox tg: доставка не удалась: %s", e)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(5)


async def _make_bot() -> Bot:
    """Собрать Telegram-клиент. Прокси — best-effort: если он мёртв, идём напрямую.

    На VPS в РФ api.telegram.org иногда недоступен, поэтому в TG_PROXY кладут
    socks/http. Но мёртвый прокси раньше ронял процесс на getMe (таймаут 60с) и
    docker restart: unless-stopped крутил это сотни раз — бот молчал. Прямой
    доступ с этого же хоста при этом мог уже работать.
    """
    proxy = settings.tg_proxy
    if not proxy:
        return Bot(settings.tg_bot_token)
    logging.info("Telegram: пробуем прокси")
    bot = Bot(settings.tg_bot_token, session=AiohttpSession(proxy=proxy))
    try:
        await asyncio.wait_for(bot.get_me(), timeout=15)
        logging.info("Telegram: прокси работает")
        return bot
    except Exception as e:  # noqa: BLE001
        logging.warning("Прокси недоступен (%s), подключаемся к Telegram напрямую", e)
        await bot.session.close()
        return Bot(settings.tg_bot_token)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await texts.load()

    bot = await _make_bot()
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)
    dp.message.outer_middleware(PendingFsmMiddleware())
    dp.include_router(router)

    outbox = asyncio.create_task(_outbox_loop(bot, storage))
    try:
        await dp.start_polling(bot)
    finally:
        outbox.cancel()
        await backend.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
