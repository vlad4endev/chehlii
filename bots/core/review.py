"""Приём отзыва: ответ на msg_016 → /reviews, не в консультацию."""

from __future__ import annotations

import logging


async def has_pending(client_id: int) -> bool:
    from bots.core.backend import backend

    try:
        return await backend.review_is_pending(int(client_id))
    except (TypeError, ValueError):
        return False


async def ingest(
    client_id: int,
    text: str | None,
    files: list[tuple[str, bytes]],
) -> bool:
    """Загрузить фото и отправить отзыв. False, если нечего слать."""
    from bots.core.backend import backend

    photo_url: str | None = None
    for name, content in files:
        if not content or photo_url:
            continue
        try:
            res = await backend.review_upload(name, content)
            photo_url = res.get("url") or None
        except Exception as e:  # noqa: BLE001
            # Не-изображения (голос и т.п.) бэкенд отклоняет — пробуем следующее.
            logging.warning("review upload skipped (%s): %s", name, e)
    body = (text or "").strip() or None
    if not body and not photo_url:
        return False
    await backend.review_submit(client_id, text=body, photo_url=photo_url)
    return True
