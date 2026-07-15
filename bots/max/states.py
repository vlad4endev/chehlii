"""FSM-состояния диалога MAX (maxapi). Бизнес-статус заказа живёт в backend."""

from __future__ import annotations

from maxapi.context.state_machine import State, StatesGroup


class OrderFlow(StatesGroup):
    waiting_phone = State()  # Ждём телефон (fallback R1: текстовый ввод)
    confirming = State()  # Показано подтверждение (тип+модель+цена)
    waiting_name = State()  # Стандарт: ждём имя/букву
    waiting_materials = State()  # Кастом: ждём фото/материалы
    confirming_materials = State()  # Кастом: показана сводка материалов, ждём подтверждения
