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


def test_courier_needs_coordinates():
    # Адрес без координат — custom_location их требует, Геокодер не подключён.
    with pytest.raises(yd.YandexDeliveryError):
        _build(pickup_point_id=None, address="Москва, Тверская 1")


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
