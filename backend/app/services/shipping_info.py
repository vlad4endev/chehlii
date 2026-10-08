"""Данные об отправке для админки: служба, адрес, трек и ссылка отслеживания."""

from __future__ import annotations

from app.services.cdek_checkout import decode_destination

SERVICE_LABELS: dict[str, str] = {
    "cdek": "СДЭК",
    "yandex": "Яндекс Доставка",
    "ozon": "Ozon Доставка",
}


def service_label(code: str | None) -> str | None:
    if not code:
        return None
    return SERVICE_LABELS.get(code, code)


def tracking_url(service: str | None, code: str | None, *, sharing_url: str | None = None) -> str | None:
    """Публичная ссылка на отслеживание. Для Яндекса предпочтителен sharing_url из API."""
    if sharing_url:
        return sharing_url
    if not service or not code:
        return None
    if service == "cdek":
        # Номер накладной (не uuid заявки) открывается на сайте СДЭК.
        return f"https://www.cdek.ru/ru/tracking?order_id={code}"
    if service == "ozon":
        return f"https://tracking.ozon.ru/?track={code}"
    return None


def destination_parts(stored: str | None) -> dict[str, str | None]:
    """Разбор адреса заказа для карточки: режим, ПВЗ, человекочитаемая подпись."""
    if not stored:
        return {
            "delivery_mode": None,
            "delivery_point_id": None,
            "delivery_address": None,
        }
    dest = decode_destination(stored)
    if dest.get("pickup_point_id"):
        label = (dest.get("label") or dest["pickup_point_id"]).strip()
        return {
            "delivery_mode": "pvz",
            "delivery_point_id": dest["pickup_point_id"],
            "delivery_address": f"ПВЗ: {label}",
        }
    label = (dest.get("label") or "").strip() or None
    postal = dest.get("to_postal")
    if postal and label and postal not in label:
        human = f"{label} (индекс {postal})"
    else:
        human = label or (f"Индекс {postal}" if postal else None)
    return {
        "delivery_mode": "door",
        "delivery_point_id": None,
        "delivery_address": f"Курьер: {human}" if human else None,
    }
