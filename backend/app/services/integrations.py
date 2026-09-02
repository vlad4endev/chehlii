"""Настройки интеграций: схема для UI, чтение/запись, env-фоллбэк.

Приоритет значения: БД (заданное в админке) → переменная окружения → default.
Секретные ключи не отдаются наружу в открытом виде (см. admin/integrations.py).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.settings import IntegrationSetting

# Схема разделов интеграций (порядок и поля — как в UI).
INTEGRATION_SCHEMA: list[dict[str, Any]] = [
    {
        "id": "yandex_disk",
        "title": "Яндекс.Диск",
        "hint": "Хранилище файлов клиентов и макетов. Нужно для передачи макета клиенту.",
        "fields": [
            {
                "key": "yandex_disk.oauth_token",
                "label": "OAuth-токен",
                "secret": True,
                "placeholder": "y0_AgAA...",
            },
            {
                "key": "yandex_disk.root",
                "label": "Корневая папка",
                "secret": False,
                "placeholder": "/chechlii/orders",
            },
        ],
    },
    {
        "id": "cdek",
        "title": "СДЭК",
        "hint": (
            "Служба доставки: расчёт, ПВЗ, заявка, статус, ярлык. Ключи — в ЛК СДЭК → "
            "Интеграция (не логин кабинета). Для тарифа «склад-дверь» обязателен код "
            "ПВЗ отгрузки. В тестовом режиме — ключи песочницы api.edu.cdek.ru."
        ),
        "fields": [
            {
                "key": "cdek.account",
                "label": "Account (Client ID)",
                "secret": False,
                "placeholder": "",
            },
            {"key": "cdek.secret", "label": "Secure password", "secret": True, "placeholder": ""},
            {
                "key": "cdek.test",
                "label": "Тестовый режим (true/false)",
                "secret": False,
                "placeholder": "true",
            },
            {
                "key": "cdek.shipment_point",
                "label": "Код ПВЗ отгрузки (склад)",
                "secret": False,
                "placeholder": "MSK1",
            },
            {
                "key": "cdek.from_postal",
                "label": "Индекс отправителя (для расчёта, если ПВЗ не задан)",
                "secret": False,
                "placeholder": "101000",
            },
            {
                "key": "cdek.from_address",
                "label": "Адрес отправителя (только тарифы «от двери»)",
                "secret": False,
                "placeholder": "",
            },
            {
                "key": "cdek.tariff_code",
                "label": "Код тарифа до двери",
                "secret": False,
                "placeholder": "137 (склад-дверь)",
            },
            {
                "key": "cdek.tariff_pickup",
                "label": "Код тарифа до ПВЗ",
                "secret": False,
                "placeholder": "136 (склад-склад)",
            },
            {
                "key": "cdek.weight",
                "label": "Вес посылки, г",
                "secret": False,
                "placeholder": "300",
            },
            {
                "key": "cdek.sender_name",
                "label": "Имя отправителя",
                "secret": False,
                "placeholder": "casetop",
            },
            {
                "key": "cdek.sender_phone",
                "label": "Телефон отправителя",
                "secret": False,
                "placeholder": "+79990000000",
            },
        ],
    },
    {
        "id": "yandex_delivery",
        "title": "Яндекс Доставка",
        "hint": (
            "Служба доставки: ПВЗ и курьер до двери. Токен — в личном кабинете "
            "dostavka.yandex.ru → «Интеграция». Ключ Геокодера нужен только для доставки "
            "до двери (координаты адреса); для ПВЗ он не требуется. В тестовом режиме "
            "нужен тестовый токен из документации API — токен из ЛК работает только "
            "на продакшене."
        ),
        "fields": [
            {
                "key": "yandex.oauth_token",
                "label": "OAuth-токен (Bearer)",
                "secret": True,
                "placeholder": "y0_AgAA...",
            },
            {
                "key": "yandex.test",
                "label": "Тестовый режим (true/false)",
                "secret": False,
                "placeholder": "true",
            },
            {
                "key": "yandex.merchant_id",
                "label": "ID магазина (merchant_id)",
                "secret": False,
                "placeholder": "290587090cfc4943856851c8c3b2eebf",
            },
            {
                "key": "yandex.platform_station_id",
                "label": "ID склада отправителя (platform_id)",
                "secret": False,
                "placeholder": "e1139f6d-e34f-47a9-a55f-31f032a861a6",
            },
            {
                "key": "yandex.last_mile_policy",
                "label": "Последняя миля (time_interval / self_pickup)",
                "secret": False,
                "placeholder": "time_interval",
            },
            {
                "key": "yandex.payment_method",
                "label": "Оплата (already_paid / card_on_receipt / postpay)",
                "secret": False,
                "placeholder": "already_paid",
            },
            {
                "key": "yandex.weight",
                "label": "Вес посылки, г",
                "secret": False,
                "placeholder": "300",
            },
            {
                "key": "yandex.pickup_delay_hours",
                "label": "Забор со склада через, ч",
                "secret": False,
                "placeholder": "24 (интервал должен совпадать с отгрузками в ЛК)",
            },
            {
                "key": "yandex.nds",
                "label": "Ставка НДС для позиций, %",
                "secret": False,
                "placeholder": "0 (без НДС)",
            },
            {
                "key": "yandex.geocoder_apikey",
                "label": "API-ключ Геокодера (только для курьера до двери)",
                "secret": True,
                "placeholder": "",
            },
        ],
    },
    {
        "id": "payment",
        "title": "Оплата (Robokassa)",
        "hint": (
            "Приём предоплаты и постоплаты. Бот показывает кнопку на каждый настроенный "
            "шлюз, а поле «Платёжный шлюз» задаёт, какой из них идёт первым. В ЛК "
            "Robokassa укажите ResultURL, Success и Fail (см. подсказку под полями)."
        ),
        "fields": [
            {
                "key": "payment.provider",
                "label": "Шлюз по умолчанию, первый в списке (robokassa / yandex_pay)",
                "secret": False,
                "placeholder": "robokassa",
            },
            {
                "key": "payment.robokassa_login",
                "label": "MerchantLogin (идентификатор магазина)",
                "secret": False,
                "placeholder": "",
            },
            {
                "key": "payment.robokassa_pass1",
                "label": "Пароль №1",
                "secret": True,
                "placeholder": "",
            },
            {
                "key": "payment.robokassa_pass2",
                "label": "Пароль №2",
                "secret": True,
                "placeholder": "",
            },
            {
                "key": "payment.robokassa_test",
                "label": "Тестовый режим (true/false)",
                "secret": False,
                "placeholder": "true",
            },
            {
                "key": "payment.prepay_percent",
                "label": "Размер предоплаты, %",
                "secret": False,
                "placeholder": "50",
            },
        ],
    },
    {
        "id": "yandex_pay",
        "title": "Оплата (Яндекс Пэй)",
        "hint": (
            "Второй шлюз: ссылка на форму Яндекс Пэй. API-ключ выпускается в ЛК "
            "pay.yandex.ru — если он выдан (вид «мерчант-без-дефисов.секрет»), вписывайте "
            "целиком. В песочнице ключ можно не выпускать: подойдёт сам Merchant ID. "
            "В ЛК укажите Callback URL = {публичный адрес}/api/v1/payments/yandex-pay/webhook. "
            "Заполненный ключ сам добавляет кнопку «Яндекс Пэй» в блок оплаты. Кнопка "
            "«Проверить связь» опрашивает Пэй сохранёнными кредами и заказов не создаёт."
        ),
        "fields": [
            {
                "key": "payment.yandexpay_api_key",
                "label": "API-ключ (Authorization: Api-Key)",
                "secret": True,
                "placeholder": "",
            },
            {
                "key": "payment.yandexpay_merchant_id",
                "label": "Merchant ID",
                "secret": False,
                "placeholder": "af0b0c8f-de95-4246-9f3c-36c16464ffeb",
            },
            {
                "key": "payment.yandexpay_test",
                "label": "Песочница (true/false)",
                "secret": False,
                "placeholder": "true",
            },
            {
                "key": "payment.yandexpay_public_base_url",
                "label": "Публичный адрес backend (для страниц после оплаты)",
                "secret": False,
                "placeholder": "https://casetop.example.ru",
            },
        ],
    },
]

ALL_KEYS: list[str] = [f["key"] for g in INTEGRATION_SCHEMA for f in g["fields"]]
SECRET_KEYS: set[str] = {f["key"] for g in INTEGRATION_SCHEMA for f in g["fields"] if f["secret"]}

# Фоллбэк из переменных окружения для известных ключей.
_ENV_FALLBACK = {
    "yandex_disk.oauth_token": lambda: settings.yandex_disk_oauth_token,
    "yandex_disk.root": lambda: settings.yandex_disk_root,
}


async def get(session: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = await session.get(IntegrationSetting, key)
    if row and row.value:
        return row.value
    fb = _ENV_FALLBACK.get(key)
    if fb and (v := fb()):
        return v
    return default


async def current_values(session: AsyncSession) -> dict[str, str | None]:
    rows = (await session.scalars(select(IntegrationSetting))).all()
    return {r.key: r.value for r in rows}


async def set_many(session: AsyncSession, values: dict[str, str]) -> None:
    for k, v in values.items():
        if k not in ALL_KEYS:
            continue
        # Пустое значение для секрета = «не менять» (не затираем существующий).
        if k in SECRET_KEYS and v == "":
            continue
        row = await session.get(IntegrationSetting, k)
        if row is None:
            session.add(IntegrationSetting(key=k, value=v))
        else:
            row.value = v
    await session.commit()
