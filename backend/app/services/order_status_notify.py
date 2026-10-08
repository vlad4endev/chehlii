"""Уведомления клиенту при ручной смене статуса заказа (AdminUI).

Макетные статусы (`mockup_*`) сюда не входят — `msg_009аб` уходит только
при загрузке файла (`POST /admin/orders/{id}/mockup`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CaseBranch, OrderStatus, PaymentKind
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import cdek_checkout, consult, integrations, pricing, review_offer
from app.services.payment_flow import continuation_for

# Статусы макета: сообщения только при прикреплении файла, не при PATCH status.
MOCKUP_STATUSES = frozenset(
    {
        OrderStatus.MOCKUP_SENT,
        OrderStatus.MOCKUP_APPROVAL,
        OrderStatus.MOCKUP_REVISION,
    }
)

_FALLBACK = {
    "msg_007а": "Чехол принят в работу. Внесите предоплату по кнопке.",
    "msg_007б": "Чехол принят, ожидайте макет. Внесите предоплату.",
    "msg_008а": "Предоплата прошла. Осталось оплатить остаток — кнопка ниже.",
    "msg_008б": "Предоплата прошла. Ожидайте макет.",
    "msg_010б_x": "Отлично! Внесите постоплату по кнопке.",
    "msg_011аб": "Оплата прошла. Выберите службу доставки.",
    "msg_014аб": "Заказ отправлен. Трек: {tracking}.",
    "msg_015аб": "Ваш заказ прибыл. Спасибо за покупку!",
    "msg_016": "Оставьте отзыв и пришлите фото чехла — будем благодарны!",
    "msg_017": "Спасибо за отзыв! Нам очень приятно ✨",
    "msg_cancel": "Заказ отменён из-за отсутствия оплаты.",
}


@dataclass(frozen=True)
class NotifyResult:
    notified: bool = False
    code: str | None = None


def _queue(
    client: Client,
    order_id: int,
    text: str,
    *,
    kind: str = "text",
    media: list | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        client_id=client.id,
        channel=client.channel,
        channel_user_id=client.channel_user_id,
        order_id=order_id,
        kind=kind,
        text=text,
        media=media,
    )


async def scenario_text(session: AsyncSession, code: str) -> str:
    text = await consult.bot_message_text(session, code)
    if not text or text == code:
        return _FALLBACK.get(code, code)
    return text


def _branch_prepay_code(order: Order) -> str:
    return "msg_007б" if order.branch == CaseBranch.CUSTOM else "msg_007а"


def payment_amount(order: Order, kind: PaymentKind, percent: float) -> float:
    priced = pricing.compute(
        order.cost or 0, order.margin or 0, float(order.total_discount or 0)
    )
    disc = float(priced.price_with_discount)
    prepay = round(disc * percent / 100, 2)
    if kind == PaymentKind.PREPAYMENT:
        return prepay
    if kind == PaymentKind.POSTPAYMENT:
        return round(disc - prepay, 2)
    if kind == PaymentKind.DELIVERY:
        return float(order.delivery_cost or 0)
    return 0.0


async def continue_after_paid(
    session: AsyncSession,
    order: Order,
    client: Client | None,
    *,
    kind: PaymentKind,
) -> NotifyResult:
    """Следующий шаг сценария после оплаты (webhook или ручной статус «оплачено»)."""
    percent = float(await integrations.get(session, "payment.prepay_percent", "50") or 50)
    custom = order.branch == CaseBranch.CUSTOM
    step = continuation_for(
        kind, custom=custom, post_amount=payment_amount(order, PaymentKind.POSTPAYMENT, percent)
    )
    if step == "wait_mockup":
        if client is not None:
            text = await scenario_text(session, "msg_008б")
            session.add(_queue(client, order.id, text))
        return NotifyResult(True, "msg_008б")
    if step == "pay_post":
        if client is not None:
            text = await scenario_text(session, "msg_008а")
            session.add(
                _queue(
                    client,
                    order.id,
                    text,
                    kind="pay",
                    media=[{"type": "pay", "kind": "postpayment"}],
                )
            )
        return NotifyResult(True, "msg_008а")
    if step == "delivery":
        if kind == PaymentKind.PREPAYMENT and order.status == OrderStatus.PREPAYMENT_PAID:
            order.status = OrderStatus.POSTPAYMENT_PAID
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    status=OrderStatus.POSTPAYMENT_PAID,
                    changed_by="system",
                    trigger="Предоплата покрыла заказ",
                    created_at=datetime.now(UTC),
                )
            )
        text = await scenario_text(session, "msg_011аб")
        await cdek_checkout.start_after_postpayment(session, order, client, text=text)
        return NotifyResult(True, "msg_011аб")
    if step == "fulfill":
        await cdek_checkout.fulfill(session, order, client)
        return NotifyResult(True, None)
    if client is not None:
        session.add(_queue(client, order.id, f"Оплата получена ✅ Заказ #{order.id} в работе."))
        return NotifyResult(True, None)
    return NotifyResult()


async def enqueue_shipped(
    session: AsyncSession, order: Order, client: Client | None
) -> NotifyResult:
    if client is None:
        return NotifyResult()
    raw = await scenario_text(session, "msg_014аб")
    tracking = order.tracking_code or "—"
    text = raw.replace("{tracking}", tracking)
    session.add(_queue(client, order.id, text))
    return NotifyResult(True, "msg_014аб")


async def enqueue_delivered(
    session: AsyncSession, order: Order, client: Client | None
) -> NotifyResult:
    if client is None:
        return NotifyResult()
    text = await scenario_text(session, "msg_015аб")
    session.add(_queue(client, order.id, text))
    return NotifyResult(True, "msg_015аб")


async def offer_review_after_delivered(
    session: AsyncSession, order: Order, client: Client | None, *, trigger: str
) -> NotifyResult:
    """После «Заказ получен» — сразу предложение отзыва (как webhook доставки)."""
    if order.status == OrderStatus.REVIEW_OFFERED:
        await review_offer.enqueue(session, order, client)
        return NotifyResult(True, "msg_016")
    order.status = OrderStatus.REVIEW_OFFERED
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=OrderStatus.REVIEW_OFFERED,
            changed_by="system",
            trigger=trigger,
            created_at=datetime.now(UTC),
        )
    )
    await review_offer.enqueue(session, order, client)
    return NotifyResult(True, "msg_016")


async def notify_after_manual_status(
    session: AsyncSession,
    order: Order,
    prev: OrderStatus,
    new: OrderStatus,
) -> NotifyResult:
    """Поставить сценарий в outbox после ручной смены статуса. Коммит — на вызывающем."""
    if prev == new:
        return NotifyResult()
    if new in MOCKUP_STATUSES:
        return NotifyResult()

    client = await session.get(Client, order.client_id)

    if new == OrderStatus.PREPAYMENT_ISSUED:
        code = _branch_prepay_code(order)
        if client is not None:
            text = await scenario_text(session, code)
            session.add(
                _queue(
                    client,
                    order.id,
                    text,
                    kind="pay",
                    media=[{"type": "pay", "kind": "prepayment"}],
                )
            )
        return NotifyResult(client is not None, code)

    if new == OrderStatus.POSTPAYMENT_ISSUED:
        if client is not None:
            text = await scenario_text(session, "msg_010б_x")
            session.add(
                _queue(
                    client,
                    order.id,
                    text,
                    kind="pay",
                    media=[{"type": "pay", "kind": "postpayment"}],
                )
            )
        return NotifyResult(client is not None, "msg_010б_x")

    if new == OrderStatus.PREPAYMENT_PAID:
        return await continue_after_paid(session, order, client, kind=PaymentKind.PREPAYMENT)

    if new == OrderStatus.POSTPAYMENT_PAID:
        return await continue_after_paid(session, order, client, kind=PaymentKind.POSTPAYMENT)

    if new == OrderStatus.DELIVERY_SERVICE_SELECTION:
        # Блок выбора службы — тот же, что после постоплаты.
        if client is None:
            return NotifyResult()
        text = await scenario_text(session, "msg_011аб")
        session.add(_queue(client, order.id, text, kind="delivery"))
        return NotifyResult(True, "msg_011аб")

    if new == OrderStatus.SHIPPED:
        return await enqueue_shipped(session, order, client)

    if new == OrderStatus.DELIVERED:
        delivered = await enqueue_delivered(session, order, client)
        review = await offer_review_after_delivered(
            session, order, client, trigger="AdminUI: после «Заказ получен»"
        )
        if delivered.notified and review.notified:
            code = "msg_015аб+msg_016"
        else:
            code = delivered.code or review.code
        return NotifyResult(delivered.notified or review.notified, code)

    if new == OrderStatus.REVIEW_OFFERED:
        await review_offer.enqueue(session, order, client)
        return NotifyResult(True, "msg_016")

    if new == OrderStatus.REVIEW_RECEIVED:
        if client is not None:
            text = await scenario_text(session, "msg_017")
            session.add(_queue(client, order.id, text))
        return NotifyResult(client is not None, "msg_017")

    if new == OrderStatus.CANCELLED:
        if client is not None:
            text = await scenario_text(session, "msg_cancel")
            session.add(_queue(client, order.id, text))
        return NotifyResult(client is not None, "msg_cancel")

    return NotifyResult()
