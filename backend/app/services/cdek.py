"""СДЭК API v2: расчёт, ПВЗ, регистрация заказа, статус, ярлык.

Создание отправки — `POST /v2/orders`. Тип 1 (интернет-магазин): в местах нужны
товары, `payment.value = 0` — предоплата, доставка входит в постоплату (вариант A).

Локации взаимоисключающие и зависят от тарифа:
- от склада — `shipment_point` (код ПВЗ), `from_location` нельзя;
- от двери — `from_location`;
- до ПВЗ — `delivery_point`, `to_location` нельзя;
- до двери — `to_location`.

Регистрация асинхронная: uuid приходит сразу, ошибки валидации — в
`GET /v2/orders/{uuid}` (`requests[].state = INVALID`).

Песочница: https://api.edu.cdek.ru, прод: https://api.cdek.ru.
Креды — «Настройки → Интеграции». Док: https://api-docs.cdek.ru
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from uuid import UUID

import httpx

PROD = "https://api.cdek.ru"
TEST = "https://api.edu.cdek.ru"

# Габариты коробки под чехол — те же, что для Яндекса.
BOX_CM = (20, 15, 5)

# Посылка: склад-склад / склад-дверь / дверь-склад / дверь-дверь.
TARIFF_WAREHOUSE_WAREHOUSE = 136
TARIFF_WAREHOUSE_DOOR = 137
TARIFF_DOOR_WAREHOUSE = 138
TARIFF_DOOR_DOOR = 139

_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Кэш токенов по (base, account): (token, expires_at).
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


class CdekError(RuntimeError):
    pass


def base_url(is_test: bool) -> str:
    return TEST if is_test else PROD


def is_uuid(value: str) -> bool:
    if not _UUID.match(value or ""):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _error_messages(data: dict) -> list[str]:
    """Ошибки СДЭК лежат в requests[].errors и/или в корневом errors."""
    msgs: list[str] = []
    for req in data.get("requests") or []:
        if not isinstance(req, dict):
            continue
        for err in req.get("errors") or []:
            if isinstance(err, dict):
                msgs.append(str(err.get("message") or err.get("code") or err))
            else:
                msgs.append(str(err))
    for err in data.get("errors") or []:
        if isinstance(err, dict):
            msgs.append(str(err.get("message") or err.get("code") or err))
        else:
            msgs.append(str(err))
    return msgs


def _format_http_error(status: int, text: str) -> str:
    try:
        msgs = _error_messages(json.loads(text))
        if msgs:
            return "; ".join(msgs)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return f"{status} {text[:300]}"


async def _token(base: str, account: str, secret: str) -> str:
    cached = _token_cache.get((base, account))
    if cached and cached[1] > time.time() + 30:
        return cached[0]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{base}/v2/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": account,
                "client_secret": secret,
            },
        )
    if r.status_code != 200:
        raise CdekError(f"авторизация СДЭК: {_format_http_error(r.status_code, r.text)}")
    data = r.json()
    token = data["access_token"]
    _token_cache[(base, account)] = (token, time.time() + int(data.get("expires_in", 3600)))
    return token


async def _request(
    cfg: dict,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    raw: bool = False,
    _retried: bool = False,
) -> Any:
    """`raw=True` — вернуть байты (скачанный PDF ярлыка)."""
    if not cfg.get("account") or not cfg.get("secret"):
        raise CdekError("не заданы account / secret")
    base = base_url(cfg["is_test"])
    token = await _token(base, cfg["account"], cfg["secret"])
    async with httpx.AsyncClient(timeout=60 if raw else 30) as client:
        r = await client.request(
            method,
            f"{base}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
    if r.status_code == 401 and not _retried:
        _token_cache.pop((base, cfg["account"]), None)
        return await _request(
            cfg, method, path, json=json, params=params, raw=raw, _retried=True
        )
    if r.status_code >= 400:
        raise CdekError(f"{path}: {_format_http_error(r.status_code, r.text)}")
    if raw:
        return r.content
    if not r.content:
        return {}
    return r.json()


# ── Сборка заявки ──────────────────────────────────────
def pick_tariff(cfg: dict, *, delivery_point: str | None) -> int:
    """ПВЗ и дверь — разные тарифы; «от склада» только если задан shipment_point."""
    warehouse_from = bool((cfg.get("shipment_point") or "").strip())
    if delivery_point:
        if warehouse_from:
            return int(cfg.get("tariff_pickup") or TARIFF_WAREHOUSE_WAREHOUSE)
        return TARIFF_DOOR_WAREHOUSE
    if warehouse_from:
        return int(cfg.get("tariff_code") or TARIFF_WAREHOUSE_DOOR)
    return TARIFF_DOOR_DOOR


def build_order(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_name: str,
    recipient_phone: str,
    recipient_email: str | None = None,
    delivery_point: str | None = None,
    to_postal: str | None = None,
    to_address: str | None = None,
) -> dict:
    """Тело `POST /v2/orders`. Сеть не трогает — удобно тестировать."""
    if not (delivery_point or to_address):
        raise CdekError("укажите ПВЗ (delivery_point) или адрес (to_address)")
    shipment_point = (cfg.get("shipment_point") or "").strip() or None
    from_address = (cfg.get("from_address") or "").strip() or None
    # Индекса склада недостаточно: тарифы «от склада» требуют код ПВЗ, «от двери» — улицу.
    if not shipment_point and not from_address:
        raise CdekError(
            "не задан код ПВЗ отгрузки (shipment_point) — укажите его в «Настройки → Интеграции»"
        )

    length, width, height = BOX_CM
    weight = int(cfg.get("weight") or 300)
    cost = round(float(item_price_rub), 2)
    tariff = pick_tariff(cfg, delivery_point=delivery_point)
    number = f"casetop-{order_id}"

    recipient: dict[str, Any] = {
        "name": recipient_name,
        "phones": [{"number": recipient_phone}],
    }
    if recipient_email:
        recipient["email"] = recipient_email

    sender: dict[str, Any] = {"name": cfg.get("sender_name") or "casetop"}
    if cfg.get("sender_phone"):
        sender["phones"] = [{"number": cfg["sender_phone"]}]

    body: dict[str, Any] = {
        "type": 1,
        "number": number,
        "tariff_code": tariff,
        "recipient": recipient,
        "sender": sender,
        "packages": [
            {
                "number": f"{number}-1",
                "weight": weight,
                "length": length,
                "width": width,
                "height": height,
                "items": [
                    {
                        "name": "Чехол для смартфона",
                        "ware_key": str(order_id),
                        "payment": {"value": 0},
                        "cost": cost,
                        "weight": weight,
                        "amount": 1,
                    }
                ],
            }
        ],
    }

    if shipment_point:
        body["shipment_point"] = shipment_point
    else:
        from_location: dict[str, Any] = {"country_code": "RU", "address": from_address}
        if cfg.get("from_postal"):
            from_location["postal_code"] = cfg["from_postal"]
        body["from_location"] = from_location

    if delivery_point:
        body["delivery_point"] = delivery_point
    else:
        to_location: dict[str, Any] = {"country_code": "RU", "address": to_address}
        if to_postal:
            to_location["postal_code"] = to_postal
        body["to_location"] = to_location
    return body


# ── Калькулятор и локации ──────────────────────────────
async def _from_location(cfg: dict) -> dict:
    """Откуда считать тариф: координаты ПВЗ отгрузки, иначе индекс склада."""
    if cfg.get("shipment_point"):
        point = await get_point(cfg, cfg["shipment_point"])
        loc = (point or {}).get("location") or {}
        if loc.get("city_code"):
            return {"code": loc["city_code"]}
        if loc.get("postal_code"):
            return {"postal_code": loc["postal_code"]}
    if cfg.get("from_postal"):
        return {"postal_code": cfg["from_postal"]}
    if cfg.get("from_address"):
        return {"address": cfg["from_address"], "country_code": "RU"}
    raise CdekError("не задан индекс или ПВЗ отправителя для расчёта")


async def calculate(
    cfg: dict,
    *,
    to_postal: str | None = None,
    to_city_code: int | None = None,
    weight_g: int | None = None,
    tariff_code: int | None = None,
    delivery_point: str | None = None,
) -> dict:
    """Стоимость и срок одного тарифа. Для ПВЗ берём город/индекс точки."""
    to_location: dict[str, Any]
    if delivery_point:
        point = await get_point(cfg, delivery_point)
        if not point:
            raise CdekError(f"ПВЗ «{delivery_point}» не найден")
        loc = point.get("location") or {}
        if loc.get("city_code"):
            to_location = {"code": loc["city_code"]}
        elif loc.get("postal_code"):
            to_location = {"postal_code": loc["postal_code"]}
        else:
            raise CdekError(f"у ПВЗ «{delivery_point}» нет города в ответе СДЭК")
    elif to_city_code is not None:
        to_location = {"code": to_city_code}
    elif to_postal:
        to_location = {"postal_code": to_postal}
    else:
        raise CdekError("для расчёта нужен индекс, город или ПВЗ получателя")

    length, width, height = BOX_CM
    tariff = tariff_code or pick_tariff(cfg, delivery_point=delivery_point)
    body = {
        "type": 1,
        "from_location": await _from_location(cfg),
        "to_location": to_location,
        "packages": [
            {
                "weight": weight_g or int(cfg.get("weight") or 300),
                "length": length,
                "width": width,
                "height": height,
            }
        ],
        "tariff_code": tariff,
    }
    data = await _request(cfg, "POST", "/v2/calculator/tariff", json=body)
    errs = _error_messages(data)
    if errs:
        raise CdekError("; ".join(errs))
    return {
        "delivery_sum": float(data.get("delivery_sum") or data.get("total_sum") or 0),
        "period_min": data.get("period_min"),
        "period_max": data.get("period_max"),
        "tariff_code": tariff,
    }


def _point_out(raw: dict) -> dict:
    loc = raw.get("location") or {}
    return {
        "id": raw.get("code"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "address": loc.get("address_full") or loc.get("address"),
        "city": loc.get("city"),
        "postal_code": loc.get("postal_code"),
        "work_time": raw.get("work_time"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
    }


async def cities(cfg: dict, query: str, *, size: int = 5) -> list[dict]:
    """Поиск населённого пункта СДЭК по названию или индексу."""
    params: dict[str, Any] = {"country_codes": "RU", "size": size}
    if query.isdigit():
        params["postal_code"] = query
    else:
        params["city"] = query
    data = await _request(cfg, "GET", "/v2/location/cities", params=params)
    if isinstance(data, dict):
        data = data.get("cities") or []
    return data if isinstance(data, list) else []


async def get_point(cfg: dict, code: str) -> dict | None:
    """Одна точка выдачи по коду ПВЗ/постамата."""
    data = await _request(cfg, "GET", "/v2/deliverypoints", params={"code": code})
    points = data if isinstance(data, list) else data.get("delivery_points") or []
    return points[0] if points else None


async def pickup_points(
    cfg: dict, *, location: str | None = None, postal_code: str | None = None, limit: int = 30
) -> list[dict]:
    """ПВЗ, куда можно выдать заказ (is_handout). `location` — город или индекс."""
    params: dict[str, Any] = {"type": "PVZ", "is_handout": True, "country_code": "RU"}
    query = (postal_code or location or "").strip()
    if query.isdigit():
        params["postal_code"] = query
    elif query:
        found = await cities(cfg, query, size=1)
        if not found:
            return []
        params["city_code"] = found[0].get("code")
    data = await _request(cfg, "GET", "/v2/deliverypoints", params=params)
    points = data if isinstance(data, list) else data.get("delivery_points") or []
    return [_point_out(p) for p in points[:limit] if p.get("code")]


# ── Заказ ──────────────────────────────────────────────
async def get_order(cfg: dict, identifier: str) -> dict:
    """Заявка по uuid, номеру СДЭК или нашему `casetop-{id}`."""
    ident = (identifier or "").strip()
    if not ident:
        raise CdekError("не передан идентификатор заявки")
    if is_uuid(ident):
        return await _request(cfg, "GET", f"/v2/orders/{ident}")
    key = "cdek_number" if ident.isdigit() else "im_number"
    return await _request(cfg, "GET", "/v2/orders", params={key: ident})


def _request_state(data: dict) -> str | None:
    reqs = data.get("requests") or []
    if reqs and isinstance(reqs[0], dict):
        return reqs[0].get("state")
    return None


async def _wait_processed(cfg: dict, uuid: str, *, attempts: int = 8) -> dict:
    """Дождаться SUCCESSFUL/INVALID: uuid есть сразу, валидация — секундой позже."""
    last: dict = {}
    last_error: CdekError | None = None
    for i in range(attempts):
        try:
            last = await get_order(cfg, uuid)
            last_error = None
        except CdekError as e:
            last_error = e
            if i + 1 < attempts:
                await asyncio.sleep(0.6)
                continue
            raise
        state = _request_state(last)
        if state in {"INVALID", "SUCCESSFUL"}:
            break
        if i + 1 < attempts:
            await asyncio.sleep(0.6)
    if last_error:
        raise last_error
    errs = _error_messages(last)
    if errs:
        raise CdekError("; ".join(errs))
    return last


async def create_order(
    cfg: dict,
    *,
    order_id: int,
    item_price_rub: float,
    recipient_name: str,
    recipient_phone: str,
    recipient_email: str | None = None,
    delivery_point: str | None = None,
    to_postal: str | None = None,
    to_address: str | None = None,
) -> dict:
    """Зарегистрировать отправку. Возвращает uuid и номер накладной, если уже есть."""
    body = build_order(
        cfg,
        order_id=order_id,
        item_price_rub=item_price_rub,
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        recipient_email=recipient_email,
        delivery_point=delivery_point,
        to_postal=to_postal,
        to_address=to_address,
    )
    data = await _request(cfg, "POST", "/v2/orders", json=body)
    errs = _error_messages(data)
    if errs:
        raise CdekError("; ".join(errs))
    uuid = (data.get("entity") or {}).get("uuid")
    if not uuid:
        raise CdekError("СДЭК не вернул uuid заявки")
    info = await _wait_processed(cfg, str(uuid))
    entity = info.get("entity") or {}
    return {
        "uuid": str(uuid),
        "cdek_number": entity.get("cdek_number"),
        "raw": info,
    }


async def delete_order(cfg: dict, identifier: str) -> dict:
    """Отменить заявку. DELETE принимает только uuid — при номере сначала читаем заказ."""
    ident = identifier.strip()
    uuid = ident if is_uuid(ident) else (await get_order(cfg, ident)).get("entity", {}).get("uuid")
    if not uuid:
        raise CdekError("не удалось определить uuid заявки для отмены")
    data = await _request(cfg, "DELETE", f"/v2/orders/{uuid}")
    errs = _error_messages(data)
    if errs:
        raise CdekError("; ".join(errs))
    return {"uuid": str(uuid), "state": _request_state(data)}


def order_info(data: dict) -> dict:
    """Разобрать GET /v2/orders в плоский статус для бота/админки."""
    entity = data.get("entity") or {}
    statuses = entity.get("statuses") or []
    last = statuses[-1] if statuses else {}
    return {
        "uuid": entity.get("uuid"),
        "cdek_number": entity.get("cdek_number"),
        "number": entity.get("number"),
        "status": last.get("code"),
        "status_name": last.get("name"),
        "request_state": _request_state(data),
    }


# ── Статусы СДЭК ───────────────────────────────────────
# Вебхук ORDER_STATUS и GET заказа используют одни и те же коды.
DELIVERED_STATUSES = frozenset({"DELIVERED", "POSTOMAT_RECEIVED"})
SHIPPED_STATUSES = frozenset(
    {
        "RECEIVED_AT_SHIPMENT_WAREHOUSE",
        "READY_FOR_SHIPMENT_IN_SENDER_CITY",
        "READY_TO_SHIP_AT_SENDING_OFFICE",
        "PASSED_TO_CARRIER_AT_SENDING_OFFICE",
        "TAKEN_BY_TRANSPORTER_FROM_SENDER_CITY",
        "SENT_TO_TRANSIT_CITY",
        "ACCEPTED_IN_TRANSIT_CITY",
        "ACCEPTED_AT_TRANSIT_WAREHOUSE",
        "IN_TRANSIT",
        "SENT_TO_RECIPIENT_CITY",
        "ARRIVED_AT_RECIPIENT_CITY",
        "ACCEPTED_IN_RECIPIENT_CITY",
        "ACCEPTED_AT_PICK_UP_POINT",
        "TAKEN_BY_COURIER",
        "POSTOMAT_POSTED",
        "POSTOMAT_SEIZED",
        "ENTERED_TO_DELIVERY_OFFICE",
        "ENTERED_TO_WAREHOUSE_ON_DEMAND",
    }
)


def map_status(status: str | None) -> str | None:
    """Код СДЭК → shipped / delivered / None (заказ не двигаем).

    NOT_DELIVERED и возвраты не отменяют наш заказ — это решение оператора.
    """
    code = (status or "").upper()
    if code in DELIVERED_STATUSES:
        return "delivered"
    if code in SHIPPED_STATUSES:
        return "shipped"
    return None


# ── Ярлык ──────────────────────────────────────────────
async def generate_label(cfg: dict, identifier: str, *, fmt: str = "A4") -> bytes:
    """PDF штрихкода места. Без него посылку не примут на складе СДЭК.

    Печать тоже асинхронная: сначала uuid задания, потом `entity.url`.
    """
    order = {"order_uuid": identifier} if is_uuid(identifier) else {"cdek_number": identifier}
    created = await _request(
        cfg,
        "POST",
        "/v2/print/barcodes",
        json={"orders": [order], "copy_count": 1, "format": fmt, "lang": "RUS"},
    )
    errs = _error_messages(created)
    if errs:
        raise CdekError("; ".join(errs))
    job_uuid = (created.get("entity") or {}).get("uuid")
    if not job_uuid:
        raise CdekError("СДЭК не вернул uuid задания печати")

    url = None
    for i in range(10):
        info = await _request(cfg, "GET", f"/v2/print/barcodes/{job_uuid}")
        entity = info.get("entity") or {}
        url = entity.get("url")
        codes = {(s.get("code") or "").upper() for s in (entity.get("statuses") or [])}
        if url:
            break
        if "INVALID" in codes or "REMOVED" in codes:
            raise CdekError(_error_messages(info)[0] if _error_messages(info) else "ярлык отклонён")
        if i < 9:
            await asyncio.sleep(0.5)
    if not url:
        raise CdekError("ярлык ещё формируется — повторите через несколько секунд")

    if url.startswith("/"):
        url = f"{base_url(cfg['is_test'])}{url}"
    token = await _token(base_url(cfg["is_test"]), cfg["account"], cfg["secret"])
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise CdekError(f"скачивание ярлыка: {r.status_code} {r.text[:200]}")
    return r.content


# ── Проба связи ────────────────────────────────────────
async def check_connection(cfg: dict) -> tuple[bool, str]:
    """OAuth + чтение справочника городов. Заказов не создаёт."""
    mode = "тест" if cfg["is_test"] else "продакшен"
    try:
        found = await cities(cfg, "Москва", size=1)
    except CdekError as e:
        detail = str(e)[:160]
        if "401" in detail or "авторизация" in detail:
            hint = (
                ". В тестовом режиме нужны ключи песочницы из ЛК СДЭК → Интеграция, "
                "не account/secure от боевого договора"
                if cfg["is_test"]
                else ""
            )
            return False, f"креды отклонены ({mode}): {detail}{hint}"
        return False, f"нет связи ({mode}): {detail}"
    if not found:
        return False, f"токен принят ({mode}), но справочник городов пуст — проверьте договор"
    city = found[0].get("city") or found[0].get("code") or "Москва"
    extra = ""
    if cfg.get("shipment_point"):
        try:
            point = await get_point(cfg, cfg["shipment_point"])
        except CdekError as e:
            extra = f". ПВЗ отгрузки {cfg['shipment_point']}: {e}"
        else:
            extra = (
                f". ПВЗ отгрузки {cfg['shipment_point']} найден"
                if point
                else f". ПВЗ отгрузки {cfg['shipment_point']} не найден — проверьте код"
            )
    else:
        extra = (
            ". Задайте код ПВЗ отгрузки (shipment_point) — "
            "без него тариф склад-дверь не создастся"
        )
    return True, f"связь есть, токен принят ({mode}). Город: {city}{extra}"
