"""Тесты YCP: Bearer-токен, окно доставки, статусы, фид. Сеть и БД не трогаем."""

from datetime import UTC, date, datetime

from app.enums import OrderStatus
from app.services import ycp


def test_token_ok_requires_matching_bearer():
    assert ycp.token_ok("secret", "Bearer secret")
    assert ycp.token_ok("secret", "bearer secret")
    assert not ycp.token_ok("secret", "Bearer other")
    assert not ycp.token_ok("secret", "secret")  # без схемы
    assert not ycp.token_ok("secret", None)


def test_token_not_configured_rejects_everything():
    # Пустой токен в настройках не должен пускать «Bearer » с пустым значением.
    assert not ycp.token_ok(None, "Bearer ")
    assert not ycp.token_ok("", "Bearer ")


def test_generated_tokens_are_unique_and_long():
    a, b = ycp.new_token(), ycp.new_token()
    assert a != b and len(a) >= 40


def test_delivery_interval_is_window_from_offset():
    iv = ycp.delivery_interval(date(2026, 10, 6), 5)
    assert iv["start_interval"] == {"date": "2026-10-11"}
    assert iv["end_interval"] == {"date": "2026-10-13"}
    assert iv["time_zone"] == 3


def test_delivery_status_mapping():
    assert ycp.delivery_status(OrderStatus.PREPAYMENT_PAID) == "processing"
    assert ycp.delivery_status(OrderStatus.SHIPPED) == "in_progress"
    assert ycp.delivery_status(OrderStatus.DELIVERED) == "delivered"
    assert ycp.delivery_status(OrderStatus.CANCELLED) == "cancelled"


def test_rub_rounds_to_integer():
    assert ycp.rub(1499.5) == 1500
    assert isinstance(ycp.rub(990.0), int)


def test_enabled_flag_defaults_to_on():
    assert ycp.enabled_flag(None)
    assert ycp.enabled_flag("")
    assert ycp.enabled_flag("true")
    assert not ycp.enabled_flag("false")


def test_cabinet_urls_match_what_yandex_appends():
    assert ycp.lk_api_url("https://casetop.ru/") == "https://casetop.ru/ycp/"
    assert ycp.feed_url("https://casetop.ru") == "https://casetop.ru/ycp/feed.yml"
    assert ycp.probe_warehouses_url("https://casetop.ru") == (
        "https://casetop.ru/ycp/api/v1/warehouses"
    )
    assert ycp.cabinet_path("/ycp/api/v1/warehouses") == "/api/v1/ycp/warehouses"
    assert ycp.cabinet_path("/ycp/api/v1/checkout/basket/check") == (
        "/api/v1/ycp/checkout/basket/check"
    )
    assert ycp.cabinet_path("/ycp/api/v1/warehouses/") == "/api/v1/ycp/warehouses"
    assert ycp.cabinet_path("/ycp/feed.yml") == "/api/v1/ycp/feed.yml"
    assert ycp.cabinet_path("/api/v1/ycp/warehouses") is None
    assert ycp.cabinet_path("/api/v1/warehouses") == "/api/v1/ycp/warehouses"
    assert ycp.cabinet_path("//api/v1/warehouses") == "/api/v1/ycp/warehouses"
    assert ycp.cabinet_path("/api/v1/checkout/basket/check") == (
        "/api/v1/ycp/checkout/basket/check"
    )
    assert ycp.cabinet_path("/api/v1/order") == "/api/v1/ycp/order"
    assert ycp.cabinet_path("/api/v1/order/cancel") == "/api/v1/ycp/order/cancel"
    assert ycp.cabinet_path("/api/v1/orders") is None
    assert ycp.cabinet_path("/ycp") == "/api/v1/ycp/health"
    assert ycp.cabinet_path("/ycp/") == "/api/v1/ycp/health"


def test_cabinet_phone_matches_spec_example():
    assert ycp.cabinet_phone("+79537179908") == "+7 (953) 717-99-08"
    assert ycp.cabinet_phone("8 (953) 717-99-08") == "+7 (953) 717-99-08"
    assert ycp.cabinet_phone("+7 (495) 123-45-67") == "+7 (495) 123-45-67"


def test_absolute_url_prefixes_site_paths():
    assert (
        ycp.absolute_url("/media/a.jpg", "https://casetop.ru") == "https://casetop.ru/media/a.jpg"
    )
    assert ycp.absolute_url("https://cdn/a.jpg", "https://casetop.ru") == "https://cdn/a.jpg"
    assert ycp.absolute_url("a.jpg", "https://casetop.ru") is None


def test_readiness_lists_what_blocks_the_cabinet():
    ok, detail = ycp.readiness(
        enabled=True,
        token=None,
        public_base="",
        address="",
        phone="",
        checkout_offers=0,
        api_token_set=False,
    )
    assert not ok
    assert "токена доступа" in detail
    assert "публичный адрес" in detail
    assert "склада" in detail
    assert "в наличии" in detail


def test_readiness_ok_mentions_optional_api_token():
    ok, detail = ycp.readiness(
        enabled=True,
        token="secret",
        public_base="https://casetop.ru",
        address="Томилино",
        phone="+79990000000",
        checkout_offers=3,
        api_token_set=False,
    )
    assert ok
    assert "3 товаров" in detail
    assert "Токен API" in detail


def test_yml_marks_checkout_only_for_stock():
    xml = ycp.yml_catalog(
        shop_name="casetop",
        shop_url="https://casetop.ru",
        categories=[ycp.FeedCategory("1", "Прозрачный & slim")],
        offers=[
            ycp.FeedOffer(
                offer_id="10",
                name="Прозрачный для iPhone 15",
                price=1499,
                category_id="1",
                available=True,
                checkout=True,
                picture="https://casetop.ru/a.jpg",
                url="https://casetop.ru",
            ),
            ycp.FeedOffer(
                offer_id="11",
                name="Нет в наличии",
                price=990,
                category_id="1",
                available=False,
                checkout=False,
            ),
        ],
        when=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
    )
    assert 'date="2026-10-07 10:00"' in xml
    assert "Прозрачный &amp; slim" in xml
    assert 'offer id="10" available="true"' in xml
    assert '<param name="is_checkout_enabled">true</param>' in xml
    assert 'offer id="11" available="false"' in xml
    assert '<param name="is_checkout_enabled">false</param>' in xml
    assert "<currencyId>RUR</currencyId>" in xml
