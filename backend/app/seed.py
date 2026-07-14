"""Идемпотентный посев демо-данных для локальной разработки.

Запуск: `python -m app.seed` (из каталога backend с активным venv).
Наполняет: администратора, каталог типов чехлов, тексты сообщений бота (msg_XXX).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.constants import IPHONE_MODELS
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.enums import AdminRole, BotMessageMode, ReviewStatus
from app.models import AdminUser, BotMessage, CaseType, CaseTypeModel, Review

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
    ("msg_001", "Действие 1 (вход в бот)", "Привет! Это бот для заказа индивидуальных чехлов."),
    ("msg_002", "/start до получения контакта", "Поделитесь контактом, чтобы продолжить."),
    ("msg_003", "Контакт получен", "Готово! Выберите раздел в меню."),
    ("msg_004а", "WebApp.sendData, тип=Стандарт", "Вы выбрали стандартный чехол. Укажите модель."),
    ("msg_004б", "WebApp.sendData, тип=Кастом", "Вы выбрали кастом-чехол. Укажите модель."),
    ("msg_005аб", "Выбор модели iPhone", "Подтвердите заказ: {type}, {model}, цена {price} ₽."),
    ("msg_006а", "Подтверждение (Стандарт)", "Напишите имя или букву для чехла."),
    ("msg_006б", "Подтверждение (Кастом)", "Пришлите фото/файлы и опишите пожелание."),
    ("msg_007а", "Получение имени/буквы", "Чехол принят в работу. Внесите предоплату по кнопке."),
    ("msg_007б", "Получение файлов", "Чехол принят, ожидайте макет. Внесите предоплату."),
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
    ("msg_remind_1", "+5 мин после ссылки оплаты", "Напоминаем: заказ ждёт оплаты."),
    ("msg_remind_2", "+45 мин", "Напоминаем об оплате заказа."),
    ("msg_remind_3", "+3 часа", "Ваш заказ всё ещё ждёт оплаты."),
    ("msg_remind_4", "+24 часа", "Последнее напоминание: оплатите заказ, иначе он отменится."),
    ("msg_cancel", "+72 часа (авто-отмена)", "Заказ отменён из-за отсутствия оплаты."),
]


ADMIN_EMAIL = "admin@chehlii.local"


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
    for ct in CASE_TYPES:
        existing = await session.scalar(select(CaseType).where(CaseType.name == ct["name"]))
        if existing:
            continue
        case_type = CaseType(**ct)
        case_type.models = [CaseTypeModel(model_name=m, is_available=True) for m in IPHONE_MODELS]
        session.add(case_type)


async def seed_bot_messages(session) -> None:
    for code, trigger, text in BOT_MESSAGES:
        existing = await session.scalar(select(BotMessage).where(BotMessage.code == code))
        if existing:
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


async def main() -> None:
    async with SessionLocal() as session:
        await seed_admin(session)
        await seed_catalog(session)
        await seed_bot_messages(session)
        await seed_reviews(session)
        await session.commit()
    print("Seed завершён: администратор, каталог, тексты бота, отзывы.")


if __name__ == "__main__":
    asyncio.run(main())
