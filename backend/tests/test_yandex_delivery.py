"""Тесты сборки заявки Яндекс Доставки: единицы измерения и выбор точки доставки.

Сеть не трогаем — проверяем только чистые функции (то, что легко сломать молча:
копейки вместо рублей и подмена ПВЗ адресом).
"""

import pytest

from app.services import yandex_delivery as yd

CFG = {
    "token": "test",
    "is_test": True,
    "merchant_id": "m-1",
    "platform_station_id": "st-1",
    "last_mile_policy": "time_interval",
    "payment_method": "already_paid",
    "weight": 300,
    "pickup_delay_hours": 24,
    "nds": 0,
}


def _build(**over):
    kwargs = {
        "order_id": 42,
        "item_price_rub": 1234.56,
        "recipient_name": "Иван Петров",
        "recipient_phone": "+79990000000",
        "pickup_point_id": "pvz-1",
    }
    kwargs.update(over)
    return yd.build_request(CFG, **kwargs)


def test_pick_geo_id_prefers_matching_city():
    variants = [
        {"geo_id": 213, "address": "Москва"},
        {"geo_id": 10716, "address": "Томилино"},
    ]
    assert yd.pick_geo_id("Томилино", variants) == 10716
    assert yd.pick_geo_id("Москва", variants) == 213
    assert yd.pick_geo_id("Владивосток", variants) is None


def test_point_matches_location_keeps_city():
    kazan = {"address": "Казань, Баумана 1", "name": "ПВЗ"}
    assert yd._point_matches_location(kazan, "Казань")
    assert not yd._point_matches_location(kazan, "Томилино")


def test_prices_are_sent_in_kopecks():
    # 1234.56 ₽ → 123456 копеек. Ошибка в 100 раз ломает оценочную стоимость.
    body = _build()
    billing = body["items"][0]["billing_details"]
    assert billing["unit_price"] == 123456
    assert billing["assessed_unit_price"] == 123456


def test_pickup_point_becomes_platform_station_and_self_pickup():
    body = _build()
    assert body["destination"]["type"] == "platform_station"
    assert body["destination"]["platform_station"]["platform_id"] == "pvz-1"
    assert body["last_mile_policy"] == "self_pickup"


def test_courier_address_without_coordinates_uses_details():
    # Геокодер не обязателен: Platform API принимает адрес в details.
    body = _build(pickup_point_id=None, address="Москва, Тверская 1")
    loc = body["destination"]["custom_location"]
    assert body["destination"]["type"] == "custom_location"
    assert "latitude" not in loc
    assert loc["details"]["full_address"] == "Москва, Тверская 1"


def test_courier_needs_address_or_pvz():
    with pytest.raises(yd.YandexDeliveryError):
        _build(pickup_point_id=None, address=None)


def test_courier_with_coordinates_uses_custom_location():
    body = _build(
        pickup_point_id=None, address="Москва, Тверская 1", latitude=55.76, longitude=37.61
    )
    loc = body["destination"]["custom_location"]
    assert body["destination"]["type"] == "custom_location"
    assert (loc["latitude"], loc["longitude"]) == (55.76, 37.61)
    assert loc["details"]["full_address"] == "Москва, Тверская 1"
    assert body["last_mile_policy"] == "time_interval"


def test_place_weight_in_grams_and_barcode_matches_item():
    body = _build()
    place = body["places"][0]
    assert place["physical_dims"]["weight_gross"] == 300
    assert place["barcode"] == body["items"][0]["place_barcode"] == "casetop-42"


def test_single_word_name_still_has_last_name():
    # last_name в заявке обязателен — при одном слове ставим прочерк.
    body = _build(recipient_name="Иван")
    assert body["recipient_info"] == {
        "first_name": "Иван",
        "last_name": "—",
        "phone": "+79990000000",
    }


def test_pickup_interval_is_a_window():
    body = _build()
    interval = body["source"]["interval_utc"]
    assert interval["from"] < interval["to"]
    assert interval["from"].endswith("Z")


def test_price_to_rub_parses_offer_string():
    assert yd.price_to_rub("192.15 RUB") == 192.15
    assert yd.price_to_rub("") == 0.0
    assert yd.price_to_rub(300) == 300.0


def test_sanitize_token_strips_bearer_and_whitespace():
    assert yd.sanitize_token("  Bearer y0_AgAA  \n") == "y0_AgAA"
    assert yd.sanitize_token('"y0_AgAA"') == "y0_AgAA"
    assert yd.sanitize_token("y0_AgAA") == "y0_AgAA"


def test_missing_station_is_rejected():
    with pytest.raises(yd.YandexDeliveryError):
        yd.build_request(
            {**CFG, "platform_station_id": None},
            order_id=1,
            item_price_rub=100,
            recipient_name="Иван Петров",
            recipient_phone="+79990000000",
            pickup_point_id="pvz-1",
        )


