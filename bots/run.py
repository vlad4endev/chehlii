"""Точка входа Telegram-бота (long polling). Запуск: python -m bots.run (из корня репо)."""

from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile

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


async def _deliver(bot: Bot, item: dict) -> None:
    text = item.get("text") or ""
    url = item.get("attachment_url")
    kind = item.get("kind")
    chat_id = int(item["channel_user_id"])

    # Рассылка с картинкой → отправляем фото (подпись до 1024 символов).
    if kind == "photo" and url and (data := await _fetch_media(url)):
        caption = text if 0 < len(text) <= 1024 else None
        await bot.send_photo(
            chat_id=chat_id, photo=BufferedInputFile(data, "image.jpg"), caption=caption
        )
        if text and caption is None:
            await bot.send_message(chat_id=chat_id, text=text)
        return

    # Макет — ссылкой; обычный текст — как есть.
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await texts.load()

    # api.telegram.org заблокирован в РФ — при наличии TG_PROXY ходим через прокси.
    session = AiohttpSession(proxy=settings.tg_proxy) if settings.tg_proxy else None
    if settings.tg_proxy:
        logging.info("Telegram: используется прокси")
    bot = Bot(settings.tg_bot_token, session=session)
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
