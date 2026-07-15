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
        "hint": "Служба доставки: расчёт стоимости, заявка, статус. Отправитель — ваш склад.",
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
                "key": "cdek.from_postal",
                "label": "Индекс отправителя (склад)",
                "secret": False,
                "placeholder": "101000",
            },
            {
                "key": "cdek.tariff_code",
                "label": "Код тарифа",
                "secret": False,
                "placeholder": "137 (склад-дверь)",
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
        ],
    },
    {
        "id": "payment",
        "title": "Оплата (Robokassa)",
        "hint": (
            "Приём предоплаты и постоплаты. В ЛК Robokassa укажите ResultURL, Success и "
            "Fail (см. подсказку под полями)."
        ),
        "fields": [
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
