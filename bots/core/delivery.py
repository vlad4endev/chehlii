"""Оформление доставки в боте: служба → ПВЗ или курьер → расчёт → ссылка оплаты."""

from __future__ import annotations

import re

import httpx

from bots.core.backend import backend

_POSTAL = re.compile(r"\b(\d{6})\b")

NEEDS_CHECKOUT = frozenset(
    {
        "postpayment_paid",
        "delivery_service_selection",
        "delivery_address_selection",
        "delivery_payment",
    }
)

SERVICE_LABELS = {"cdek": "СДЭК", "yandex": "Яндекс Доставка"}

_STATUS_RU = {
    "postpayment_paid": "оплачен — оформите доставку",
    "delivery_service_selection": "выберите службу и способ получения",
    "delivery_address_selection": "укажите адрес",
    "delivery_payment": "ожидает оплату доставки",
    "shipped": "в пути",
    "delivered": "получен",
}


def extract_postal(text: str) -> str | None:
    m = _POSTAL.search(text or "")
    return m.group(1) if m else None


def api_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            detail = e.response.json().get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        except Exception:  # noqa: BLE001
            pass
        return (e.response.text or str(e))[:240]
    return str(e)[:240]


def service_label(code: str | None) -> str:
    return SERVICE_LABELS.get(code or "", "доставку")


async def configured_services() -> list[str]:
    try:
        data = await backend.delivery_options()
    except Exception:  # noqa: BLE001
        return []
    return [s for s in (data.get("services") or []) if s in SERVICE_LABELS]


async def resolve_service(stored: str | None) -> str:
    if stored in SERVICE_LABELS:
        return stored
    services = await configured_services()
    if len(services) == 1:
        return services[0]
    return "cdek"


def orders_text(orders: list[dict]) -> str:
    if not orders:
        return "Пока нет заказов с доставкой."
    lines = ["Ваши доставки:"]
    for o in orders[:10]:
        st = _STATUS_RU.get(o.get("status") or "", o.get("status") or "")
        name = o.get("case_name") or "заказ"
        track = f", трек {o['tracking_code']}" if o.get("tracking_code") else ""
        addr = o.get("delivery_address")
        extra = f"\n   {addr}" if addr else ""
        lines.append(f"#{o['id']} {name} — {st}{track}{extra}")
    return "\n".join(lines)


def quote_text(quote: dict) -> str:
    cost = int(round(float(quote.get("delivery_sum") or 0)))
    mn, mx = quote.get("period_min"), quote.get("period_max")
    if mn and mx and mn != mx:
        period = f"Срок {mn}–{mx} дн. "
    elif mn or mx:
        period = f"Срок {mn or mx} дн. "
    else:
        period = ""
    addr = quote.get("address") or ""
    where = f"\nАдрес: {addr}" if addr else ""
    name = service_label(quote.get("service"))
    return f"Доставка {name} — {cost} ₽. {period.strip()}{where}".strip()


def points_text(city: str, points: list[dict], service: str = "cdek") -> str:
    name = service_label(service)
    lines = [f"Пункты выдачи {name} в «{city}». Нажмите номер:"]
    for i, p in enumerate(points[:8], start=1):
        addr = p.get("address") or p.get("name") or p.get("id") or "ПВЗ"
        lines.append(f"{i}. {addr}")
    return "\n".join(lines)


def empty_points_text(service: str = "cdek") -> str:
    return (
        f"В этом городе нет пунктов выдачи {service_label(service)}. "
        "Напишите другой город или выберите курьера."
    )


async def pickup_points(city: str, service: str = "cdek") -> list[dict]:
    if service == "yandex":
        return await backend.yandex_pickup_points(city, limit=8)
    return await backend.cdek_pickup_points(city, limit=8)


async def quote_pvz(order_id: int, point: dict, service: str = "cdek") -> dict:
    point_id = str(point.get("id") or "")
    if service == "yandex":
        return await backend.yandex_select(
            order_id,
            pickup_point_id=point_id,
            to_address=point.get("address"),
        )
    return await backend.cdek_quote(
        order_id,
        pickup_point_id=point_id,
        to_address=point.get("address"),
        to_city=point.get("city"),
        to_postal=point.get("postal_code"),
    )


async def quote_door(order_id: int, city: str, street: str, service: str = "cdek") -> dict:
    postal = extract_postal(city) or extract_postal(street)
    city_name = _POSTAL.sub("", city or "").strip(" ,") or None
    address = street if city_name and city_name.lower() in street.lower() else f"{city}, {street}"
    address = address.strip(" ,")
    if service == "yandex":
        return await backend.yandex_select(order_id, to_address=address)
    return await backend.cdek_quote(
        order_id,
        to_postal=postal,
        to_address=address,
        to_city=city_name or city,
    )


if __name__ == "__main__":
    assert extract_postal("101000, Москва") == "101000"
    assert extract_postal("Казань") is None
    text = quote_text({"delivery_sum": 350.4, "period_min": 2, "period_max": 4, "address": "ПВЗ"})
    assert "350 ₽" in text, text
    assert "2–4" in text, text
    yandex = quote_text({"delivery_sum": 400, "service": "yandex", "address": "ПВЗ"})
    assert "Яндекс" in yandex, yandex
    assert "нет заказов" in orders_text([]).lower()
    pts = points_text("Казань", [{"address": "Баумана 1"}], "yandex")
    assert "1. Баумана 1" in pts
    assert "Яндекс" in pts
    print("ok")
