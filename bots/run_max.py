"""Точка входа MAX-бота (long polling). Запуск: python -m bots.run_max (из корня репо).

Требуется MAX_BOT_TOKEN в bots/.env. Единое ядро (core/) и backend — общие с Telegram.
"""

from __future__ import annotations

import asyncio
import logging

from maxapi import Bot

from bots.core.backend import backend
from bots.core.config import settings
from bots.core.texts import texts
from bots.max.handlers import dp
from bots.max.keyboards import mockup_kb


async def _deliver(bot: Bot, item: dict) -> None:
    text = item.get("text") or "Новое сообщение"
    url = item.get("attachment_url")
    if url:
        text = f"{text}\n\n📎 Макет: {url}"
    atts = (
        [mockup_kb(item["order_id"])]
        if item.get("kind") == "mockup" and item.get("order_id")
        else None
    )
    await bot.send_message(user_id=int(item["channel_user_id"]), text=text, attachments=atts)


async def _outbox_loop(bot: Bot) -> None:
    """Забирает исходящие сообщения из backend и доставляет клиентам в MAX."""
    while True:
        try:
            for item in await backend.get_outbox("max"):
                try:
                    await _deliver(bot, item)
                    await backend.mark_outbox_sent(item["id"])
                except Exception as e:  # noqa: BLE001
                    logging.warning("outbox max: доставка не удалась: %s", e)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(5)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.max_bot_token:
        raise SystemExit("MAX_BOT_TOKEN не задан в bots/.env — получите токен MAX-бота у @MasterBot.")

    await texts.load()
    bot = Bot(settings.max_bot_token)
    outbox = asyncio.create_task(_outbox_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        outbox.cancel()
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
