"""Ozon Доставка для бизнеса (Delivery API): OAuth, ПВЗ, расчёт, заявка, статус.

Это не Seller API и не старый Ozon Rocket. Креды — частное приложение в ЛК
Ozon Доставки (Client ID + Client Secret). Док: https://docs.ozon.ru/api/ozon-delivery/

OAuth: POST https://xapi.ozon.ru/oauth/token, `scope` — JSON-массив.
API: https://api-delivery.ozon.ru/, Bearer. `expires_in` — абсолютный Unix timestamp.
302/307 testcookie: повторить тот же POST на Location, без авто-follow.
`POST /v1/order/create` требует `Idempotency-Key` (UUID).

Деньги — строки с копейками (`"1234.56"`), вес — граммы, габариты — миллиметры.
Объявленная стоимость не может быть 0. Телефон получателя — `+7XXXXXXXXXX`,
и номер должен быть зарегистрирован в Ozon (`/v1/delivery/check-client`).
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

TOKEN_URL = "https://xapi.ozon.ru/oauth/token"
API = "https://api-delivery.ozon.ru"
SCOPES = ("delivery-api.all",)
# Те же габариты коробки, что у СДЭК/Яндекса, но API ждёт миллиметры.
BOX_MM = (200, 150, 50)
_TOKEN_MARGIN = 60.0
_MAX_REDIRECTS = 3
_REDIRECT_CODES = frozenset({302, 307})
_PHONE = re.compile(r"^\+7\d{10}$")
_IDEMPOTENCY_NS = uuid5(NAMESPACE_URL, "casetop:ozon-delivery")

# Кэш токенов по client_id: (token, expires_at).
_token_cache: dict[str, tuple[str, float]] = {}


class OzonDeliveryError(RuntimeError):
    pass


def sanitize_secret(raw: str | None) -> str:
    """Убрать кавычки, пробелы и переносы — из ЛК часто копируют с хвостовым пробелом."""
    return "".join((raw or "").strip().strip('"').strip("'").split())


def normalize_phone(raw: str | None) -> str:
    """Любой российский номер → +7XXXXXXXXXX. Иначе OzonDeliveryError."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        raise OzonDeliveryError("телефон получателя должен быть в формате +7XXXXXXXXXX")
    phone = f"+7{digits}"
    if not _PHONE.match(phone):
        raise OzonDeliveryError("телефон получателя должен быть в формате +7XXXXXXXXXX")
    return phone


def money_amount(rub: float) -> str:
    """Рубли → строка для Money.amount. Ноль Ozon не принимает — нижняя граница 1.00."""
    value = max(round(float(rub), 2), 1.0)
    return f"{value:.2f}"


def parse_expires_at(expires_in: Any, *, now: float | None = None) -> float:
    """`expires_in` у Ozon — абсолютный Unix timestamp; запасной путь — TTL в секундах."""
    clock = now if now is not None else time.time()
    if isinstance(expires_in, bool) or not isinstance(expires_in, int | float):
        raise OzonDeliveryError("OAuth: нет числового expires_in")
    value = float(expires_in)
    expires_at = value if value > clock else clock + value
    if expires_at - clock <= _TOKEN_MARGIN:
        raise OzonDeliveryError("OAuth: срок токена слишком короткий")
    return expires_at


def default_cutoff_at(*, now: datetime | None = None) -> str:
    """Окно отгрузки: сейчас + 24 ч, округлённое до часа, ISO UTC."""
    dt = (now or datetime.now(UTC)) + timedelta(hours=24)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def idempotency_key(order_id: int) -> UUID:
    """Стабильный ключ на заказ: повтор fulfill не создаёт вторую заявку."""
    return uuid5(_IDEMPOTENCY_NS, str(int(order_id)))


def _error_text(status: int, text: str) -> str:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"{status} {text[:300]}"
    nested = data.get("error") if isinstance(data, dict) else None
    msg = None
    if isinstance(nested, dict):
        msg = nested.get("message") or nested.get("code")
    if not msg and isinstance(data, dict):
        msg = data.get("message") or data.get("code")
    return str(msg) if msg else f"{status} {text[:300]}"


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port


