"""FSM-состояния диалога MAX (maxapi). Бизнес-статус заказа живёт в backend.

Имена совпадают с Telegram (`waiting_contact` и т.д.) — один сценарий админки.
"""

from __future__ import annotations

from maxapi.context.state_machine import State, StatesGroup


class OrderFlow(StatesGroup):
    waiting_contact = State()  # выбран чехол, нет телефона — ждём контакт/текст
    confirming = State()  # Показано подтверждение (тип+модель+цена)
    waiting_name = State()  # Стандарт: ждём имя/букву
    waiting_materials = State()  # Кастом: ждём фото/материалы
    confirming_materials = State()  # Кастом: сводка материалов, ждём подтверждения
    delivery_mode = State()
    delivery_city = State()
    delivery_address = State()
    delivery_pvz = State()
    consulting = State()  # «Поможем выбрать»
