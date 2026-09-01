"""Тесты Яндекс Пэй: формат сумм, ttl ссылки и разбор тела-JWT вебхука.

Сеть не трогаем. Проверяем то, что ломается молча: сумма строкой с двумя знаками
(иначе Пэй отклонит заказ), ttl в допустимых границах и base64url без паддинга
в payload вебхука — на нём легко потерять оплату.
"""

import asyncio
import base64
import json

import pytest

from app.services import yandex_pay as yp


def _order(**over):
    kwargs = {"order_id": "42", "amount": 1234.5, "title": "casetop заказ #7", "ttl_seconds": 3600}
    kwargs.update(over)
    return yp.build_order(**kwargs)


def test_amounts_are_two_decimal_strings():
    body = _order()
    item = body["cart"]["items"][0]
    assert body["cart"]["total"] == {"amount": "1234.50"}
    assert item["total"] == "1234.50"
    assert item["unitPrice"] == "1234.50"


def test_ttl_is_clamped_to_api_limits():
    assert _order(ttl_seconds=10)["ttl"] == yp.TTL_MIN
    assert _order(ttl_seconds=10**9)["ttl"] == yp.TTL_MAX


def test_redirect_urls_only_when_public_base_known():
    assert "redirectUrls" not in _order()
    urls = _order(redirect_base="https://casetop.example.ru/")["redirectUrls"]
    assert urls["onSuccess"] == "https://casetop.example.ru/api/v1/payments/success"
    assert urls["onError"].endswith("/api/v1/payments/fail")


def _jwt(payload: dict) -> bytes:
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")

    return seg({"alg": "ES256", "kid": "k1"}) + b"." + seg(payload) + b".signature"


def test_webhook_payload_survives_missing_base64_padding():
    payload = {"event": "ORDER_STATUS_UPDATED", "order": {"orderId": "42"}}
    assert yp.webhook_payload(_jwt(payload)) == payload


def test_webhook_payload_rejects_garbage():
    with pytest.raises(yp.YandexPayError):
        yp.webhook_payload(b"not-a-jwt")


def _check(monkeypatch, error: Exception | None, *, is_test=True) -> tuple[bool, str]:
    """Проба связи с подменённым order_status — сеть не трогаем."""
    seen: list[str] = []

    async def fake_order_status(cfg, order_id):
        seen.append(order_id)
        if error is not None:
            raise error
        return "PENDING"

    monkeypatch.setattr(yp, "order_status", fake_order_status)
    result = asyncio.run(yp.check_connection({"api_key": "k", "is_test": is_test}))
    assert seen == [yp.PROBE_ORDER_ID], "проба не должна трогать реальные заказы"
    return result


def test_unknown_order_means_key_accepted(monkeypatch):
    # Валидный ключ + несуществующий заказ = 404 ORDER_NOT_FOUND_ERROR (проверено на песочнице).
    err = yp.YandexPayError("404", status_code=404, reason_code="ORDER_NOT_FOUND_ERROR")
    ok, detail = _check(monkeypatch, err)
    assert ok and "песочница" in detail


def test_rejected_key_means_no_link(monkeypatch):
    err = yp.YandexPayError(
        "/orders: 401 Malformed API key", status_code=401, reason_code="AUTHENTICATION_ERROR"
    )
    ok, detail = _check(monkeypatch, err, is_test=False)
    assert not ok
    assert "продакшен" in detail


def test_network_error_means_no_link(monkeypatch):
    ok, _ = _check(monkeypatch, yp.YandexPayError("connect timeout"))
    assert not ok
