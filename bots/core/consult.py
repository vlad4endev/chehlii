"""Общая логика раздела «Поможем выбрать»: сохранить сообщение клиента."""

from __future__ import annotations

import logging

from bots.core.backend import backend


async def ingest(
    client_id: int,
    text: str | None,
    files: list[tuple[str, bytes]],
) -> bool:
    """Загрузить вложения и отправить сообщение. False, если нечего слать."""
    media: list[dict] = []
    for name, content in files:
        if not content:
            continue
        try:
            res = await backend.consult_upload(name, content)
            media.append(
                {"url": res["url"], "type": res.get("type") or "file", "name": name}
            )
        except Exception as e:  # noqa: BLE001
            logging.warning("consult upload failed (%s): %s", name, e)
    body = (text or "").strip() or None
    if not body and not media:
        return False
    await backend.consult_send(client_id, text=body, media=media or None)
    return True
