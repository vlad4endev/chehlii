"""СДЭК API v2: авторизация (OAuth client_credentials), расчёт тарифа, заявка, статус.

Песочница: https://api.edu.cdek.ru, прод: https://api.cdek.ru.
Креды берутся из «Настройки → Интеграции» (cdek.account, cdek.secret, cdek.test).
Док: https://api-docs.cdek.ru
"""

from __future__ import annotations

import time
from typing import Any

import httpx

PROD = "https://api.cdek.ru"
TEST = "https://api.edu.cdek.ru"

# Кэш токенов по (base, account): (token, expires_at).
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


class CdekError(RuntimeError):
    pass


def base_url(is_test: bool) -> str:
    return TEST if is_test else PROD


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
        raise CdekError(f"авторизация СДЭК: {r.status_code} {r.text[:200]}")
    data = r.json()
    token = data["access_token"]
    _token_cache[(base, account)] = (token, time.time() + int(data.get("expires_in", 3600)))
    return token


async def _request(
    cfg: dict, method: str, path: str, *, json: dict | None = None, params: dict | None = None
) -> Any:
    base = base_url(cfg["is_test"])
    token = await _token(base, cfg["account"], cfg["secret"])
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(
            method,
            f"{base}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
    if r.status_code >= 400:
        raise CdekError(f"СДЭК {path}: {r.status_code} {r.text[:300]}")
    return r.json()


async def calculate(
    cfg: dict, *, to_postal: str, weight_g: int, tariff_code: int
) -> dict:
    """Расчёт стоимости и срока доставки до индекса получателя (один тариф)."""
    body = {
        "type": 1,  # интернет-магазин
        "from_location": {"postal_code": cfg["from_postal"]},
        "to_location": {"postal_code": to_postal},
        "packages": [{"weight": weight_g, "length": 20, "width": 15, "height": 5}],
        "tariff_code": tariff_code,
    }
    data = await _request(cfg, "POST", "/v2/calculator/tariff", json=body)
    return {
        "delivery_sum": float(data.get("delivery_sum") or data.get("total_sum") or 0),
        "period_min": data.get("period_min"),
        "period_max": data.get("period_max"),
        "tariff_code": tariff_code,
    }


async def create_order(cfg: dict, *, order_id: int, to_postal: str, to_address: str,
                       recipient_name: str, recipient_phone: str, weight_g: int,
                       tariff_code: int) -> dict:
    """Создать заявку на доставку. Возвращает uuid заявки СДЭК."""
    body = {
        "type": 1,
        "number": f"casetop-{order_id}",
        "tariff_code": tariff_code,
        "from_location": {"postal_code": cfg["from_postal"]},
        "to_location": {"postal_code": to_postal, "address": to_address},
        "recipient": {"name": recipient_name, "phones": [{"number": recipient_phone}]},
        "sender": {"name": cfg.get("sender_name") or "casetop"},
        "packages": [
            {
                "number": f"casetop-{order_id}-1",
                "weight": weight_g,
                "length": 20,
                "width": 15,
                "height": 5,
                "items": [
                    {
                        "name": "Чехол для смартфона",
                        "ware_key": str(order_id),
                        "payment": {"value": 0},
                        "cost": 0,
                        "weight": weight_g,
                        "amount": 1,
                    }
                ],
            }
        ],
    }
    data = await _request(cfg, "POST", "/v2/orders", json=body)
    return {"uuid": (data.get("entity") or {}).get("uuid"), "raw": data}


async def get_order(cfg: dict, uuid: str) -> dict:
    return await _request(cfg, "GET", f"/v2/orders/{uuid}")
