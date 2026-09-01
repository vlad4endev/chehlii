"""Автоподготовка видео-кружка для Telegram (send_video_note).

Кружок должен быть коротким квадратным MP4. Здесь один раз (при отправке рассылки)
прогоняем ffmpeg: центрированный кроп до квадрата, до 60 с, 384×384, H.264/AAC.
Готовый файл кладём в media/notes/, возвращаем /media/notes/… — боты качают его
как обычно и уходят в send_video_note.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from app.core.config import settings


async def prepare(source_url: str) -> str:
    """Подготовить видео к формату Telegram-кружка. Возвращает новый /media/notes/…
    URL. Если ffmpeg отсутствует / файл не найден / прогон упал — возвращаем исходный.
    ponytail: prep один раз на рассылку; для 10× трафика — кэш по хэшу исходника.
    """
    if not source_url.startswith("/media/"):
        return source_url
    src = Path(settings.media_root) / source_url[len("/media/") :]
    if not src.exists():
        return source_url
    out_dir = Path(settings.media_root) / "notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{uuid.uuid4().hex}.mp4"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-t",
            "60",
            "-vf",
            "crop='min(iw,ih)':'min(iw,ih)',scale=384:384",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
    except FileNotFoundError:
        logging.warning("video_note: ffmpeg не установлен, отправляю исходное видео")
        return source_url
    if rc != 0 or not out.exists() or out.stat().st_size == 0:
        logging.warning("video_note: ffmpeg rc=%s, отправляю исходное видео", rc)
        return source_url
    return f"/media/notes/{out.name}"
