"""Куда вести сценарий бота после подтверждённой оплаты. Без I/O."""

from __future__ import annotations

from app.enums import PaymentKind


def continuation_for(kind: PaymentKind, *, custom: bool, post_amount: float) -> str:
    """Следующий шаг после оплаты.

    pay_post — стандарт, в чат уходит ссылка на остаток.
    wait_mockup — кастом, ждём макет дизайнера.
    delivery — выбор службы доставки.
    fulfill — заявка в службу после оплаты доставки.
    """
    if kind == PaymentKind.PREPAYMENT and custom:
        return "wait_mockup"
    if kind == PaymentKind.PREPAYMENT and post_amount > 0:
        return "pay_post"
    if kind == PaymentKind.PREPAYMENT:
        return "delivery"
    if kind == PaymentKind.POSTPAYMENT:
        return "delivery"
    if kind == PaymentKind.DELIVERY:
        return "fulfill"
    return "ack"
