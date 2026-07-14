"""Машина статусов заказа (модель статусов ТЗ v2.0).

Описывает допустимые переходы, а также кто и по какому триггеру меняет статус.
Разделяет ветки Стандарт (а) и Кастом (б). Бизнес-логика спринтов 3–6 опирается
на `can_transition` / `assert_transition`, чтобы не допустить недопустимых переходов.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.enums import OrderStatus as S


class Changer(StrEnum):
    SYSTEM = "system"  # авто (webhook, действие клиента в боте, sendData)
    DESIGNER = "designer"  # вручную дизайнером в AdminUI
    BOTH = "both"  # система или дизайнер


@dataclass(frozen=True)
class Transition:
    to: S
    changer: Changer
    trigger: str


# Допустимые переходы: из статуса → список возможных следующих статусов.
# Ветвление Стандарт/Кастом отражено там, где пути расходятся.
TRANSITIONS: dict[S, list[Transition]] = {
    S.CASE_TYPE_SELECTED: [
        Transition(S.MODEL_SELECTED, Changer.SYSTEM, "Нажатие inline-кнопки модели"),
    ],
    S.MODEL_SELECTED: [
        Transition(S.CASE_CONFIRMED, Changer.SYSTEM, "Нажатие «Подтвердить»"),
    ],
    S.CASE_CONFIRMED: [
        # Стандарт: имя/буква → сразу предоплата. Кастом: материалы → предоплата.
        Transition(S.MATERIALS_SUBMITTED, Changer.SYSTEM, "Кастом: получены файлы/текст"),
        Transition(S.PREPAYMENT_ISSUED, Changer.SYSTEM, "Стандарт: получены имя/буква"),
    ],
    S.MATERIALS_SUBMITTED: [
        Transition(S.PREPAYMENT_ISSUED, Changer.SYSTEM, "Бот отправил ссылку предоплаты"),
    ],
    S.PREPAYMENT_ISSUED: [
        Transition(S.PREPAYMENT_PAID, Changer.SYSTEM, "Webhook предоплаты"),
        Transition(S.CANCELLED, Changer.BOTH, "Авто-отмена 72ч / вручную дизайнером"),
    ],
    S.PREPAYMENT_PAID: [
        # Стандарт: сразу постоплата (нет макета). Кастом: цикл дизайна.
        Transition(S.POSTPAYMENT_ISSUED, Changer.SYSTEM, "Стандарт: ссылка постоплаты"),
        Transition(S.HANDED_TO_DESIGN, Changer.DESIGNER, "Дизайнер: «Передан в дизайн»"),
    ],
    S.HANDED_TO_DESIGN: [
        Transition(S.DESIGN_IN_PROGRESS, Changer.DESIGNER, "Дизайнер: «Дизайн в процессе»"),
        Transition(S.CANCELLED, Changer.DESIGNER, "Ручная отмена дизайнером"),
    ],
    S.DESIGN_IN_PROGRESS: [
        Transition(S.MOCKUP_SENT, Changer.SYSTEM, "Дизайнер загрузил макет → отправка клиенту"),
        Transition(S.CANCELLED, Changer.DESIGNER, "Ручная отмена дизайнером"),
    ],
    S.MOCKUP_SENT: [
        Transition(S.MOCKUP_APPROVAL, Changer.SYSTEM, "Клиент нажал «Подтвердить»"),
        Transition(S.MOCKUP_REVISION, Changer.SYSTEM, "Клиент нажал «Переделать»"),
    ],
    S.MOCKUP_REVISION: [
        # Дизайнер общается вручную и загружает новый макет.
        Transition(S.MOCKUP_SENT, Changer.SYSTEM, "Дизайнер загрузил новый макет"),
        Transition(S.CANCELLED, Changer.DESIGNER, "Ручная отмена дизайнером"),
    ],
    S.MOCKUP_APPROVAL: [
        Transition(S.POSTPAYMENT_ISSUED, Changer.SYSTEM, "Ссылка постоплаты"),
    ],
    S.POSTPAYMENT_ISSUED: [
        Transition(S.POSTPAYMENT_PAID, Changer.SYSTEM, "Webhook постоплаты"),
        Transition(S.CANCELLED, Changer.BOTH, "Авто-отмена 72ч / вручную дизайнером"),
    ],
    S.POSTPAYMENT_PAID: [
        Transition(S.DELIVERY_SERVICE_SELECTION, Changer.SYSTEM, "Переход к выбору доставки"),
    ],
    S.DELIVERY_SERVICE_SELECTION: [
        Transition(S.DELIVERY_ADDRESS_SELECTION, Changer.SYSTEM, "Клиент выбрал службу"),
    ],
    S.DELIVERY_ADDRESS_SELECTION: [
        Transition(S.DELIVERY_PAYMENT, Changer.SYSTEM, "Клиент ввёл адрес"),
    ],
    S.DELIVERY_PAYMENT: [
        Transition(S.SHIPPED, Changer.SYSTEM, "Webhook сервиса доставки «Отправлен»"),
    ],
    S.SHIPPED: [
        Transition(S.DELIVERED, Changer.SYSTEM, "Webhook «Доставлено»"),
    ],
    S.DELIVERED: [
        Transition(S.REVIEW_OFFERED, Changer.SYSTEM, "Статус «Заказ получен»"),
    ],
    S.REVIEW_OFFERED: [
        Transition(S.REVIEW_RECEIVED, Changer.SYSTEM, "Клиент прислал отзыв"),
    ],
    # Терминальные статусы
    S.REVIEW_RECEIVED: [],
    S.CANCELLED: [],
}


def allowed_next(status: S) -> list[Transition]:
    return TRANSITIONS.get(status, [])


def can_transition(src: S, dst: S) -> bool:
    return any(t.to == dst for t in allowed_next(src))


def assert_transition(src: S, dst: S) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"Недопустимый переход статуса: {src} → {dst}")


class InvalidTransition(ValueError):
    """Попытка перевести заказ в статус, недостижимый из текущего."""
