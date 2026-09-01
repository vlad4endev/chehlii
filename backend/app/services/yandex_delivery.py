"""Яндекс Доставка (Platform API): геолокация, ПВЗ, варианты доставки, создание заказа.

Создание доставки идёт через офферы: `offers/create` (варианты + цена) →
`offers/confirm` (бронь) → `request_id` заказа. Прямой `request/create` тоже есть,
но он не возвращает стоимость, а клиент оплачивает доставку до её создания
(статус `delivery_payment` перед `shipped`) — поэтому цена нужна заранее.

ПВЗ работает на одном токене Доставки (`location/detect` → `pickup-points/list`).
Курьер до двери требует координат: `custom_location` принимает только широту/долготу,
а `location/detect` отдаёт лишь `geo_id` города — поэтому для адресной доставки нужен
отдельный ключ Геокодера («Настройки → Интеграции»).

Единицы API: деньги — копейки, вес — граммы, габариты — сантиметры.
Прод: https://b2b-authproxy.taxi.yandex.net, тест: https://b2b.taxi.tst.yandex.net.
Док: https://yandex.ru/support/delivery-profile/ru/api/other-day/
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

PROD = "https://b2b-authproxy.taxi.yandex.net"
TEST = "https://b2b.taxi.tst.yandex.net"
GEOCODER = "https://geocode-maps.yandex.ru/v1"

# Габариты коробки под чехол — те же, что для СДЭК (см. services/cdek.py).
BOX_CM = (20, 15, 5)
# ponytail: окно забора — 8 часов от `pickup_delay_hours`. Для склада интервал должен
# совпадать с отгрузками в ЛК; если расписание другое — вынести окно в настройки.
PICKUP_WINDOW_HOURS = 8
_TS = "%Y-%m-%dT%H:%M:%SZ"


class YandexDeliveryError(RuntimeError):
    pass


def base_url(is_test: bool) -> str:
    return TEST if is_test else PROD


def to_kopecks(rub: float) -> int:
    """Рубли → копейки: все денежные поля Platform API принимают копейки."""
    return int(round(float(rub) * 100))


def price_to_rub(value: Any) -> float:
    """Цена оффера приходит строкой «192.15 RUB» — вытаскиваем рубли."""
    if isinstance(value, int | float):
        return float(value)
    parts = str(value or "").replace(",", ".").split()
    try:
        return float(parts[0]) if parts else 0.0
    except ValueError:
        return 0.0


async def _request(
    cfg: dict,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    raw: bool = False,
) -> Any:
    """`raw=True` — вернуть байты (ярлыки приходят application/pdf, а не JSON)."""
    if not cfg.get("token"):
        raise YandexDeliveryError("не задан OAuth-токен")
    async with httpx.AsyncClient(timeout=60 if raw else 30) as client:
        r = await client.request(
            method,
            f"{base_url(cfg['is_test'])}{path}",
            headers={"Authorization": f"Bearer {cfg['token']}", "Accept-Language": "ru"},
            json=json,
            params=params,
        )
    if r.status_code >= 400:
        raise YandexDeliveryError(f"{path}: {r.status_code} {r.text[:300]}")
    return r.content if raw else r.json()


# ── Геолокация и ПВЗ ───────────────────────────────────
async def detect_geo_id(cfg: dict, location: str) -> int | None:
    """Адрес или его фрагмент → geo_id города (для фильтра списка ПВЗ)."""
    data = await _request(
        cfg, "POST", "/api/b2b/platform/location/detect", json={"location": location}
    )
    variants = data.get("variants") or []
    return variants[0].get("geo_id") if variants else None


async def pickup_points(cfg: dict, *, geo_id: int | None = None, limit: int = 50) -> list[dict]:
    """Список ПВЗ (пункты выдачи). Пустое тело = все доступные точки."""
    body: dict[str, Any] = {"type": "pickup_point"}
    if geo_id is not None:
        body["geo_id"] = geo_id
    data = await _request(cfg, "POST", "/api/b2b/platform/pickup-points/list", json=body)
    points = data.get("points") or []
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "address": (p.get("address") or {}).get("full_address"),
            "latitude": (p.get("position") or {}).get("latitude"),
            "longitude": (p.get("position") or {}).get("longitude"),
        }
        for p in points[:limit]
    ]


async def geocode(apikey: str, address: str) -> tuple[float, float]:
    """Адрес → (широта, долгота). Нужен только для курьера до двери."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            GEOCODER,
            params={
                "apikey": apikey,
                "geocode": address,
                "format": "json",
                "lang": "ru_RU",
                "results": 1,
            },
        )
    if r.status_code >= 400:
        raise YandexDeliveryError(f"Геокодер: {r.status_code} {r.text[:200]}")
    try:
        members = r.json()["response"]["GeoObjectCollection"]["featureMember"]
        lon, lat = members[0]["GeoObject"]["Point"]["pos"].split()  # «долгота широта»
    except (KeyError, IndexError, ValueError) as e:
        raise YandexDeliveryError(f"Геокодер не нашёл координаты для «{address}»") from e
    return float(lat), float(lon)


