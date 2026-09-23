"""Общая логика раздела «Поможем выбрать»: сохранить сообщение клиента в backend."""

from __future__ import annotations

import logging


def has_phone(client: dict) -> bool:
    return bool(str(client.get("phone") or "").strip())


def can_write(*, phone: str | None, thread_open: bool = False) -> bool:
    """Номер — достаточно, даже без заказа. Без номера — только открытый диалог."""
    return has_phone({"phone": phone}) or thread_open


async def allowed_to_write(client: dict) -> bool:
    """Писать админу можно с номером — даже без заказа — или если диалог уже открыт."""
    if can_write(phone=client.get("phone")):
        return True
    from bots.core.backend import backend

    try:
        return await backend.consult_is_open(int(client["id"]))
    except (KeyError, TypeError, ValueError):
        return False


async def ingest(
    client_id: int,
    text: str | None,
    files: list[tuple[str, bytes]],
) -> bool:
    """Загрузить вложения и отправить сообщение. False, если нечего слать."""
    from bots.core.backend import backend

    media: list[dict] = []
    for name, content in files:
        if not content:
            continue
        try:
            res = await backend.consult_upload(name, content)
            media.append({"url": res["url"], "type": res.get("type") or "file", "name": name})
        except Exception as e:  # noqa: BLE001
            logging.warning("consult upload failed (%s): %s", name, e)
    body = (text or "").strip() or None
    if not body and not media:
        return False
    await backend.consult_send(client_id, text=body, media=media or None)
    return True
