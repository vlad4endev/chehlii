"""Товара нет на складе: бот честно отказывает, а не обещает «ссылка придёт позже»."""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

os.environ.setdefault("TG_BOT_TOKEN", "123456:test")

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bots.core import payments
from bots.core.backend import Backend, OutOfStock, raise_if_out_of_stock
from bots.tg import handlers
from bots.tg.states import OrderFlow

MESSAGE = "К сожалению, для iPhone 15 сейчас нет в наличии — оплатить пока нельзя."


def _response(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://t/x"))


def test_out_of_stock_detail_becomes_an_exception_with_the_text() -> None:
    res = _response(409, {"detail": {"code": "out_of_stock", "message": MESSAGE}})
    with pytest.raises(OutOfStock) as err:
        raise_if_out_of_stock(res)
    assert err.value.message == MESSAGE


@pytest.mark.parametrize(
    "response",
    [
        _response(200, {"ok": True}),
        _response(409, {"detail": "Недостаточно на складе"}),  # обычный конфликт — не наш случай
        _response(409, {"detail": {"code": "something_else", "message": "x"}}),
        _response(409, {}),
        httpx.Response(409, text="не json", request=httpx.Request("POST", "http://t/x")),
        _response(500, {"detail": {"code": "out_of_stock", "message": "x"}}),
    ],
)
def test_other_responses_are_left_alone(response) -> None:
    raise_if_out_of_stock(response)  # не бросает


def _backend_with(handler) -> Backend:
    backend = Backend()
    backend._client = httpx.AsyncClient(
        base_url="http://backend", transport=httpx.MockTransport(handler)
    )
    return backend


async def test_backend_client_raises_out_of_stock_for_link_and_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": {"code": "out_of_stock", "message": MESSAGE}})

    backend = _backend_with(handler)
    with pytest.raises(OutOfStock):
        await backend.payment_link(5, "prepayment")
    with pytest.raises(OutOfStock):
        await backend.create_order(1, 2, "standard", "iPhone 15")


async def test_other_backend_errors_still_raise_http_errors() -> None:
    backend = _backend_with(lambda request: httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(httpx.HTTPStatusError):
        await backend.payment_link(5)


async def test_payment_block_says_no_stock_and_has_no_pay_buttons(monkeypatch) -> None:
    monkeypatch.setattr(
        payments, "backend", SimpleNamespace(payment_link=AsyncMock(side_effect=OutOfStock(MESSAGE)))
    )

    block = await payments.block(5, "prepayment")

    assert block.text == MESSAGE
    assert block.buttons == []
    assert "придёт следующим сообщением" not in block.text  # не обещаем ссылку, которой не будет


async def test_payment_block_keeps_the_old_fallback_for_other_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        payments, "backend", SimpleNamespace(payment_link=AsyncMock(side_effect=RuntimeError("шлюз")))
    )

    block = await payments.block(5)

    assert block.buttons == [] and "придёт следующим сообщением" in block.text


async def test_telegram_selection_without_stock_creates_no_order(monkeypatch) -> None:
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
    await state.update_data(pending_case_id=7, pending_case_type="standard", pending_model="iPhone 15")
    backend = SimpleNamespace(
        create_order=AsyncMock(side_effect=OutOfStock(MESSAGE)), mark_journey=AsyncMock()
    )
    monkeypatch.setattr(handlers, "backend", backend)
    msg = SimpleNamespace(answer=AsyncMock(), date=datetime.now())

    await handlers._begin_order(msg, state, 1, 7, "standard", "iPhone 15")

    msg.answer.assert_awaited_once()
    assert msg.answer.await_args.args[0] == MESSAGE
    assert await state.get_state() != OrderFlow.confirming.state  # до подтверждения не дошли
    data = await state.get_data()
    assert data["pending_case_id"] is None and data["pending_model"] is None
    backend.mark_journey.assert_not_awaited()
