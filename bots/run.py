"""Точка входа Telegram-бота (long polling). Запуск: python -m bots.run (из корня репо)."""

from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo

from bots.core.backend import backend
from bots.core.config import settings
from bots.core.texts import texts
from bots.tg.handlers import router
from bots.tg.keyboards import mockup_kb


async def _fetch_media(path_or_url: str) -> bytes | None:
    """Скачать изображение (из backend по внутреннему адресу) для отправки вложением."""
    try:
        if path_or_url.startswith("http"):
            u = path_or_url
        else:
            origin = settings.backend_url.split("/api/")[0]  # http://backend:8000
            u = f"{origin}{path_or_url}"
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(u)
            r.raise_for_status()
            return r.content
    except Exception:  # noqa: BLE001
        return None


def _media_of(item: dict) -> list[dict]:
    """Список вложений рассылки. Старый одиночный photo нормализуем к списку."""
    media = list(item.get("media") or [])
    if not media and item.get("kind") == "photo" and item.get("attachment_url"):
        media = [{"url": item["attachment_url"], "type": "image"}]
    return media[:10]  # Telegram: не больше 10 в альбоме


async def _deliver(bot: Bot, item: dict) -> None:
    text = item.get("text") or ""
    kind = item.get("kind")
    chat_id = int(item["channel_user_id"])

    # Рассылка с медиа: фото/видео — альбомом; кружки (video note) — отдельно.
    media = _media_of(item)
    if media:
        notes = [m for m in media if m.get("type") == "video_note"]
        rest = [m for m in media if m.get("type") in ("image", "video")]
        sent_any = False
        text_sent = False

        # 1) Фото/обычные видео: одно — отдельно, несколько — альбомом (с подписью).
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

        # 2) Видео-кружки: у video note подписи нет — шлём отдельными сообщениями.
        for i, mm in enumerate(notes):
            data = await _fetch_media(mm.get("url", ""))
            if data:
                await bot.send_video_note(
                    chat_id=chat_id, video_note=BufferedInputFile(data, f"n{i}.mp4")
                )
                sent_any = True

        # 3) Текст, если ещё не ушёл подписью.
        if sent_any:
            if text and not text_sent:
                await bot.send_message(chat_id=chat_id, text=text)
            return
        # если ничего не скачалось — упадём на текст ниже

    url = item.get("attachment_url")
    if url and kind == "mockup":
        text = f"{text or 'Новое сообщение'}\n\n📎 Макет: {url}"
    kb = mockup_kb(item["order_id"]) if kind == "mockup" and item.get("order_id") else None
    await bot.send_message(chat_id=chat_id, text=text or "Новое сообщение", reply_markup=kb)


async def _outbox_loop(bot: Bot) -> None:
    """Забирает исходящие сообщения из backend и доставляет клиентам (backend
    не ходит в Telegram напрямую — TG заблокирован на сервере)."""
    while True:
        try:
            for item in await backend.get_outbox("tg"):
                try:
                    await _deliver(bot, item)
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
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    dp.include_router(router)

    outbox = asyncio.create_task(_outbox_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        outbox.cancel()
        await backend.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
