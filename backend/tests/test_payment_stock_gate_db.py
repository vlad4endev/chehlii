"""Нельзя платить за товар, которого нет: ссылка на оплату и заказ (реальная PostgreSQL)."""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select, update

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

A, B = "iPhone 15", "iPhone 16"


@pytest.fixture
async def world():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.enums import CaseBranch
    from app.models import CaseType, Client, Order
    from app.models.catalog import CaseTypeModel, IphoneModel
    from app.models.payment import Payment
    from app.models.warehouse import StockComponent, StockGroup, StockMovement

    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await s.execute(update(StockMovement).values(reverses_id=None))
        await s.execute(delete(StockMovement))
        await s.execute(delete(StockComponent))
        await s.execute(update(IphoneModel).values(stock_group_id=None))
        await s.execute(delete(StockGroup))
        await s.execute(delete(Payment))
        await s.execute(delete(Order))
        await s.execute(delete(CaseTypeModel))
        await s.execute(delete(CaseType))
        case = CaseType(name="Чёрный", plate_type="black", cost=900, margin=600, is_active=True)
        client = Client(channel="tg", channel_user_id="gate-1")
        s.add_all([case, client])
        await s.flush()
        for m in (A, B):
            s.add(CaseTypeModel(case_type_id=case.id, model_name=m, is_available=True))

        async def make_order(model: str = A, **kw) -> Order:
            fields = {
                "client_id": client.id,
                "case_type_id": case.id,
                "model_name": model,
                "branch": CaseBranch.STANDARD,
                "status": "case_confirmed",
                "cost": 900,
                "margin": 600,
            }
            order = Order(**{**fields, **kw})
            s.add(order)
            await s.flush()
            return order

        yield SimpleNamespace(
            session=s, case=case, client=client, make_order=make_order, Payment=Payment
        )
        await s.close()
        await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def api(world):
    import httpx

    from app.api.v1.internal import require_internal
    from app.core.database import get_session
    from app.main import app

    async def fake_session():
        yield world.session

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[require_internal] = lambda: None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _stock(s, model: str, base: int, plate: int, plate_type: str = "black") -> None:
    from app.services import warehouse as wh

    if base:
        await wh.supply(s, kind="base", model_name=model, qty=base)
    if plate:
        await wh.supply(s, kind="plate", model_name=model, plate_type=plate_type, qty=plate)


async def _payments(s) -> int:
    from app.models.payment import Payment

    return await s.scalar(select(func.count(Payment.id))) or 0


def _is_out_of_stock(res) -> bool:
    detail = res.json().get("detail")
    return res.status_code == 409 and isinstance(detail, dict) and detail["code"] == "out_of_stock"


LINK = "/api/v1/payments/link"


@pytest.mark.parametrize("kind", ["prepayment", "postpayment"])
async def test_no_stock_means_no_payment_link(api, world, kind) -> None:
    order = await world.make_order()

    res = await api.post(LINK, json={"order_id": order.id, "kind": kind})

    assert _is_out_of_stock(res), res.text
    assert A in res.json()["detail"]["message"]
    assert await _payments(world.session) == 0  # платёж не создан, платить нечем


@pytest.mark.parametrize(("base", "plate"), [(5, 0), (0, 5)])
async def test_half_a_pair_is_not_enough(api, world, base, plate) -> None:
    await _stock(world.session, A, base, plate)
    order = await world.make_order()

    res = await api.post(LINK, json={"order_id": order.id, "kind": "prepayment"})

    assert _is_out_of_stock(res)


async def test_wrong_plate_color_is_not_enough(api, world) -> None:
    await _stock(world.session, A, 5, 5, plate_type="silver")  # а тип чехла — на чёрной
    order = await world.make_order()

    assert _is_out_of_stock(await api.post(LINK, json={"order_id": order.id, "kind": "prepayment"}))


async def test_with_stock_the_gate_lets_the_request_through(api, world) -> None:
    await _stock(world.session, A, 1, 1)
    order = await world.make_order()

    res = await api.post(LINK, json={"order_id": order.id, "kind": "prepayment"})

    # Дальше — уже шлюзы (в тестовой базе не настроены), но не отказ по остатку.
    assert not _is_out_of_stock(res)


async def test_universal_group_stock_is_shared_between_models(api, world) -> None:
    from app.services import stock_groups as sg

    await _stock(world.session, A, 1, 1)  # остаток есть только «на A»
    await sg.save_group(world.session, name="Общая", scope="both", models=[A, B])
    order_b = await world.make_order(B)

    res = await api.post(LINK, json={"order_id": order_b.id, "kind": "prepayment"})

    assert not _is_out_of_stock(res)  # B получает остаток группы


async def test_group_with_zero_stock_blocks_every_member(api, world) -> None:
    from app.services import stock_groups as sg

    await sg.save_group(world.session, name="Общая", scope="both", models=[A, B])
    for model in (A, B):
        order = await world.make_order(model)
        assert _is_out_of_stock(
            await api.post(LINK, json={"order_id": order.id, "kind": "prepayment"})
        )


async def test_custom_order_balance_message_mentions_the_prepayment(api, world) -> None:
    from app.enums import CaseBranch

    order = await world.make_order(branch=CaseBranch.CUSTOM, status="mockup_approval")

    res = await api.post(LINK, json={"order_id": order.id, "kind": "postpayment"})

    assert _is_out_of_stock(res)
    assert "предоплату" in res.json()["detail"]["message"]


async def test_delivery_payment_is_never_blocked_by_stock(api, world) -> None:
    order = await world.make_order(status="delivery_payment")

    res = await api.post(LINK, json={"order_id": order.id, "kind": "delivery"})

    assert not _is_out_of_stock(res)


@pytest.mark.parametrize("override", [{"is_test": True}, {"stock_deducted": True}])
async def test_test_and_already_deducted_orders_are_not_gated(api, world, override) -> None:
    order = await world.make_order(**override)

    res = await api.post(LINK, json={"order_id": order.id, "kind": "prepayment"})

    assert not _is_out_of_stock(res)


async def test_unknown_order_is_still_404(api) -> None:
    assert (await api.post(LINK, json={"order_id": 10**9, "kind": "prepayment"})).status_code == 404


# ── создание заказа ───────────────────────────────────────────────────────


def _order_body(world, model: str) -> dict:
    return {
        "client_id": world.client.id,
        "case_type_id": world.case.id,
        "branch": "standard",
        "model_name": model,
    }


async def test_cannot_create_an_order_for_a_model_without_stock(api, world) -> None:
    from app.models import Order

    res = await api.post("/api/v1/orders", json=_order_body(world, A))

    assert _is_out_of_stock(res), res.text
    assert await world.session.scalar(select(func.count(Order.id))) == 0  # заказ не заведён


async def test_order_is_created_when_stock_exists_including_group_stock(api, world) -> None:
    from app.services import stock_groups as sg

    await _stock(world.session, A, 1, 1)
    assert (await api.post("/api/v1/orders", json=_order_body(world, A))).status_code == 200

    await sg.save_group(world.session, name="Общая", scope="both", models=[A, B])
    assert (await api.post("/api/v1/orders", json=_order_body(world, B))).status_code == 200