async def _token(client: httpx.AsyncClient, cfg: dict) -> str:
    client_id = sanitize_secret(cfg.get("client_id"))
    secret = sanitize_secret(cfg.get("client_secret"))
    if not client_id or not secret:
        raise OzonDeliveryError("не заданы Client ID / Client Secret")
    cached = _token_cache.get(client_id)
    if cached and cached[1] > time.time() + _TOKEN_MARGIN:
        return cached[0]
    r = await client.post(
        TOKEN_URL,
        json={
            "client_id": client_id,
            "client_secret": secret,
            "grant_type": "client_credentials",
            "scope": list(SCOPES),
        },
        follow_redirects=False,
    )
    if r.status_code >= 400:
        raise OzonDeliveryError(f"авторизация Ozon: {_error_text(r.status_code, r.text)}")
    try:
        data = r.json()
    except ValueError as e:
        raise OzonDeliveryError("OAuth: некорректный JSON") from e
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise OzonDeliveryError("OAuth: нет access_token")
    expires_at = parse_expires_at(data.get("expires_in"))
    _token_cache[client_id] = (token, expires_at)
    return token


async def _request(
    cfg: dict,
    path: str,
    payload: dict,
    *,
    idempotency_key: UUID | None = None,
    raw: bool = False,
    _retried: bool = False,
) -> Any:
    """POST на Delivery API. `raw=True` — байты (ярлык PDF)."""
    cfg = {
        **cfg,
        "client_id": sanitize_secret(cfg.get("client_id")),
        "client_secret": sanitize_secret(cfg.get("client_secret")),
    }
    url = urljoin(f"{API}/", path.lstrip("/"))
    expected = _origin(API)
    if _origin(url) != expected:
        raise OzonDeliveryError("путь API вышел за origin Ozon")
    async with httpx.AsyncClient(timeout=60 if raw else 30, follow_redirects=False) as client:
        token = await _token(client, cfg)
        headers = {"Authorization": f"Bearer {token}"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = str(idempotency_key)
        redirects = 0
        while True:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 401 and not _retried:
                _token_cache.pop(cfg["client_id"], None)
                return await _request(
                    cfg,
                    path,
                    payload,
                    idempotency_key=idempotency_key,
                    raw=raw,
                    _retried=True,
                )
            if r.status_code in _REDIRECT_CODES:
                location = r.headers.get("location")
                if not location:
                    raise OzonDeliveryError("testcookie-редирект без Location")
                next_url = urljoin(url, location)
                if _origin(next_url) != expected:
                    raise OzonDeliveryError("testcookie-редирект на чужой origin")
                redirects += 1
                if redirects > _MAX_REDIRECTS:
                    raise OzonDeliveryError("слишком много testcookie-редиректов")
                url = next_url
                continue
            if r.status_code >= 400:
                raise OzonDeliveryError(f"{path}: {_error_text(r.status_code, r.text)}")
            if raw:
                return r.content
            if not r.content:
                return {}
            try:
                return r.json()
            except ValueError as e:
                raise OzonDeliveryError(f"{path}: некорректный JSON") from e


def _shipment_method_id(cfg: dict) -> int:
    try:
        value = int(str(cfg.get("shipment_method_id") or "").strip())
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise OzonDeliveryError(
            "не задан ID метода доставки (shipment_method_id) — укажите его в "
            "«Настройки → Интеграции» (в ЛК Ozon под штрих-кодом метода)"
        )
    return value


def _dimensions(cfg: dict) -> dict:
    length, width, height = BOX_MM
    weight = int(cfg.get("weight") or 300)
    return {
        "weight_g": weight,
        "length_mm": length,
        "width_mm": width,
        "height_mm": height,
    }


def build_checkout(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_phone: str,
    delivery_point_id: int,
    cutoff_at: str | None = None,
) -> dict:
    """Тело `POST /v1/order/checkout`. Сеть не трогает."""
    if delivery_point_id <= 0:
        raise OzonDeliveryError("укажите пункт выдачи Ozon")
    return {
        "recipient": {"phone_number": normalize_phone(recipient_phone)},
        "postings": [
            {
                "request_id": int(order_id),
                "shipment_method_id": _shipment_method_id(cfg),
                "cutoff_at": cutoff_at or default_cutoff_at(),
                "declared_value": {
                    "amount": money_amount(item_price_rub),
                    "currency_code": "RUB",
                },
                "dimensions": _dimensions(cfg),
            }
        ],
        "delivery": {"delivery_point": {"delivery_point_id": int(delivery_point_id)}},
    }


def build_create(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_name: str,
    recipient_phone: str,
    delivery_point_id: int,
    cutoff_at: str | None = None,
) -> dict:
    """Тело `POST /v1/order/create`. Сеть не трогает."""
    checkout = build_checkout(
        cfg,
        order_id=order_id,
        item_price_rub=item_price_rub,
        recipient_phone=recipient_phone,
        delivery_point_id=delivery_point_id,
        cutoff_at=cutoff_at,
    )
    name = (recipient_name or "Получатель").strip() or "Получатель"
    posting = {
        **checkout["postings"][0],
        "posting_external_id": f"casetop-{order_id}-1",
        "description": "Чехол для смартфона",
    }
    return {
        "order_external_id": f"casetop-{order_id}",
        "recipient": {**checkout["recipient"], "full_name": name},
        "delivery": checkout["delivery"],
        "postings": [posting],
    }


def money_to_rub(value: Any) -> float:
    """Money `{amount, currency_code}` или строка/число → рубли."""
    if isinstance(value, dict):
        value = value.get("amount")
    if isinstance(value, int | float):
        return float(value)
    text = str(value or "").replace(",", ".").split()
    try:
        return float(text[0]) if text else 0.0
    except ValueError:
        return 0.0


def parse_checkout(data: dict) -> dict:
    """Первый успешный результат checkout → цена и срок."""
    results = data.get("results") or []
    for item in results:
        if not isinstance(item, dict):
            continue
        err = item.get("error")
        if err:
            msg = err.get("message") if isinstance(err, dict) else err
            raise OzonDeliveryError(str(msg) or "Ozon отклонил расчёт")
        posting = item.get("posting") or {}
        days = posting.get("estimated_delivery_days")
        return {
            "delivery_sum": money_to_rub(posting.get("estimated_delivery_cost")),
            "insurance_sum": money_to_rub(posting.get("estimated_insurance_cost")),
            "period_min": days if isinstance(days, int) else None,
            "period_max": days if isinstance(days, int) else None,
            "cutoff_at": posting.get("cutoff_at"),
            "request_id": item.get("request_id"),
        }
    raise OzonDeliveryError("Ozon не вернул стоимость доставки")


_DELIVERED = {
    "delivered",
    "given_to_customer",
    "received",
    "received_by_customer",
    "picked_up",
    "issued",
    "posting_delivered",
}
_SHIPPED = {
    "in_transit",
    "on_the_way",
    "sent",
    "shipped",
    "delivering",
    "in_delivery",
    "at_pickup_point",
    "arrived",
    "accepted",
    "in_process",
    "awaiting_deliver",
    "awaiting_delivery",
}


def map_status(code: str | None) -> str | None:
    """Код Ozon → shipped / delivered. Создание и отмену не двигаем сами."""
    raw = (code or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return None
    if raw in _DELIVERED or raw.endswith("_delivered"):
        return "delivered"
    if raw in _SHIPPED or "transit" in raw or "delivering" in raw:
        return "shipped"
    return None


def extract_status(data: dict | None) -> str | None:
    """Достать статус из posting/info — поле гуляет по разным ключам."""
    if not isinstance(data, dict):
        return None
    for key in ("status", "posting_status", "state"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    posting = data.get("posting")
    if isinstance(posting, dict):
        found = extract_status(posting)
        if found:
            return found
    postings = data.get("postings")
    if isinstance(postings, list) and postings and isinstance(postings[0], dict):
        return extract_status(postings[0])
    return None


def _city_haystack(point: dict) -> str:
    parts = [
        point.get("full_address"),
        point.get("address"),
        point.get("name"),
        point.get("city"),
    ]
    return " ".join(str(p) for p in parts if p).lower().replace("ё", "е")


def _city_matches(query: str, point: dict) -> bool:
    q = (query or "").strip().lower().replace("ё", "е")
    if not q:
        return True
    hay = _city_haystack(point)
    if q in hay:
        return True
    digits = re.sub(r"\D", "", q)
    return len(digits) == 6 and digits in hay


# ── API ────────────────────────────────────────────────
async def check_client(cfg: dict, phone: str) -> bool:
    data = await _request(
        cfg, "/v1/delivery/check-client", {"phone_number": normalize_phone(phone)}
    )
    value = data.get("can_be_delivered")
    if not isinstance(value, bool):
        raise OzonDeliveryError("Ozon вернул некорректный check-client")
    return value


async def list_delivery_points(cfg: dict, *, cursor: str | None = None, limit: int = 100) -> dict:
    if cursor == "":
        cursor = None
    limit = max(1, min(int(limit), 100))
    data = await _request(
        cfg,
        "/v1/delivery-point/list",
        {"pagination": {"cursor": cursor, "limit": limit}},
    )
    points = []
    for item in data.get("delivery_points") or []:
        if not isinstance(item, dict):
            continue
        point_id = item.get("delivery_point_id")
        if isinstance(point_id, bool) or not isinstance(point_id, int):
            continue
        methods = item.get("shipment_method_ids") or []
        if isinstance(methods, int):
            methods = [methods]
        if not isinstance(methods, list):
            methods = []
        points.append({"delivery_point_id": point_id, "shipment_method_ids": methods})
    next_cursor = data.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        next_cursor = None
    return {"delivery_points": points, "next_cursor": next_cursor}


async def delivery_points_info(cfg: dict, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    data = await _request(
        cfg, "/v1/delivery-point/info", {"delivery_point_ids": [int(x) for x in ids[:100]]}
    )
    out: list[dict] = []
    for item in data.get("delivery_points") or []:
        if not isinstance(item, dict):
            continue
        point_id = item.get("delivery_point_id")
        if not isinstance(point_id, int):
            continue
        coords = item.get("coordinates") if isinstance(item.get("coordinates"), dict) else {}
        out.append(
            {
                "delivery_point_id": point_id,
                "name": item.get("name"),
                "full_address": item.get("full_address"),
                "type": item.get("type"),
                "is_active": item.get("is_active", True),
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
            }
        )
    return out


async def pickup_points(cfg: dict, *, location: str | None = None, limit: int = 30) -> list[dict]:
    """ПВЗ Ozon по городу: list → info, фильтр по методу доставки и адресу."""
    method_id = 0
    try:
        method_id = _shipment_method_id(cfg)
    except OzonDeliveryError:
        method_id = 0
    want = max(1, min(int(limit), 100))
    found: list[dict] = []
    cursor: str | None = None
    for _ in range(25):
        page = await list_delivery_points(cfg, cursor=cursor, limit=100)
        ids: list[int] = []
        for row in page["delivery_points"]:
            methods = row.get("shipment_method_ids") or []
            if method_id and method_id not in methods:
                continue
            ids.append(row["delivery_point_id"])
        if ids:
            for info in await delivery_points_info(cfg, ids):
                if info.get("is_active") is False:
                    continue
                if not _city_matches(location or "", info):
                    continue
                found.append(
                    {
                        "id": str(info["delivery_point_id"]),
                        "name": info.get("name"),
                        "address": info.get("full_address"),
                        "type": info.get("type"),
                        "city": None,
                        "postal_code": None,
                        "latitude": info.get("latitude"),
                        "longitude": info.get("longitude"),
                    }
                )
                if len(found) >= want:
                    return found[:want]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return found[:want]


async def checkout(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_phone: str,
    delivery_point_id: int,
) -> dict:
    body = build_checkout(
        cfg,
        order_id=order_id,
        item_price_rub=item_price_rub,
        recipient_phone=recipient_phone,
        delivery_point_id=delivery_point_id,
    )
    return parse_checkout(await _request(cfg, "/v1/order/checkout", body))


async def create_order(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_name: str,
    recipient_phone: str,
    delivery_point_id: int,
    cutoff_at: str | None = None,
) -> dict:
    body = build_create(
        cfg,
        order_id=order_id,
        item_price_rub=item_price_rub,
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        delivery_point_id=delivery_point_id,
        cutoff_at=cutoff_at,
    )
    data = await _request(cfg, "/v1/order/create", body, idempotency_key=idempotency_key(order_id))
    postings = data.get("postings") or []
    first = postings[0] if postings and isinstance(postings[0], dict) else {}
    order_number = data.get("order_number")
    posting_number = first.get("posting_number")
    if not (order_number or posting_number):
        raise OzonDeliveryError("Ozon не вернул номер отправления")
    return {
        "order_number": order_number,
        "posting_number": posting_number,
        "request_id": first.get("request_id"),
        "tracking_code": posting_number or order_number,
    }


async def posting_info(cfg: dict, posting_number: str) -> dict:
    return await _request(cfg, "/v1/posting/info", {"posting_number": posting_number})


async def cancel(cfg: dict, posting_number: str) -> dict:
    data = await _request(cfg, "/v1/posting/cancel", {"posting_number": posting_number})
    return data if isinstance(data, dict) else {"ok": True}


async def generate_label(cfg: dict, posting_number: str) -> bytes:
    raw = await _request(cfg, "/v1/posting/label", {"posting_number": posting_number}, raw=True)
    if isinstance(raw, bytes) and raw[:4] == b"%PDF":
        return raw
    if isinstance(raw, bytes):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OzonDeliveryError("ярлык Ozon пришёл не PDF") from e
    else:
        data = raw
    content = None
    if isinstance(data, dict):
        content = data.get("file_content") or data.get("content") or data.get("file")
    if isinstance(content, str):
        import base64

        try:
            return base64.b64decode(content)
        except (ValueError, TypeError) as e:
            raise OzonDeliveryError("ярлык Ozon: некорректный base64") from e
    raise OzonDeliveryError("ярлык Ozon не получен")


async def check_connection(cfg: dict) -> tuple[bool, str]:
    """OAuth + первая страница ПВЗ. Заказов не создаёт."""
    cfg = {
        **cfg,
        "client_id": sanitize_secret(cfg.get("client_id")),
        "client_secret": sanitize_secret(cfg.get("client_secret")),
    }
    if not cfg["client_id"] or not cfg["client_secret"]:
        return False, "задайте Client ID и Client Secret частного приложения Delivery API"
    try:
        page = await list_delivery_points(cfg, cursor=None, limit=1)
    except OzonDeliveryError as e:
        detail = str(e)[:200]
        hint = (
            " Client ID и Client Secret — из ЛК Ozon Доставки → частное приложение "
            "с типом Delivery API (скоуп delivery-api.all), не ключ Seller API."
        )
        return False, f"нет связи: {detail}.{hint}"
    n = len(page.get("delivery_points") or [])
    extra = ""
    method = str(cfg.get("shipment_method_id") or "").strip()
    if not method or method in {"0"}:
        extra = (
            ". Укажите ID метода доставки (под штрих-кодом метода в ЛК) — "
            "без него нельзя рассчитать доставку"
        )
    else:
        extra = f". Метод доставки {method}"
    if n:
        return True, f"связь есть, токен принят. Пункты выдачи доступны{extra}"
    return True, f"токен принят, но список ПВЗ пуст — проверьте договор и метод доставки{extra}"