@pytest.mark.parametrize(
    ("platform_status", "expected"),
    [
        ("DELIVERY_DELIVERED", "delivered"),
        ("delivery_delivered", "delivered"),  # регистр из ответа не важен
        ("DELIVERY_TRANSMITTED_TO_RECIPIENT", "delivered"),
        ("DELIVERY_ARRIVED_PICKUP_POINT", "shipped"),
        ("SORTING_CENTER_AT_START", "shipped"),
        ("DRAFT", None),  # заявка только создана — заказ не двигаем
        ("CREATED", None),
        ("CANCELLED", None),  # отмену решает оператор, не автомат
        (None, None),
    ],
)
def test_map_status(platform_status, expected):
    assert yd.map_status(platform_status) == expected


class _FakeResponse:
    """Минимальный ответ httpx: нужен только код и текст (см. yd._request)."""

    def __init__(self, status_code: int, payload: dict | None = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        if text is not None:
            self.text = text
        else:
            self.text = "Access denied" if status_code >= 400 else ""

    def json(self):
        return self._payload


def _fake_client(routes: dict[str, _FakeResponse], monkeypatch):
    """Подменяет httpx.AsyncClient: путь запроса → заранее заданный ответ."""

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            for path, resp in routes.items():
                if url.endswith(path):
                    return resp
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)


def _fake_client_by_host(test_resp: _FakeResponse, prod_resp: _FakeResponse, monkeypatch):
    """Разные ответы для песочницы и продакшена (один и тот же путь)."""

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            if "b2b.taxi.tst.yandex.net" in url:
                return test_resp
            if "b2b-authproxy.taxi.yandex.net" in url:
                return prod_resp
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)


async def test_check_connection_survives_forbidden_warehouses(monkeypatch):
    # Раздел складов открыт не всякому токену: 401 на нём не значит «нет связи».
    _fake_client(
        {
            "/location/detect": _FakeResponse(200, {"variants": [{"geo_id": 213}]}),
            "/warehouses/list": _FakeResponse(401),
        },
        monkeypatch,
    )
    ok, detail = await yd.check_connection(CFG)
    assert ok is True
    assert "ID склада возьмите в ЛК" in detail


async def test_check_connection_reports_bad_token(monkeypatch):
    _fake_client({"/location/detect": _FakeResponse(401)}, monkeypatch)
    ok, detail = await yd.check_connection(CFG)
    assert ok is False
    assert "тестовый токен из документации" in detail  # подсказка про тестовый режим


async def test_check_connection_detects_prod_token_in_test_mode(monkeypatch):
    # Частый случай: токен из ЛК при включённом тестовом режиме.
    _fake_client_by_host(
        _FakeResponse(401, text='{"code":"unauthorized","message":"Access denied"}'),
        _FakeResponse(200, {"variants": [{"geo_id": 213}]}),
        monkeypatch,
    )
    ok, detail = await yd.check_connection(CFG)
    assert ok is False
    assert "принят на продакшен" in detail
    assert "Переключите «Тестовый режим»" in detail


async def test_check_connection_lists_warehouses(monkeypatch):
    _fake_client(
        {
            "/location/detect": _FakeResponse(200, {"variants": [{"geo_id": 213}]}),
            "/warehouses/list": _FakeResponse(
                200, {"warehouses": [{"station_id": "st-1", "name": "Склад МСК"}]}
            ),
        },
        monkeypatch,
    )
    ok, detail = await yd.check_connection(CFG)
    assert ok is True
    assert "Склад МСК [st-1]" in detail


def test_build_warehouse_body_requires_phone():
    with pytest.raises(yd.YandexDeliveryError):
        yd.build_warehouse_body(
            name="Склад",
            client_warehouse_id="wh-1",
            latitude=55.55,
            longitude=37.94,
            city="Томилино",
            house="3",
            phone="  ",
        )


def test_build_warehouse_body_tomilino_address():
    body = yd.build_warehouse_body(
        name=str(yd.TOMILINO_WAREHOUSE["name"]),
        client_warehouse_id=str(yd.TOMILINO_WAREHOUSE["client_warehouse_id"]),
        latitude=float(yd.TOMILINO_WAREHOUSE["latitude"]),
        longitude=float(yd.TOMILINO_WAREHOUSE["longitude"]),
        city=str(yd.TOMILINO_WAREHOUSE["city"]),
        house=str(yd.TOMILINO_WAREHOUSE["house"]),
        phone="+7 999 000 00 00",
        street=str(yd.TOMILINO_WAREHOUSE["street"]),
        region=str(yd.TOMILINO_WAREHOUSE["region"]),
        postal_code=str(yd.TOMILINO_WAREHOUSE["postal_code"]),
        geo_id=10716,
        contact_name="Иван Петров",
        merchant_id="m-1",
    )
    assert body["client_warehouse_id"] == "tomilino-garshina-3"
    assert body["location"]["address"] == {
        "city": "Томилино",
        "country": "Россия",
        "house": "3",
        "street": "улица Гаршина",
        "region": "Московская область",
        "postal_code": "140070",
        "geo_id": 10716,
    }
    assert body["contact"]["phone"] == "+79990000000"
    assert body["contact"]["first_name"] == "Иван"
    assert body["merchant_id"] == "m-1"


