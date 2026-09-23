"""Тесты оформления СДЭК: адрес, статусы и сообщение после постоплаты. Сеть не трогаем."""

import asyncio
from types import SimpleNamespace

from app.enums import Channel
from app.enums import OrderStatus as S
from app.services.cdek_checkout import (
    DELIVERY_CHAIN,
    decode_destination,
    encode_destination,
    start_after_postpayment,
    statuses_to_apply,
)


def test_encode_decode_pvz():
    stored = encode_destination(pickup_point_id="NSK12", label="Новосибирск, Красный 1")
    assert stored.startswith("pvz:NSK12|")
    d = decode_destination(stored)
    assert d["pickup_point_id"] == "NSK12"
    assert d["to_address"] is None
    assert "Красный" in d["label"]


def test_encode_decode_door():
    stored = encode_destination(to_postal="101000", to_address="Москва, Тверская 1")
    d = decode_destination(stored)
    assert d["pickup_point_id"] is None
    assert d["to_postal"] == "101000"
    assert d["to_address"] == "Москва, Тверская 1"


def test_legacy_plain_address_is_door():
    d = decode_destination("Москва, Арбат 10")
    assert d["to_address"] == "Москва, Арбат 10"
    assert d["pickup_point_id"] is None


def test_delivery_chain_from_paid():
    assert statuses_to_apply(S.POSTPAYMENT_PAID, S.DELIVERY_SERVICE_SELECTION) == [
        S.DELIVERY_SERVICE_SELECTION
    ]
    assert statuses_to_apply(S.DELIVERY_SERVICE_SELECTION, S.DELIVERY_PAYMENT) == [
        S.DELIVERY_ADDRESS_SELECTION,
        S.DELIVERY_PAYMENT,
    ]
    assert statuses_to_apply(S.DELIVERY_PAYMENT, S.DELIVERY_PAYMENT) == []
    assert DELIVERY_CHAIN[0] == S.POSTPAYMENT_PAID


class _Session:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def test_start_after_postpayment_queues_delivery_buttons():
    """После оплаты чехла в outbox уходит kind=delivery — бот рисует выбор службы."""
    session = _Session()
    order = SimpleNamespace(id=9, status=S.POSTPAYMENT_PAID, client_id=1)
    client = SimpleNamespace(id=1, channel=Channel.TG, channel_user_id="100")
    asyncio.run(start_after_postpayment(session, order, client))
    assert order.status == S.DELIVERY_SERVICE_SELECTION
    kinds = [getattr(x, "kind", None) for x in session.added]
    assert "delivery" in kinds
    msg = next(x for x in session.added if getattr(x, "kind", None) == "delivery")
    assert msg.order_id == 9
    assert "доставк" in (msg.text or "").lower()


def test_start_after_postpayment_skips_when_not_in_delivery_window():
    session = _Session()
    order = SimpleNamespace(id=9, status=S.MOCKUP_APPROVAL, client_id=1)
    client = SimpleNamespace(id=1, channel=Channel.TG, channel_user_id="100")
    asyncio.run(start_after_postpayment(session, order, client))
    assert order.status == S.MOCKUP_APPROVAL
    assert not any(getattr(x, "kind", None) == "delivery" for x in session.added)
