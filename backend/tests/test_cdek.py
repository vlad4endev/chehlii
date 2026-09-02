"""Тесты сборки заявки СДЭК: локации тарифа и объявленная стоимость.

Сеть не трогаем — проверяем чистые функции (то, что легко сломать молча:
shipment_point вместо from_location, оба поля сразу, cost=0).
"""

import pytest

from app.services import cdek

CFG = {
    "account": "acc",
    "secret": "sec",
    "is_test": True,
    "shipment_point": "MSK1",
    "from_postal": "101000",
    "tariff_code": 137,
    "tariff_pickup": 136,
    "weight": 300,
    "sender_name": "casetop",
    "sender_phone": "+79991112233",
}


def _build(**over):
    kwargs = {
        "order_id": 42,
        "item_price_rub": 1234.56,
        "recipient_name": "Иван Петров",
        "recipient_phone": "+79990000000",
        "to_postal": "630000",
        "to_address": "Новосибирск, Красный проспект 1",
    }
    kwargs.update(over)
    return cdek.build_order(CFG, **kwargs)


def test_door_uses_shipment_point_not_from_location():
    # Тариф 137 склад-дверь: from_location вместе с ПВЗ отгрузки СДЭК отвергает.
    body = _build()
    assert body["type"] == 1
    assert body["tariff_code"] == 137
    assert body["shipment_point"] == "MSK1"
    assert "from_location" not in body
    assert body["to_location"]["address"] == "Новосибирск, Красный проспект 1"
    assert body["to_location"]["postal_code"] == "630000"
    assert "delivery_point" not in body


def test_pickup_point_becomes_delivery_point_and_warehouse_tariff():
    body = _build(delivery_point="NSK12", to_address=None, to_postal=None)
    assert body["tariff_code"] == 136
    assert body["delivery_point"] == "NSK12"
    assert "to_location" not in body
    assert body["shipment_point"] == "MSK1"


def test_item_cost_is_declared_value_and_payment_is_prepaid():
    # Объявленная стоимость — цена чехла; payment=0, потому что клиент уже платит в боте.
    item = _build()["packages"][0]["items"][0]
    assert item["cost"] == 1234.56
    assert item["payment"] == {"value": 0}
    assert item["ware_key"] == "42"
    assert item["weight"] == 300


def test_package_barcode_matches_order_number():
    body = _build()
    assert body["number"] == "casetop-42"
    assert body["packages"][0]["number"] == "casetop-42-1"
    assert body["packages"][0]["weight"] == 300


def test_sender_and_recipient_phones():
    body = _build()
    assert body["sender"]["phones"] == [{"number": "+79991112233"}]
    assert body["recipient"] == {
        "name": "Иван Петров",
        "phones": [{"number": "+79990000000"}],
    }


def test_recipient_email_optional():
    body = _build(recipient_email="a@b.ru")
    assert body["recipient"]["email"] == "a@b.ru"


def test_missing_shipment_point_is_rejected():
    with pytest.raises(cdek.CdekError, match="ПВЗ отгрузки"):
        cdek.build_order(
            {**CFG, "shipment_point": None},
            order_id=1,
            item_price_rub=100,
            recipient_name="Иван",
            recipient_phone="+79990000000",
            to_address="Москва, Тверская 1",
        )


def test_door_from_uses_from_location_when_no_pvz():
    body = cdek.build_order(
        {**CFG, "shipment_point": "", "from_address": "Москва, Склад 1"},
        order_id=1,
        item_price_rub=100,
        recipient_name="Иван",
        recipient_phone="+79990000000",
        to_address="Новосибирск, Ленина 1",
    )
    assert "shipment_point" not in body
    assert body["from_location"]["address"] == "Москва, Склад 1"
    assert body["tariff_code"] == 139  # без ПВЗ отгрузки — дверь-дверь


def test_destination_required():
    with pytest.raises(cdek.CdekError, match="ПВЗ"):
        _build(delivery_point=None, to_address=None)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("DELIVERED", "delivered"),
        ("postomat_received", "delivered"),
        ("ACCEPTED_AT_PICK_UP_POINT", "shipped"),
        ("RECEIVED_AT_SHIPMENT_WAREHOUSE", "shipped"),
        ("TAKEN_BY_COURIER", "shipped"),
        ("CREATED", None),
        ("NOT_DELIVERED", None),
        (None, None),
    ],
)
def test_map_status(code, expected):
    assert cdek.map_status(code) == expected


def test_is_uuid():
    assert cdek.is_uuid("72753031-a20e-4ba5-9bb8-0c2214c6c4a1")
    assert not cdek.is_uuid("1105084311")
    assert not cdek.is_uuid("casetop-42")


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ("Access denied" if status_code >= 400 else "")
        self.content = b"{}" if payload is not None else b""

    def json(self):
        return self._payload


def _fake_client(routes: dict[str, _FakeResponse], monkeypatch):
    """Подменяет httpx.AsyncClient. Кэш токена сбрасываем — иначе предыдущий тест
    подсунет Bearer и запрос уйдёт мимо /oauth/token."""
    cdek._token_cache.clear()

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            for path, resp in routes.items():
                if path in url:
                    return resp
            raise AssertionError(f"неожиданный запрос: {url}")

        async def post(self, url, **kw):
            return await self.request("POST", url, **kw)

        async def get(self, url, **kw):
            return await self.request("GET", url, **kw)

    monkeypatch.setattr(cdek.httpx, "AsyncClient", Client)


async def test_check_connection_ok(monkeypatch):
    _fake_client(
        {
            "/oauth/token": _FakeResponse(
                200, {"access_token": "t", "expires_in": 3600}
            ),
            "/location/cities": _FakeResponse(200, [{"code": 44, "city": "Москва"}]),
            "/deliverypoints": _FakeResponse(
                200,
                [{"code": "MSK1", "location": {"city_code": 44, "address": "Тверская"}}],
            ),
        },
        monkeypatch,
    )
    ok, detail = await cdek.check_connection(CFG)
    assert ok is True
    assert "Москва" in detail
    assert "MSK1 найден" in detail


async def test_check_connection_bad_token(monkeypatch):
    _fake_client({"/oauth/token": _FakeResponse(401, text="invalid_client")}, monkeypatch)
    ok, detail = await cdek.check_connection(CFG)
    assert ok is False
    assert "песочницы" in detail
