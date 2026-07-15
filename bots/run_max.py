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


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.max_bot_token:
        raise SystemExit("MAX_BOT_TOKEN не задан в bots/.env — получите токен MAX-бота у @MasterBot.")

    await texts.load()
    bot = Bot(settings.max_bot_token)
    try:
        await dp.start_polling(bot)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
