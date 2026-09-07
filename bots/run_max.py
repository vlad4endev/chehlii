"""Точка входа MAX-бота (long polling). Запуск: python -m bots.run_max (из корня репо).

Требуется MAX_BOT_TOKEN в bots/.env. Единое ядро (core/) и backend — общие с Telegram.
"""

from __future__ import annotations

import asyncio
import logging

from maxapi import Bot
from maxapi.enums.upload_type import UploadType
from maxapi.types.input_media import InputMediaBuffer

from bots.core import delivery
from bots.core.backend import backend
from bots.core.config import settings
from bots.core.fetch_media import fetch_bytes, looks_like_image, looks_like_pdf
from bots.core.texts import texts
from bots.max.handlers import dp
from bots.max.keyboards import (
    delivery_mode_kb,
    delivery_service_kb,
    delivery_start_kb,
    mockup_kb,
)


async def _fetch_media(path_or_url: str) -> bytes | None:
    return await fetch_bytes(path_or_url)


def _media_of(item: dict) -> list[dict]:
    """Список вложений рассылки. Старый одиночный photo нормализуем к списку."""
    media = list(item.get("media") or [])
    if not media and item.get("kind") == "photo" and item.get("attachment_url"):
        media = [{"url": item["attachment_url"], "type": "image"}]
    return media[:10]


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


async def _deliver(bot: Bot, item: dict) -> None:
    text = item.get("text") or ""
    kind = item.get("kind")
    uid = int(item["channel_user_id"])
    if kind == "mockup":
        await _deliver_mockup(bot, item)
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
            atts2 = [delivery_mode_kb(oid)]
    await bot.send_message(user_id=uid, text=text or "Новое сообщение", attachments=atts2)


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
