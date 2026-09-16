"""Тесты Ozon Доставки: sanitize, OAuth expiry, сборка заявки. Сеть не трогаем."""

import time
from uuid import UUID

import pytest

from app.services import ozon_delivery as ozon

CFG = {
    "client_id": "11111111-1111-1111-1111-111111111111",
    "client_secret": "sec",
    "shipment_method_id": "12345",
    "weight": 300,
}


def test_schema_exposes_ozon_group():
    from app.services.integrations import ALL_KEYS, SECRET_KEYS

    assert "ozon.client_id" in ALL_KEYS
    assert "ozon.client_secret" in SECRET_KEYS
    assert "ozon.shipment_method_id" in ALL_KEYS
    assert ozon.sanitize_secret('  "abc123" \n') == "abc123"
    assert ozon.sanitize_secret("ab cd") == "abcd"
    assert ozon.sanitize_secret("") == ""


def test_normalize_phone_accepts_russian_formats():
    assert ozon.normalize_phone("89990000000") == "+79990000000"
    assert ozon.normalize_phone("+7 999 000-00-00") == "+79990000000"
    assert ozon.normalize_phone("7 (999) 000 00 00") == "+79990000000"


def test_normalize_phone_rejects_short():
    with pytest.raises(ozon.OzonDeliveryError, match="телефон"):
        ozon.normalize_phone("123")


def test_money_amount_never_zero():
    assert ozon.money_amount(0) == "1.00"
    assert ozon.money_amount(1234.567) == "1234.57"


def test_parse_expires_at_absolute_unix():
    now = 1_800_000_000.0
    assert ozon.parse_expires_at(now + 3600, now=now) == now + 3600


def test_parse_expires_at_ttl_seconds_fallback():
    now = 1_800_000_000.0
    assert ozon.parse_expires_at(3600, now=now) == now + 3600


def test_parse_expires_at_rejects_short_ttl():
    with pytest.raises(ozon.OzonDeliveryError, match="срок"):
        ozon.parse_expires_at(10, now=time.time())


def test_idempotency_key_is_stable_uuid():
    a = ozon.idempotency_key(42)
    b = ozon.idempotency_key(42)
    assert a == b
    assert isinstance(a, UUID)
    assert a != ozon.idempotency_key(43)


def test_checkout_body_uses_pvz_and_declared_value():
    body = ozon.build_checkout(
        CFG,
        order_id=42,
        item_price_rub=1234.56,
        recipient_phone="89990000000",
        delivery_point_id=999,
        cutoff_at="2030-01-02T12:00:00Z",
    )
    assert body["recipient"]["phone_number"] == "+79990000000"
    assert body["delivery"]["delivery_point"]["delivery_point_id"] == 999
    posting = body["postings"][0]
    assert posting["request_id"] == 42
    assert posting["shipment_method_id"] == 12345
    assert posting["declared_value"] == {"amount": "1234.56", "currency_code": "RUB"}
    assert posting["dimensions"]["weight_g"] == 300
    assert posting["dimensions"]["length_mm"] == 200


def test_create_body_adds_external_id_and_name():
    body = ozon.build_create(
        CFG,
        order_id=42,
        item_price_rub=100,
        recipient_name="Иван Петров",
        recipient_phone="+79990000000",
        delivery_point_id=7,
        cutoff_at="2030-01-02T12:00:00Z",
    )
    assert body["order_external_id"] == "casetop-42"
    assert body["recipient"]["full_name"] == "Иван Петров"
    assert body["postings"][0]["posting_external_id"] == "casetop-42-1"
    assert body["postings"][0]["description"] == "Чехол для смартфона"


def test_missing_shipment_method_is_rejected():
    with pytest.raises(ozon.OzonDeliveryError, match="метода доставки"):
        ozon.build_checkout(
            {**CFG, "shipment_method_id": None},
            order_id=1,
            item_price_rub=100,
            recipient_phone="+79990000000",
            delivery_point_id=1,
        )


def test_parse_checkout_reads_money_and_days():
    parsed = ozon.parse_checkout(
        {
            "results": [
                {
                    "request_id": 42,
                    "posting": {
                        "estimated_delivery_cost": {"amount": "290.50", "currency_code": "RUB"},
                        "estimated_delivery_days": 3,
                        "cutoff_at": "2030-01-02T12:00:00Z",
                    },
                }
            ]
        }
    )
    assert parsed["delivery_sum"] == 290.5
    assert parsed["period_min"] == parsed["period_max"] == 3


def test_parse_checkout_raises_on_error():
    with pytest.raises(ozon.OzonDeliveryError, match="нет ПВЗ"):
        ozon.parse_checkout({"results": [{"request_id": 1, "error": {"message": "нет ПВЗ"}}]})


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("delivered", "delivered"),
        ("POSTING_DELIVERED", "delivered"),
        ("in_transit", "shipped"),
        ("awaiting_deliver", "shipped"),
        ("created", None),
        ("cancelled", None),
        (None, None),
    ],
)
def test_map_status(code, expected):
    assert ozon.map_status(code) == expected


def test_city_filter_matches_address():
    point = {"full_address": "г. Казань, ул. Баумана 1", "name": "ПВЗ 1"}
    assert ozon._city_matches("Казань", point)
    assert not ozon._city_matches("Москва", point)


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "", headers=None, content=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        if content is not None:
            self.content = content
            self.text = text or ""
        else:
            self.content = b"{}" if payload is not None else b""
            self.text = text or ("Access denied" if status_code >= 400 else "")

    def json(self):
        return self._payload


def _fake_client(routes: dict[str, _FakeResponse | list], monkeypatch):
    ozon._token_cache.clear()
    hits: dict[str, int] = dict.fromkeys(routes, 0)

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            for path, resp in sorted(routes.items(), key=lambda kv: -len(kv[0])):
                if path in url:
                    hits[path] += 1
                    if isinstance(resp, list):
                        idx = min(hits[path] - 1, len(resp) - 1)
                        return resp[idx]
                    return resp
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(ozon.httpx, "AsyncClient", Client)
    return hits


async def test_check_connection_ok(monkeypatch):
    _fake_client(
        {
            "/oauth/token": _FakeResponse(
                200, {"access_token": "t", "expires_in": time.time() + 3600}
            ),
            "/v1/delivery-point/list": _FakeResponse(
                200, {"delivery_points": [{"delivery_point_id": 1, "shipment_method_ids": [12345]}]}
            ),
        },
        monkeypatch,
    )
    ok, detail = await ozon.check_connection(CFG)
    assert ok is True
    assert "токен принят" in detail
    assert "12345" in detail


async def test_check_connection_bad_secret(monkeypatch):
    _fake_client(
        {"/oauth/token": _FakeResponse(401, {"message": "invalid_client"}, text="invalid_client")},
        monkeypatch,
    )
    ok, detail = await ozon.check_connection(CFG)
    assert ok is False
    assert "частное приложение" in detail


async def test_check_connection_follows_testcookie_redirect(monkeypatch):
    _fake_client(
        {
            "/oauth/token": _FakeResponse(
                200, {"access_token": "t", "expires_in": time.time() + 3600}
            ),
            "/v1/delivery-point/list": [
                _FakeResponse(
                    307,
                    headers={"location": "https://api-delivery.ozon.ru/v1/delivery-point/list"},
                ),
                _FakeResponse(200, {"delivery_points": []}),
            ],
        },
        monkeypatch,
    )
    ok, detail = await ozon.check_connection(CFG)
    assert ok is True
    assert "список ПВЗ пуст" in detail
