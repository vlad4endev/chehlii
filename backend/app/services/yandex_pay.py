"""Яндекс Пэй (Merchant API v1): ссылка оплаты, статус заказа, списание, разбор вебхука.

Ссылка: POST /orders → `data.paymentUrl`; заказ у Пэй идентифицируем нашим `payments.id`.
Вебхук приходит телом-JWT (ES256, `application/octet-stream`). Подпись не проверяем
намеренно: из тела берём только `orderId`, а статус перечитываем авторизованным
GET /orders/{id} — источник истины наш собственный запрос, его не подделать. Так не
нужны JWKS, кэш ключей и ротация `kid`, а подделанный вебхук стоит один лишний запрос.

Двухстадийность: `AUTHORIZED` = деньги захолдированы, но не списаны — без `capture`
холд снимется и оплата не состоится. `CAPTURED`/`CONFIRMED` — деньги у нас.

Ключ авторизации: `Authorization: Api-Key <ключ>`, ключ выпускается в ЛК; в песочнице
вместо него принимается сам merchant_id.
Суммы — строки с двумя знаками («1234.56»), валюта RUB.
Док: https://pay.yandex.ru/docs/ru/custom/integration-guide-link
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

PROD = "https://pay.yandex.ru/api/merchant/v1"
SANDBOX = "https://sandbox.pay.yandex.ru/api/merchant/v1"

# Границы ttl ссылки по документации (2 минуты … 7 суток).
TTL_MIN, TTL_MAX = 120, 604800

# Идентификатор для пробы связи: такого заказа у нас никогда нет.
PROBE_ORDER_ID = "casetop-connection-probe"

# Статусы, при которых деньги фактически получены.
PAID_STATUSES = {"CAPTURED", "CONFIRMED"}
FAILED_STATUSES = {"FAILED", "VOIDED"}


class YandexPayError(RuntimeError):
    """Ошибка Пэй. `reason_code`/`status_code` нужны, чтобы отличать причины без разбора текста."""

    def __init__(self, message: str, *, status_code: int | None = None, reason_code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code


def base_url(is_test: bool) -> str:
    return SANDBOX if is_test else PROD


def _money(rub: float) -> str:
    return f"{float(rub):.2f}"


async def _request(cfg: dict, method: str, path: str, *, json_body: dict | None = None) -> dict:
    if not cfg.get("api_key"):
        raise YandexPayError("не задан API-ключ Яндекс Пэй")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(
            method,
            f"{base_url(cfg['is_test'])}{path}",
            headers={"Authorization": f"Api-Key {cfg['api_key']}"},
            json=json_body,
        )
    if r.status_code >= 400:
        try:
            reason_code = str(r.json().get("reasonCode") or "")
        except ValueError:
            reason_code = ""
        raise YandexPayError(
            f"{path}: {r.status_code} {r.text[:300]}",
            status_code=r.status_code,
            reason_code=reason_code,
        )
    data = r.json()
    if data.get("status") != "success":
        raise YandexPayError(f"{path}: {str(data)[:300]}")
    return data.get("data") or {}


def build_order(
    *,
    order_id: str,
    amount: float,
    title: str,
    ttl_seconds: int,
    redirect_base: str | None = None,
) -> dict:
    """Тело POST /orders. Одна позиция на весь платёж — чек формирует Пэй по cart.

    `availablePaymentMethods` не передаём: набор способов (карта, Сплит) задаётся в ЛК,
    а перечисление недоступного метода в запросе ломает создание заказа.
    """
    total = _money(amount)
    body: dict[str, Any] = {
        "orderId": order_id,
        "currencyCode": "RUB",
        "cart": {
            "externalId": order_id,
            "items": [
                {
                    "productId": order_id,
                    "title": title[:2048],
                    "quantity": {"count": "1"},
                    "unitPrice": total,
                    "total": total,
                }
            ],
            "total": {"amount": total},
        },
        "ttl": max(TTL_MIN, min(TTL_MAX, int(ttl_seconds))),
    }
    if redirect_base:
        base = redirect_base.rstrip("/")
        body["redirectUrls"] = {
            "onSuccess": f"{base}/api/v1/payments/success",
            "onError": f"{base}/api/v1/payments/fail",
            "onAbort": f"{base}/api/v1/payments/fail",
        }
    return body


async def create_order(cfg: dict, body: dict) -> str:
    """Создать заказ → ссылка на форму оплаты."""
    data = await _request(cfg, "POST", "/orders", json_body=body)
    url = data.get("paymentUrl")
    if not url:
        raise YandexPayError("Пэй не вернул paymentUrl")
    return str(url)


async def order_status(cfg: dict, order_id: str) -> str:
    """Актуальный `paymentStatus` заказа — источник истины при обработке вебхука."""
    data = await _request(cfg, "GET", f"/orders/{order_id}")
    return str(((data.get("order") or {}).get("paymentStatus")) or "")


async def capture(cfg: dict, order_id: str, amount: float) -> str:
    """Списать захолдированную сумму (статус AUTHORIZED) → статус операции."""
    data = await _request(
        cfg, "POST", f"/orders/{order_id}/capture", json_body={"orderAmount": _money(amount)}
    )
    return str(((data.get("operation") or {}).get("status")) or "")


async def check_connection(cfg: dict) -> tuple[bool, str]:
    """Статус связи с Пэй без побочных эффектов: запрос заведомо несуществующего заказа.

    404 ORDER_NOT_FOUND_ERROR = связь есть и ключ принят; 401 AUTHENTICATION_ERROR =
    ключ не тот (частый случай — прод-ключ в песочнице). Заказов при проверке не
    создаём, иначе в ЛК копился бы мусор.
    """
    mode = "песочница" if cfg["is_test"] else "продакшен"
    try:
        await order_status(cfg, PROBE_ORDER_ID)
    except YandexPayError as e:
        if e.status_code == 404 or e.reason_code.startswith("ORDER_NOT_FOUND"):
            return True, f"связь есть, ключ принят ({mode})"
        if e.reason_code == "AUTHENTICATION_ERROR":
            return False, f"ключ отклонён ({mode}): {e.args[0].split(': ', 1)[-1][:160]}"
        return False, str(e)[:200]
    return True, f"связь есть, ключ принят ({mode})"


def webhook_payload(body: bytes) -> dict:
    """Тело вебхука (JWT) → payload без проверки подписи (см. docstring модуля)."""
    try:
        segment = body.decode().strip().split(".")[1]
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        payload = json.loads(raw)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        raise YandexPayError("не удалось разобрать тело вебхука Яндекс Пэй") from e
    if not isinstance(payload, dict):
        raise YandexPayError("неожиданный формат вебхука Яндекс Пэй")
    return payload
