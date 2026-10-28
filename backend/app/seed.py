"""Идемпотентный посев демо-данных для локальной разработки.

Запуск: `python -m app.seed` (из каталога backend с активным venv).
Наполняет: администратора, каталог типов чехлов, тексты сообщений бота (msg_XXX).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.enums import AdminRole, BotMessageMode, ReviewStatus
from app.models import AdminUser, BotMessage, CaseType, CaseTypeModel, Review
from app.models.settings import IntegrationSetting
from app.services import iphone_models as im
from app.services import promo
from app.services import warehouse as wh

CASE_TYPES = [
    {
        "name": "Классика",
        "is_custom": False,
        "description": "Однотонный чехол с гравировкой имени или буквы.",
        "photo_url": "https://example.com/cases/classic.jpg",
        "cost": 450,
        "margin": 750,
    },
    {
        "name": "Минимал",
        "is_custom": False,
        "description": "Матовый чехол, лаконичный дизайн.",
        "photo_url": "https://example.com/cases/minimal.jpg",
        "cost": 500,
        "margin": 800,
    },
    {
        "name": "Арт-кастом",
        "is_custom": True,
        "description": "Индивидуальный дизайн по вашим фото и пожеланиям.",
        "photo_url": "https://example.com/cases/art.jpg",
        "cost": 900,
        "margin": 1600,
    },
]

# Тексты-заглушки; финальные пишет заказчик и редактирует через AdminUI (Спринт 8).
BOT_MESSAGES = [
    (
        "msg_001",
        "Действие 1 (вход в бот)",
        "Привет! Это casetop — бот для заказа индивидуальных чехлов.",
    ),
    ("msg_002", "/start до получения контакта", "Поделитесь контактом, чтобы продолжить."),
    ("msg_003", "Контакт получен", "Готово! Выберите раздел в меню."),
    ("msg_004а", "WebApp.sendData, тип=Стандарт", "Вы выбрали стандартный чехол. Укажите модель."),
    ("msg_004б", "WebApp.sendData, тип=Кастом", "Вы выбрали кастом-чехол. Укажите модель."),
    ("msg_005аб", "Выбор модели iPhone", "Подтвердите заказ: {type}, {model}, цена {price} ₽."),
    ("msg_006а", "Подтверждение (Стандарт, устарело)", "Напишите имя или букву для чехла."),
    ("msg_006б", "Кастом: запрос фото", "Пришлите фото или файлы для кастом-чехла."),
    (
        "msg_006б_done",
        "Кастом: фото получены",
        "Готово. Теперь опишите пожелание текстом — или нажмите «Без описания».",
    ),
    (
        "msg_006б_desc",
        "Кастом: запрос описания",
        "Опишите пожелание текстом — или нажмите «Без описания».",
    ),
    (
        "msg_006б_summary",
        "Кастом: сводка материалов",
        "Проверьте кастом-чехол:\nОписание: {desc}\nВложений: {files}",
    ),
    ("msg_007а", "Стандарт: полная оплата", "Чехол принят в работу. Оплатите полную стоимость по кнопке."),
    ("msg_007б", "Получение файлов", "Чехол принят, ожидайте макет. Внесите предоплату."),
    (
        "msg_001_hint",
        "Подсказка после старта",
        "Если что-то непонятно — нажмите в меню кнопку «Позвать человека».",
    ),
    (
        "welcome_back",
        "Повторный /start (есть контакт)",
        "С возвращением! Ваша скидка — {discount}%.",
    ),
    (
        "msg_offscript",
        "Сообщение вне сценария",
        "Передали ваше сообщение менеджеру — ответим здесь. "
        "Чтобы продолжить оформление, нажмите кнопку выше.",
    ),
    ("msg_008а", "Webhook предоплаты (Стандарт)", "Предоплата прошла. Ожидайте ссылку постоплаты."),
    ("msg_008б", "Webhook предоплаты (Кастом)", "Предоплата прошла. Ожидайте макет."),
    ("msg_009аб", "Дизайнер загрузил макет", "Ваш макет готов. Подтвердите или переделать."),
    ("msg_010б_x", "Клиент подтвердил макет", "Отлично! Внесите постоплату по кнопке."),
    ("msg_011аб", "Webhook постоплаты", "Оплата прошла. Выберите службу доставки."),
    ("msg_012аб", "Выбор доставки", "Укажите адрес (дом или ПВЗ)."),
    ("msg_013аб", "Подтверждение адреса", "Адрес принят. Оплатите доставку по ссылке."),
    ("msg_014аб", "Статус доставки «Отправлен»", "Заказ отправлен. Трек: {tracking}."),
    ("msg_015аб", "Статус доставки «Получен»", "Ваш заказ прибыл. Спасибо за покупку!"),
    ("msg_016", "Запрос отзыва", "Оставьте отзыв и пришлите фото чехла — будем благодарны!"),
    ("msg_017", "Отзыв получен", "Спасибо за отзыв! Нам очень приятно ✨"),
    ("msg_remind_1", "+5 мин после ссылки оплаты", "Напоминаем: заказ ждёт оплаты."),
    ("msg_remind_2", "+45 мин", "Напоминаем об оплате заказа."),
    ("msg_remind_3", "+3 часа", "Ваш заказ всё ещё ждёт оплаты."),
    ("msg_remind_4", "+24 часа", "Последнее напоминание: оплатите заказ, иначе он отменится."),
    ("msg_cancel", "+72 часа (авто-отмена)", "Заказ отменён из-за отсутствия оплаты."),
    (
        "msg_help",
        "Кнопка «Позвать человека»",
        "Менеджер подключится в ближайшее время — пишите здесь. "
        "Можно текст, фото и голосовые.\n\n"
        "Оформление заказа можно продолжить кнопками выше.",
    ),
    (
        "msg_help_ack",
        "Клиент написал в консультацию",
        "Передали ваше сообщение менеджеру — ответим здесь. "
        "Чтобы продолжить оформление, нажмите кнопку выше.",
    ),
    (
        "msg_help_close",
        "Продавец закрыл консультацию",
        "Диалог закрыт. Если понадобится помощь, напишите сюда или нажмите «Позвать человека».",
    ),
]


ADMIN_EMAIL = "admin@casetop.local"


async def seed_admin(session) -> None:
    existing = await session.scalar(select(AdminUser).where(AdminUser.email == ADMIN_EMAIL))
    if existing:
        return
    session.add(
        AdminUser(
            email=ADMIN_EMAIL,
            full_name="Администратор",
            password_hash=hash_password("admin123"),
            role=AdminRole.ADMIN,
        )
    )


async def seed_catalog(session) -> None:
    models = await im.list_model_names(session)
    for ct in CASE_TYPES:
        existing = await session.scalar(select(CaseType).where(CaseType.name == ct["name"]))
        if existing:
            continue
        case_type = CaseType(**ct)
        case_type.models = [CaseTypeModel(model_name=m, is_available=True) for m in models]
        session.add(case_type)


# Коды, которые при сиде перезаписываем (приёмка 23.10 — смена формулировок).
_REFRESH_MSG_CODES = {
    "msg_001_hint",
    "msg_006б",
    "msg_007а",
    "msg_help",
    "msg_help_ack",
    "msg_help_close",
    "msg_offscript",
}


async def seed_bot_messages(session) -> None:
    for code, trigger, text in BOT_MESSAGES:
        existing = await session.scalar(select(BotMessage).where(BotMessage.code == code))
        if existing:
            if code in _REFRESH_MSG_CODES and existing.text != text:
                existing.text = text
                existing.trigger = trigger
            continue
        session.add(BotMessage(code=code, trigger=trigger, text=text, mode=BotMessageMode.AUTO))


_P = ReviewStatus.PUBLISHED
_M = ReviewStatus.PENDING
SAMPLE_REVIEWS = [
    ("Марина", "Кастом по рисунку — точь-в-точь, печать супер.", _P),
    ("Илья", "Гравировка аккуратная, пришло быстро.", _P),
    ("Sofia", "Дизайнер помог с макетом. Рекомендую.", _M),
    ("Артём", "Взял в подарок с инициалами — супер.", _M),
    ("Ольга", "Немного задержали, но чехол отличный!", _M),
]


async def seed_reviews(session) -> None:
    if await session.scalar(select(Review).limit(1)):
        return
    for name, text, status in SAMPLE_REVIEWS:
        session.add(Review(author_name=name, text=text, status=status))


async def seed_warehouse(session) -> None:
    """Балванки + серебряные/чёрные пластины по всем моделям канона (qty 0)."""
    await wh.ensure_components(session)


# Дефолты приёмки 23.10: друг / пригласившему / потолок. Не затираем ненулевые.
_PROMO_DEFAULTS = {
    promo.FRIEND_KEY: "5",
    promo.INVITER_KEY: "5",
    promo.MAX_KEY: "20",
}


async def seed_promo_defaults(session) -> None:
    """Проставить 5/5/20, если ключа нет или значение пустое/0."""
    for key, val in _PROMO_DEFAULTS.items():
        row = await session.get(IntegrationSetting, key)
        if row is None:
            session.add(IntegrationSetting(key=key, value=val))
            continue
        cur = (row.value or "").strip()
        if cur in ("", "0", "0.0"):
            row.value = val


async def main() -> None:
    async with SessionLocal() as session:
        await im.ensure_seeded(session)
        await seed_admin(session)
        await seed_catalog(session)
        await seed_bot_messages(session)
        await seed_reviews(session)
        await seed_warehouse(session)
        await seed_promo_defaults(session)
        await session.commit()
    print("Seed завершён: администратор, каталог, тексты бота, отзывы, склад, промо.")


if __name__ == "__main__":
    asyncio.run(main())
