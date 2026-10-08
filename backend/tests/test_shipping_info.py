"""Сериализация адреса и ссылок трекинга для карточки заказа."""

from app.services.shipping_info import destination_parts, service_label, tracking_url


def test_service_labels():
    assert service_label("cdek") == "СДЭК"
    assert service_label("yandex") == "Яндекс Доставка"
    assert service_label("ozon") == "Ozon Доставка"
    assert service_label(None) is None


def test_tracking_urls():
    assert tracking_url("cdek", "123") == "https://www.cdek.ru/ru/tracking?order_id=123"
    assert tracking_url("ozon", "PN-1") == "https://tracking.ozon.ru/?track=PN-1"
    assert tracking_url("yandex", "req-1") is None
    assert (
        tracking_url("yandex", "req-1", sharing_url="https://dostavka.yandex.ru/track/x")
        == "https://dostavka.yandex.ru/track/x"
    )


def test_destination_pvz():
    parts = destination_parts("pvz:MSK123|ПВЗ на Тверской")
    assert parts["delivery_mode"] == "pvz"
    assert parts["delivery_point_id"] == "MSK123"
    assert parts["delivery_address"] == "ПВЗ: ПВЗ на Тверской"


def test_destination_door():
    parts = destination_parts("door:101000|ул. Примерная, 1")
    assert parts["delivery_mode"] == "door"
    assert parts["delivery_point_id"] is None
    assert "Курьер:" in (parts["delivery_address"] or "")
    assert "Примерная" in (parts["delivery_address"] or "")
