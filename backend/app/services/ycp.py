"""Yandex Commerce Protocol (YCP): покупка «в 1 клик» из Алисы/Поиска.

Яндекс ходит к нам (`Authorization: Bearer <токен доступа>`). Токен выпускаем сами
и вставляем в красное поле «Токен доступа» личного кабинета YCP — кабинет его не выдаёт.
Обратный «Токен API YCP» кабинет может показать отдельно: он нужен только если Яндекс
просит исходящие вызовы, на приём заказов не влияет.

В поле «URL для API» кабинет дописывает `/api/v1/...` к вставленной базе.
Со слэшем на конце `https://домен/ycp/` это `/ycp/api/v1/warehouses`.
Без слэша или с адресом сайта (`https://домен/`) путь схлопывается в
`/api/v1/warehouses` или `//api/v1/warehouses` — эти адреса тоже отдаём как YCP.
Фид для Яндекс Товаров — `/ycp/feed.yml`.
Спека: https://yandex.ru/support/merchants-ru-ycp/ru/openapi/index.md

Что продаём: типы чехлов без кастома (`is_custom=False`). Оффер = строка `CaseTypeModel`
(тип × модель iPhone), её `id` и есть ID товара для Яндекса (он же offerId в фиде).
Цены — целые рубли. Заказ в YCP всегда на 1 штуку: в нашей модели заказ = один чехол.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

from app.enums import OrderStatus

TOKEN_KEY = "ycp.access_token"
API_TOKEN_KEY = "ycp.api_token"
ENABLED_KEY = "ycp.enabled"
PUBLIC_BASE_KEY = "ycp.public_base_url"
SHOP_URL_KEY = "ycp.shop_url"
SHOP_NAME = "casetop"
WAREHOUSE_ID = "main"
MAX_QTY = 1  # ponytail: Order = один чехол; корзины на N штук = N заказов, добавить при спросе
TZ = 3  # МСК
# Габариты упакованного чехла (мм, г) — Яндексу нужны для расчёта логистики.
DIMENSIONS = {"width": 100, "height": 180, "depth": 20, "weight": 80}
DELIVERY_INTERVAL_DAYS = 2  # ширина окна «от … до …» в днях


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_ok(expected: str | None, authorization: str | None) -> bool:
    """`Authorization: Bearer <token>` против сохранённого токена, в постоянное время."""
    if not expected or not authorization:
        return False
    scheme, _, given = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(given.strip(), expected)


def delivery_interval(today: date, days: int) -> dict:
    """Окно доставки [today+days, today+days+2] в формате DeliveryDateInterval."""
    start = today + timedelta(days=max(days, 0))
    end = start + timedelta(days=DELIVERY_INTERVAL_DAYS)
    return {
        "start_interval": {"date": start.isoformat()},
        "end_interval": {"date": end.isoformat()},
        "time_zone": TZ,
    }


# Статус заказа в нашей модели → статус доставки в терминах YCP.
_DELIVERY_STATUS = {
    OrderStatus.SHIPPED: "in_progress",
    OrderStatus.DELIVERED: "delivered",
    OrderStatus.REVIEW_OFFERED: "delivered",
    OrderStatus.REVIEW_RECEIVED: "delivered",
    OrderStatus.CANCELLED: "cancelled",
}


def delivery_status(status: str) -> str:
    return _DELIVERY_STATUS.get(OrderStatus(status), "processing")


def rub(value: float) -> int:
    """Цена в целых рублях (YCP принимает integer)."""
    return int(round(float(value)))


def enabled_flag(raw: str | None) -> bool:
    """Пустое значение = интеграция включена (так жили установки до появления тумблера)."""
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in ("1", "true", "yes", "да")


def _base(public_base: str) -> str:
    return public_base.strip().rstrip("/")


def lk_api_url(public_base: str) -> str:
    """База для поля «URL для API»: кабинет сам дописывает `/api/v1/...`."""
    return f"{_base(public_base)}/ycp/"


def feed_url(public_base: str) -> str:
    return f"{_base(public_base)}/ycp/feed.yml"


def probe_warehouses_url(public_base: str) -> str:
    return f"{_base(public_base)}/ycp/api/v1/warehouses"


def cabinet_phone(raw: str | None) -> str:
    """Телефон склада в виде примера из спеки: «+7 (495) 123-45-67»."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        rest = digits[1:]
        return f"+7 ({rest[:3]}) {rest[3:6]}-{rest[6:8]}-{rest[8:10]}"
    return (raw or "").strip()


def cabinet_path(path: str) -> str | None:
    """Путь, как его видит кабинет YCP → путь наших хендлеров.

    `/ycp/api/v1/warehouses` и схлопнутый `/api/v1/warehouses` (в том числе с `//`)
    ведут на одни хендлеры. `/api/v1/orders` не трогаем. Хвостовой слэш снимаем,
    чтобы FastAPI не редиректил на внутренний путь.
    """
    collapsed = re.sub(r"/{2,}", "/", path) or "/"
    if collapsed in ("/ycp", "/ycp/"):
        return "/api/v1/ycp/health"
    if collapsed == "/ycp/feed.yml":
        return "/api/v1/ycp/feed.yml"
    if collapsed.startswith("/ycp/api/v1"):
        rewritten = "/api/v1/ycp" + collapsed.removeprefix("/ycp/api/v1")
    elif _root_ycp(collapsed):
        rewritten = "/api/v1/ycp" + collapsed.removeprefix("/api/v1")
    else:
        return None
    if len(rewritten) > 1:
        rewritten = rewritten.rstrip("/")
    return rewritten