async def test_geocode_rejects_delivery_oauth_without_http():
    with pytest.raises(yd.YandexDeliveryError, match="OAuth-токен Доставки"):
        await yd.geocode("y0_AgAAAA-fake-delivery-token", "Томилино, улица Гаршина, 3")


async def test_resolve_warehouse_geo_keeps_fallback_when_geocoder_forbidden(monkeypatch):
    """Битый ключ Геокодера не блокирует склад: остаются запасные координаты БЦ."""

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            assert "geocode-maps.yandex.ru" in url
            return _FakeResponse(
                403, {"statusCode": 403, "error": "Forbidden", "message": "Invalid api key"}
            )

        async def request(self, method, url, **kw):
            if url.endswith("/location/detect"):
                return _FakeResponse(200, {"variants": [{"geo_id": 10716}]})
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)
    lat, lon, geo_id = await yd.resolve_warehouse_geo(
        {**CFG, "geocoder_apikey": "11111111-2222-3333-4444-555555555555"},
        address=str(yd.TOMILINO_WAREHOUSE["full_address"]),
        latitude=float(yd.TOMILINO_WAREHOUSE["latitude"]),
        longitude=float(yd.TOMILINO_WAREHOUSE["longitude"]),
    )
    assert (lat, lon) == (
        float(yd.TOMILINO_WAREHOUSE["latitude"]),
        float(yd.TOMILINO_WAREHOUSE["longitude"]),
    )
    assert geo_id == 10716


async def test_ensure_warehouse_reuses_existing(monkeypatch):
    _fake_client(
        {
            "/warehouses/list": _FakeResponse(
                200,
                {
                    "warehouses": [
                        {
                            "station_id": "st-tom",
                            "client_warehouse_id": "tomilino-garshina-3",
                            "name": "Томилино, Гаршина 3",
                            "location": {
                                "address": {
                                    "city": "Томилино",
                                    "street": "улица Гаршина",
                                    "house": "3",
                                }
                            },
                        }
                    ]
                },
            )
        },
        monkeypatch,
    )
    station, reused = await yd.ensure_warehouse(
        CFG,
        name="Томилино, Гаршина 3",
        client_warehouse_id="tomilino-garshina-3",
        city="Томилино",
        house="3",
        phone="+79990000000",
        street="улица Гаршина",
    )
    assert station == "st-tom"
    assert reused is True


async def test_ensure_warehouse_creates_when_missing(monkeypatch):
    seen: dict = {}

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            if url.endswith("/warehouses/list"):
                return _FakeResponse(200, {"warehouses": []})
            if url.endswith("/location/detect"):
                return _FakeResponse(200, {"variants": [{"geo_id": 10716}]})
            if url.endswith("/warehouses/create"):
                seen["body"] = kw.get("json")
                return _FakeResponse(200, {"station_id": "st-new"})
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)
    station, reused = await yd.ensure_warehouse(
        CFG,
        name="Томилино, Гаршина 3",
        client_warehouse_id="tomilino-garshina-3",
        city="Томилино",
        house="3",
        phone="+79990000000",
        street="улица Гаршина",
        full_address=str(yd.TOMILINO_WAREHOUSE["full_address"]),
        region="Московская область",
        postal_code="140070",
    )
    assert station == "st-new"
    assert reused is False
    assert seen["body"]["location"]["address"]["house"] == "3"
    assert seen["body"]["location"]["address"]["geo_id"] == 10716
    assert seen["body"]["contact"]["phone"] == "+79990000000"


async def test_create_warehouse_retries_without_unknown_merchant(monkeypatch):
    """merchant_id из доки/чужого кабинета: Яндекс 404, повтор без поля проходит."""
    seen: list[dict] = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            if not url.endswith("/warehouses/create"):
                raise AssertionError(url)
            body = kw.get("json") or {}
            seen.append(body)
            if body.get("merchant_id"):
                return _FakeResponse(
                    404, text='{"code":"not_found","message":"Merchant not found"}'
                )
            return _FakeResponse(200, {"station_id": "st-ok"})

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)
    station = await yd.create_warehouse(
        CFG,
        {
            "client_warehouse_id": "tomilino-garshina-3",
            "name": "Томилино, Гаршина 3",
            "merchant_id": "a1899c66801048d090cac6d0efa03a3a",
            "contact": {"phone": "+79990000000"},
        },
    )
    assert station == "st-ok"
    assert "merchant_id" in seen[0]
    assert "merchant_id" not in seen[1]


