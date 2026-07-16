"""FSM-состояния диалога (aiogram). Бизнес-статус заказа живёт в backend."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    waiting_contact = State()  # выбран чехол, но нет телефона — ждём контакт перед заказом
    confirming = State()  # показано подтверждение (тип+модель+цена)
    waiting_name = State()  # Стандарт: ждём имя/букву
    waiting_materials = State()  # Кастом: ждём фото/материалы
    confirming_materials = State()  # Кастом: показана сводка материалов, ждём подтверждения
