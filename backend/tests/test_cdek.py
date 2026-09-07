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


def test_sanitize_secret_strips_quotes_and_whitespace():
    assert cdek.sanitize_secret('  "abc123" \n') == "abc123"
    assert cdek.sanitize_secret("ab cd") == "abcd"
    assert cdek.sanitize_secret("") == ""


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


def test_casetop_order_id():
    assert cdek.casetop_order_id("casetop-42") == 42
    assert cdek.casetop_order_id("casetop-42-1") is None
    assert cdek.casetop_order_id("42") is None
    assert cdek.casetop_order_id("1105084311") is None
    assert cdek.casetop_order_id("") is None
    assert cdek.casetop_order_id(None) is None


def test_iter_webhook_events_object_and_array():
    one = {"type": "ORDER_STATUS", "uuid": "u1", "attributes": {"code": "DELIVERED"}}
    assert cdek.iter_webhook_events(one) == [one]
    many = [one, {"type": "PRINT_FORM"}]
    assert cdek.iter_webhook_events(many) == many
    wrapped = {"events": [one]}
    assert cdek.iter_webhook_events(wrapped) == [one]
    assert cdek.iter_webhook_events("nope") == []


def test_webhook_finds_order_by_uuid_when_number_missing():
    event = {
        "type": "ORDER_STATUS",
        "uuid": "72753031-a20e-4ba5-9bb8-0c2214c6c4a1",
        "attributes": {
            "cdek_number": "1100285492",
            "code": "RECEIVED_AT_SHIPMENT_WAREHOUSE",
        },
    }
    assert cdek.webhook_status_code(event) == "RECEIVED_AT_SHIPMENT_WAREHOUSE"
    assert cdek.map_status(cdek.webhook_status_code(event)) == "shipped"
    assert cdek.casetop_order_id((event["attributes"]).get("number")) is None
    ids = cdek.webhook_track_ids(event)
    assert "72753031-a20e-4ba5-9bb8-0c2214c6c4a1" in ids
    assert "1100285492" in ids


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
            # Длинный ключ первым: различаем api.edu.cdek.ru и api.cdek.ru.
            for path, resp in sorted(routes.items(), key=lambda kv: -len(kv[0])):
                if path in url:
                    return resp
            raise AssertionError(f"неожиданный запрос: {url}")

        async def post(self, url, **kw):
            return await self.request("POST", url, **kw)

        async def get(self, url, **kw):
            return await self.request("GET", url, **kw)

    monkeypatch.setattr(cdek.httpx, "AsyncClient", Client)


async def test_check_connection_rejects_lk_login_email():
    ok, detail = await cdek.check_connection({**CFG, "account": "shop@cdek.ru"})
    assert ok is False
    assert "email" in detail


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
    resp = _FakeResponse(401, text='{"error":"invalid_client"}')
    _fake_client({"/oauth/token": resp}, monkeypatch)
    ok, detail = await cdek.check_connection(CFG)
    assert ok is False
    assert "креды отклонены" in detail
    assert "Создать ключ" in detail


async def test_check_connection_wrong_environment(monkeypatch):
    # Ключи ЛК не живут на edu — проверка должна подсказать переключить режим.
    _fake_client(
        {
            "api.edu.cdek.ru": _FakeResponse(401, text='{"error":"invalid_client"}'),
            "/oauth/token": _FakeResponse(200, {"access_token": "t", "expires_in": 3600}),
            "/location/cities": _FakeResponse(200, [{"code": 44, "city": "Москва"}]),
        },
        monkeypatch,
    )
    ok, detail = await cdek.check_connection(CFG)  # is_test=True → сначала edu
    assert ok is False
    assert "приняты на продакшен" in detail


def test_encode_decode_pvz():
    from app.services.cdek_checkout import decode_destination, encode_destination

    stored = encode_destination(pickup_point_id="NSK12", label="Новосибирск, Красный 1")
    assert stored.startswith("pvz:NSK12|")
    dest = decode_destination(stored)
    assert dest["pickup_point_id"] == "NSK12"
    assert dest["to_address"] is None
    assert "Красный" in dest["label"]


def test_encode_decode_door():
    from app.services.cdek_checkout import decode_destination, encode_destination

    stored = encode_destination(to_postal="630000", to_address="Новосибирск, Ленина 1")
    dest = decode_destination(stored)
    assert dest["pickup_point_id"] is None
    assert dest["to_postal"] == "630000"
    assert dest["to_address"] == "Новосибирск, Ленина 1"


def test_decode_legacy_pvz_prefix():
    from app.services.cdek_checkout import decode_destination

    dest = decode_destination("ПВЗ MSK10")
    assert dest["pickup_point_id"] == "MSK10"


def test_delivery_status_chain():
    from app.enums import OrderStatus as S
    from app.services.cdek_checkout import statuses_to_apply

    assert statuses_to_apply(S.POSTPAYMENT_PAID, S.DELIVERY_SERVICE_SELECTION) == [
        S.DELIVERY_SERVICE_SELECTION
    ]
    assert statuses_to_apply(S.POSTPAYMENT_PAID, S.DELIVERY_PAYMENT) == [
        S.DELIVERY_SERVICE_SELECTION,
        S.DELIVERY_ADDRESS_SELECTION,
        S.DELIVERY_PAYMENT,
    ]
    assert statuses_to_apply(S.DELIVERY_PAYMENT, S.DELIVERY_ADDRESS_SELECTION) == []
    assert statuses_to_apply(S.DELIVERY_PAYMENT, S.DELIVERY_PAYMENT) == []