async def test_pickup_points_empty_when_city_unknown(monkeypatch):
    _fake_client({"/location/detect": _FakeResponse(200, {"variants": []})}, monkeypatch)
    assert await yd.pickup_points(CFG, location="Неттакогогорода", limit=8) == []


async def test_pickup_points_filters_other_cities(monkeypatch):
    _fake_client(
        {
            "/location/detect": _FakeResponse(
                200, {"variants": [{"geo_id": 43, "address": "Казань"}]}
            ),
            "/pickup-points/list": _FakeResponse(
                200,
                {
                    "points": [
                        {
                            "id": "far",
                            "name": "Дальний",
                            "address": {"full_address": "Владивосток, Ленина 1"},
                            "position": {},
                        },
                        {
                            "id": "near",
                            "name": "Центр",
                            "address": {"full_address": "Казань, Баумана 1"},
                            "position": {},
                        },
                    ]
                },
            ),
        },
        monkeypatch,
    )
    points = await yd.pickup_points(CFG, location="Казань", limit=8)
    assert [p["id"] for p in points] == ["near"]


async def test_resolve_door_location_ignores_geocoder_403(monkeypatch):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _FakeResponse(403, text='{"message":"Invalid api key"}')

        async def request(self, method, url, **kw):
            if url.endswith("/location/detect"):
                return _FakeResponse(200, {"variants": [{"geo_id": 213, "address": "Москва"}]})
            raise AssertionError(url)

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)
    lat, lon, geo_id = await yd.resolve_door_location(
        {**CFG, "geocoder_apikey": "11111111-2222-3333-4444-555555555555"},
        address="Москва, Тверская 1",
    )
    assert lat is None and lon is None
    assert geo_id == 213


async def test_pickup_points_sorted_by_distance_from_geocoded_address(monkeypatch):
    def pt(pid, lat, lon):
        return {
            "id": pid,
            "address": {"full_address": f"Москва, {pid}"},
            "position": {"latitude": lat, "longitude": lon},
        }

    _fake_client(
        {
            "/location/detect": _FakeResponse(
                200, {"variants": [{"geo_id": 213, "address": "Москва"}]}
            ),
            "/pickup-points/list": _FakeResponse(
                200,
                {
                    "points": [
                        pt("far", 55.9, 37.9),
                        pt("near", 55.75, 37.62),
                        pt("mid", 55.8, 37.7),
                    ]
                },
            ),
        },
        monkeypatch,
    )

    async def fake_geocode(apikey, address):
        return 55.7558, 37.6173

    monkeypatch.setattr(yd, "geocode", fake_geocode)
    cfg = {**CFG, "geocoder_apikey": "11111111-2222-3333-4444-555555555555"}
    points = await yd.pickup_points(cfg, location="Москва, Тверская 1", limit=2)
    assert [p["id"] for p in points] == ["near", "mid"]


def test_normalize_phone_to_plus7_format():
    # Схема request/create ждёт «+79529999999»; клиент вводит по-разному.
    for raw in ("8 (999) 000-00-00", "79990000000", "+7 999 000 00 00", "9990000000"):
        assert yd.normalize_phone(raw) == "+79990000000"
    assert yd.normalize_phone(None) == ""
    assert _build(recipient_phone="8 999 000 00 00")["recipient_info"]["phone"] == "+79990000000"


async def test_known_api_error_code_gets_actionable_hint(monkeypatch):
    _fake_client(
        {
            "/offers/create": _FakeResponse(
                400,
                {
                    "code": "pickups_not_configured",
                    "message": "Pickups are not configured for the warehouse",
                },
            )
        },
        monkeypatch,
    )
    with pytest.raises(yd.YandexDeliveryError) as e:
        await yd.offers_create(CFG, {})
    assert "график забора" in str(e.value)
    assert "pickups_not_configured" in str(e.value)


async def test_dropoff_points_ask_api_for_dropoff_not_pickup_type(monkeypatch):
    # Путь Б: точки приёма от отправителя — фильтр available_for_dropoff, а не type=pickup_point.
    seen = {}

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            if url.endswith("/location/detect"):
                return _FakeResponse(200, {"variants": [{"geo_id": 213, "address": "Москва"}]})
            seen["body"] = kw["json"]
            return _FakeResponse(
                200,
                {"points": [{"id": "drop-1", "address": {"full_address": "Москва, Тверская 1"}}]},
            )

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)
    points = await yd.pickup_points(CFG, location="Москва", limit=5, dropoff=True)
    assert seen["body"] == {"available_for_dropoff": True, "geo_id": 213}
    assert [p["id"] for p in points] == ["drop-1"]