# ── Сборка заявки ──────────────────────────────────────
def _interval_utc(delay_hours: int) -> dict[str, str]:
    start = (datetime.now(UTC) + timedelta(hours=delay_hours)).replace(
        minute=0, second=0, microsecond=0
    )
    return {
        "from": start.strftime(_TS),
        "to": (start + timedelta(hours=PICKUP_WINDOW_HOURS)).strftime(_TS),
    }


def _destination(
    *,
    pickup_point_id: str | None,
    address: str | None,
    latitude: float | None,
    longitude: float | None,
) -> dict:
    if pickup_point_id:
        return {
            "type": "platform_station",
            "platform_station": {"platform_id": pickup_point_id},
        }
    if latitude is None or longitude is None:
        raise YandexDeliveryError(
            "для курьерской доставки нужны координаты адреса — задайте API-ключ Геокодера "
            "в «Настройки → Интеграции» или выберите ПВЗ"
        )
    return {
        "type": "custom_location",
        "custom_location": {
            "latitude": latitude,
            "longitude": longitude,
            "details": {"full_address": address or ""},
        },
    }


def build_request(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_name: str,
    recipient_phone: str,
    pickup_point_id: str | None = None,
    address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    """Тело заявки — одинаковое для offers/create и request/create."""
    if not cfg.get("platform_station_id"):
        raise YandexDeliveryError("не задан ID склада отправителя (platform_station_id)")
    barcode = f"casetop-{order_id}"
    dx, dy, dz = BOX_CM
    # ФИО клиент присылает как одну строку; last_name в заявке обязателен, поэтому
    # при одном слове ставим прочерк — так делают формы доставки.
    first, _, last = (recipient_name or "").strip().partition(" ")
    price_kop = to_kopecks(item_price_rub)
    body: dict[str, Any] = {
        "info": {"operator_request_id": barcode},
        "source": {
            "platform_station": {"platform_id": cfg["platform_station_id"]},
            "interval_utc": _interval_utc(cfg["pickup_delay_hours"]),
        },
        "destination": _destination(
            pickup_point_id=pickup_point_id,
            address=address,
            latitude=latitude,
            longitude=longitude,
        ),
        "items": [
            {
                "count": 1,
                "name": "Чехол для смартфона",
                "article": str(order_id),
                "billing_details": {
                    "unit_price": price_kop,
                    "assessed_unit_price": price_kop,
                    "nds": cfg["nds"],
                },
                "physical_dims": {"dx": dx, "dy": dy, "dz": dz},
                "place_barcode": barcode,
            }
        ],
        "places": [
            {
                "barcode": barcode,
                "physical_dims": {"weight_gross": cfg["weight"], "dx": dx, "dy": dy, "dz": dz},
            }
        ],
        "billing_info": {"payment_method": cfg["payment_method"]},
        "recipient_info": {
            "first_name": first or "Получатель",
            "last_name": last or "—",
            "phone": recipient_phone,
        },
        "last_mile_policy": "self_pickup" if pickup_point_id else cfg["last_mile_policy"],
    }
    if cfg.get("merchant_id"):
        body["info"]["merchant_id"] = cfg["merchant_id"]
    return body


# ── Офферы и заказ ─────────────────────────────────────
async def offers_create(cfg: dict, body: dict) -> list[dict]:
    """Варианты доставки с ценой. `delivery_cost` — стоимость доставки с НДС.

    `total_cost` (pricing_total) включает комиссию за приём платежа получателем —
    берём его только для справки, клиенту выставляем `delivery_cost`.
    """
    data = await _request(cfg, "POST", "/api/b2b/platform/offers/create", json=body)
    offers = []
    for o in data.get("offers") or []:
        d = o.get("offer_details") or {}
        interval = d.get("delivery_interval") or {}
        offers.append(
            {
                "offer_id": o.get("offer_id"),
                "expires_at": o.get("expires_at"),
                "delivery_cost": price_to_rub(d.get("pricing")),
                "total_cost": price_to_rub(d.get("pricing_total")),
                "delivery_from": interval.get("min"),
                "delivery_to": interval.get("max"),
                "policy": interval.get("policy"),
            }
        )
    if not offers:
        raise YandexDeliveryError("Яндекс не предложил вариантов доставки по этим данным")
    return offers


async def offers_confirm(cfg: dict, offer_id: str) -> str:
    """Забронировать оффер → id заказа в платформе (request_id)."""
    data = await _request(
        cfg, "POST", "/api/b2b/platform/offers/confirm", json={"offer_id": offer_id}
    )
    request_id = data.get("request_id")
    if not request_id:
        raise YandexDeliveryError("не получили request_id при подтверждении оффера")
    return str(request_id)


async def request_info(cfg: dict, request_id: str) -> dict:
    """Статус заказа, номер у оператора и ссылка на трекинг для получателя."""
    data = await _request(
        cfg, "GET", "/api/b2b/platform/request/info", params={"request_id": request_id}
    )
    state = data.get("state") or {}
    return {
        "request_id": data.get("request_id"),
        "status": state.get("status"),
        "description": state.get("description"),
        "courier_order_id": data.get("courier_order_id"),
        "sharing_url": data.get("sharing_url"),
    }


# ── Статусы платформы ──────────────────────────────────
# Берём только «жирные» вехи статусной модели (док: api/other-day/status-model) плюс
# те статусы детализации, которые для клиента означают то же самое. Детализация
# внутри сортировочного центра клиенту не интересна — она не меняет наш статус.
DELIVERED_STATUSES = frozenset(
    {
        "DELIVERY_DELIVERED",  # вручён клиенту / выдан в ПВЗ
        "PARTICULARLY_DELIVERED",  # частичная выдача — для нас заказ из одной позиции
        "DELIVERY_TRANSMITTED_TO_RECIPIENT",  # «выдан получателю» — то же событие, деталь
    }
)
SHIPPED_STATUSES = frozenset(
    {
        "SORTING_CENTER_AT_START",  # поступил в точку приёма — посылка уже не у нас
        "SORTING_CENTER_PREPARED",
        "SORTING_CENTER_TRANSMITTED",
        "DELIVERY_AT_START",
        "DELIVERY_AT_START_SORT",
        "DELIVERY_TRANSPORTATION",  # едет в ПВЗ
        "DELIVERY_TRANSPORTATION_RECIPIENT",  # едет к получателю
        "DELIVERY_ARRIVED_PICKUP_POINT",  # доставлен в ПВЗ, ждёт получателя
    }
)


def map_status(status: str | None) -> str | None:
    """Статус платформы → «shipped» / «delivered» / None (ничего не менять).

    `CANCELLED` намеренно не отменяет наш заказ: у нас с ним связаны оплаты и
    возврат балванки на склад — это решение оператора, а не автомата.
    """
    code = (status or "").upper()
    if code in DELIVERED_STATUSES:
        return "delivered"
    if code in SHIPPED_STATUSES:
        return "shipped"
    return None


# ── Отмена, ярлыки, склады ─────────────────────────────
async def cancel(cfg: dict, request_id: str) -> dict:
    """Отменить заявку. Курьерскую — до статуса DELIVERY_TRANSPORTATION_RECIPIENT."""
    data = await _request(
        cfg, "POST", "/api/b2b/platform/request/cancel", json={"request_id": request_id}
    )
    return {
        "status": data.get("status"),
        "reason": data.get("reason"),
        "description": data.get("description"),
    }


async def generate_label(cfg: dict, request_id: str, *, size_mm: str = "210x297") -> bytes:
    """PDF-ярлык на посылку. Без него посылку не примут на отгрузке."""
    return await _request(
        cfg,
        "POST",
        "/api/b2b/platform/request/generate-labels",
        json={
            "request_ids": [request_id],
            "generate_type": "one",
            "label_size_mm": size_mm,
            "language": "ru",
        },
        raw=True,
    )


async def warehouses(cfg: dict) -> list[dict]:
    """Склады отправителя: отсюда берётся `platform_station_id` для заявки."""
    body: dict[str, Any] = {"filter": {}}
    if cfg.get("merchant_id"):
        body["filter"]["merchant_id"] = cfg["merchant_id"]
    data = await _request(cfg, "POST", "/api/b2b/platform/warehouses/list", json=body)
    out = []
    for w in data.get("warehouses") or []:
        addr = ((w.get("location") or {}).get("address")) or {}
        out.append(
            {
                "station_id": w.get("station_id"),
                "name": w.get("name"),
                "city": addr.get("city"),
            }
        )
    return out


async def check_connection(cfg: dict) -> tuple[bool, str]:
    """Проба связи без побочных эффектов.

    Токен проверяем самым базовым методом (`location/detect`): он нужен любой
    интеграции. `warehouses/list` для этого не годится — раздел управления
    складами открыт не всякому токену и отвечает 401 даже на рабочих кредах.
    Склады показываем сверх того, если доступ есть: их `station_id` нужен в
    настройках, а в ЛК он на глаза не попадается.
    """
    mode = "тест" if cfg["is_test"] else "продакшен"
    try:
        await detect_geo_id(cfg, "Москва")
    except YandexDeliveryError as e:
        detail = str(e)[:160]
        if cfg["is_test"] and "401" in detail:
            detail += (
                ". В тестовом режиме нужен тестовый токен из документации — "
                "токен из ЛК действует только на продакшене"
            )
        return False, f"токен отклонён ({mode}): {detail}"

    try:
        found = await warehouses(cfg)
    except YandexDeliveryError:
        # Нет доступа к разделу складов — на саму доставку это не влияет.
        return True, f"связь есть, токен принят ({mode}). ID склада возьмите в ЛК Доставки"
    if not found:
        return True, f"токен принят ({mode}), но складов нет — создайте склад в ЛК Доставки"
    listed = ", ".join(f"{w['name'] or '—'} [{w['station_id']}]" for w in found[:5])
    return True, f"связь есть, токен принят ({mode}). Склады: {listed}"