def _root_ycp(path: str) -> bool:
    """YCP на корне сайта: склады, чекаут и заказ. `/orders` магазина — нет."""
    if not path.startswith("/api/v1/"):
        return False
    rest = path.removeprefix("/api/v1")
    return (
        rest == "/warehouses"
        or rest.startswith("/warehouses/")
        or rest == "/checkout"
        or rest.startswith("/checkout/")
        or rest == "/order"
        or rest.startswith("/order/")
    )


def absolute_url(url: str | None, public_base: str) -> str | None:
    if not url:
        return None
    if url.startswith(("https://", "http://")):
        return url
    base = _base(public_base)
    if url.startswith("/") and base:
        return base + url
    return None


def readiness(
    *,
    enabled: bool,
    token: str | None,
    public_base: str | None,
    address: str | None,
    phone: str | None,
    checkout_offers: int,
    api_token_set: bool,
) -> tuple[bool, str]:
    """Готовность к проверке в кабинете YCP: токен, адрес API, склад, товары в фиде."""
    missing: list[str] = []
    if not enabled:
        missing.append("интеграция выключена")
    if not token:
        missing.append("нет токена доступа")
    if not (public_base or "").strip():
        missing.append("не задан публичный адрес сайта")
    if not (address or "").strip() or not (phone or "").strip():
        missing.append("не заполнены адрес и телефон склада")
    if checkout_offers <= 0:
        missing.append("нет некастомных чехлов в наличии для кнопки «Купить»")
    if missing:
        return False, "; ".join(missing)
    note = ""
    if not api_token_set:
        note = " Токен API из кабинета Яндекса не задан — приём заказов работает и без него."
    return True, f"API готово: {checkout_offers} товаров с кнопкой «Купить».{note}"


async def probe_public(public_base: str, token: str) -> str | None:
    """Живой запрос на публичный URL складов — тот же, что сделает кнопка в кабинете."""
    import httpx

    url = probe_warehouses_url(public_base)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        return f"публичный адрес недоступен с сервера ({url}): {exc}"[:220]
    if response.status_code != 200:
        return f"публичный адрес ответил {response.status_code} на {url}"
    return None


@dataclass(frozen=True)
class FeedCategory:
    category_id: str
    name: str


@dataclass(frozen=True)
class FeedOffer:
    offer_id: str
    name: str
    price: int
    category_id: str
    available: bool
    checkout: bool
    picture: str | None = None
    description: str | None = None
    url: str | None = None


def _xml(value: str) -> str:
    return escape(value, {"'": "&apos;", '"': "&quot;"})


def yml_catalog(
    *,
    shop_name: str,
    shop_url: str,
    categories: list[FeedCategory],
    offers: list[FeedOffer],
    when: datetime,
) -> str:
    """YML для Яндекс Товаров. `param is_checkout_enabled` включает кнопку «Купить»."""
    stamp = when.strftime("%Y-%m-%d %H:%M")
    cats = "\n".join(
        f'      <category id="{_xml(c.category_id)}">{_xml(c.name)}</category>' for c in categories
    )
    blocks: list[str] = []
    for offer in offers:
        bits = [
            (
                f'      <offer id="{_xml(offer.offer_id)}" '
                f'available="{"true" if offer.available else "false"}">'
            ),
            f"        <name>{_xml(offer.name[:200])}</name>",
            f"        <vendor>{_xml(shop_name)}</vendor>",
            f"        <price>{offer.price}</price>",
            "        <currencyId>RUR</currencyId>",
            f"        <categoryId>{_xml(offer.category_id)}</categoryId>",
        ]
        if offer.url:
            bits.append(f"        <url>{_xml(offer.url)}</url>")
        if offer.picture:
            bits.append(f"        <picture>{_xml(offer.picture)}</picture>")
        if offer.description:
            bits.append(f"        <description>{_xml(offer.description[:3000])}</description>")
        flag = "true" if offer.checkout else "false"
        bits.append(f'        <param name="is_checkout_enabled">{flag}</param>')
        bits.append("      </offer>")
        blocks.append("\n".join(bits))
    offers_xml = "\n".join(blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<yml_catalog date="{stamp}">\n'
        "  <shop>\n"
        f"    <name>{_xml(shop_name)}</name>\n"
        f"    <company>{_xml(shop_name)}</company>\n"
        f"    <url>{_xml(shop_url)}</url>\n"
        '    <currencies><currency id="RUR" rate="1"/></currencies>\n'
        "    <categories>\n"
        f"{cats}\n"
        "    </categories>\n"
        "    <offers>\n"
        f"{offers_xml}\n"
        "    </offers>\n"
        "  </shop>\n"
        "</yml_catalog>\n"
    )
