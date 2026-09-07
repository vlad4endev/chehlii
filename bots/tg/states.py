"""FSM-состояния диалога (aiogram). Бизнес-статус заказа живёт в backend."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    waiting_contact = State()  # выбран чехол, но нет телефона — ждём контакт перед заказом
    confirming = State()  # показано подтверждение (тип+модель+цена)
    waiting_name = State()  # Стандарт: ждём имя/букву
    waiting_materials = State()  # Кастом: ждём фото/материалы
    confirming_materials = State()  # Кастом: показана сводка материалов, ждём подтверждения
    delivery_mode = State()  # служба / ПВЗ или курьер
    delivery_city = State()  # город или индекс
    delivery_address = State()  # улица/дом до двери
    delivery_pvz = State()  # выбор пункта из списка
    consulting = State()  # «Поможем выбрать» — переписка с продавцом
