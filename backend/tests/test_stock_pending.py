"""Заказы, ждущие списания со склада: правила (без БД) и работа на реальной PostgreSQL."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.enums import CaseBranch, OrderStatus
from app.services.stock_pending import (
    CUSTOM_PAID,
    STANDARD_PAID,
    is_awaiting_deduction,
)


def _order(**kw) -> SimpleNamespace:
    base = {
        "stock_deducted": False,
        "deleted_at": None,
        "is_test": False,
        "case_type_id": 1,
        "model_name": "iPhone 15",
        "branch": CaseBranch.STANDARD,
        "status": OrderStatus.PREPAYMENT_PAID,
    }
    return SimpleNamespace(**{**base, **kw})


def test_standard_order_waits_from_full_prepayment() -> None:
    assert is_awaiting_deduction(_order(status=OrderStatus.PREPAYMENT_PAID))
    assert is_awaiting_deduction(_order(status=OrderStatus.SHIPPED))
    assert not is_awaiting_deduction(_order(status=OrderStatus.PREPAYMENT_ISSUED))


def test_custom_order_waits_only_from_postpayment() -> None:
    custom = {"branch": CaseBranch.CUSTOM}
    assert not is_awaiting_deduction(_order(**custom, status=OrderStatus.PREPAYMENT_PAID))
    assert not is_awaiting_deduction(_order(**custom, status=OrderStatus.DESIGN_IN_PROGRESS))
    assert is_awaiting_deduction(_order(**custom, status=OrderStatus.POSTPAYMENT_PAID))


@pytest.mark.parametrize(
    "override",
    [
        {"stock_deducted": True},
        {"deleted_at": datetime.now(UTC)},
        {"is_test": True},
        {"case_type_id": None},
        {"model_name": None},
        {"status": OrderStatus.CANCELLED},
    ],
)
def test_orders_that_need_nothing_are_not_listed(override) -> None:
    assert not is_awaiting_deduction(_order(**override))


def test_cancelled_is_never_paid() -> None:
    assert OrderStatus.CANCELLED not in STANDARD_PAID | CUSTOM_PAID
    assert CUSTOM_PAID < STANDARD_PAID  # кастомный список — часть стандартного


# ── реальная база ─────────────────────────────────────────────────────────

DB_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")


@pytest.fixture
async def world():
    from sqlalchemy import delete, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.models import CaseType, Client, Order
    from app.models.catalog import CaseTypeModel, IphoneModel
    from app.models.warehouse import StockComponent, StockGroup, StockMovement

    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await s.execute(delete(StockMovement))
        await s.execute(delete(StockComponent))
        await s.execute(update(IphoneModel).values(stock_group_id=None))
        await s.execute(delete(StockGroup))
        await s.execute(delete(Order))
        case = CaseType(name="Ждёт", plate_type="black", cost=1, margin=1)
        s.add(case)
        await s.flush()
        s.add(CaseTypeModel(case_type_id=case.id, model_name="iPhone 15"))
        client = Client(channel="tg", channel_user_id="pend-1")
        s.add(client)
        await s.flush()

        async def make_order(**kw) -> Order:
            defaults = {
                "client_id": client.id,
                "case_type_id": case.id,
                "model_name": "iPhone 15",
                "branch": CaseBranch.STANDARD,
                "status": OrderStatus.PREPAYMENT_PAID,
            }
            order = Order(**{**defaults, **kw})
            s.add(order)
            await s.flush()
            return order

        yield SimpleNamespace(session=s, make_order=make_order)
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _stock(session, base: int, plate: int) -> None:
    from app.services import warehouse as wh

    if base:
        await wh.supply(session, kind="base", model_name="iPhone 15", qty=base)
    if plate:
        await wh.supply(
            session, kind="plate", model_name="iPhone 15", plate_type="black", qty=plate
        )


@needs_db
async def test_list_marks_only_what_stock_can_cover_in_order(world) -> None:
    from app.services import stock_pending as sp

    first = await world.make_order()
    second = await world.make_order()
    await world.make_order(status=OrderStatus.PREPAYMENT_ISSUED)  # не оплачен — не в списке
    await _stock(world.session, base=1, plate=1)  # хватает на одну пару

    items = await sp.list_pending(world.session)

    assert [i["order_id"] for i in items] == [first.id, second.id]
    assert [i["can_deduct"] for i in items] == [True, False]  # вторая пара — нет остатка


@needs_db
async def test_deduct_one_succeeds_then_leaves_queue(world) -> None:
    from sqlalchemy import select

    from app.models.warehouse import StockComponent
    from app.services import stock_pending as sp

    order = await world.make_order()
    await _stock(world.session, base=2, plate=2)

    await sp.deduct_one(world.session, order.id)

    assert order.stock_deducted is True
    assert await sp.pending_count(world.session) == 0
    qty = await world.session.scalar(
        select(StockComponent.qty).where(
            StockComponent.kind == "base", StockComponent.model_name == "iPhone 15"
        )
    )
    assert qty == 1


@needs_db
async def test_deduct_one_without_stock_is_409_and_changes_nothing(world) -> None:
    from fastapi import HTTPException

    from app.services import stock_pending as sp

    order = await world.make_order()
    await _stock(world.session, base=1, plate=0)  # пластины нет

    with pytest.raises(HTTPException) as err:
        await sp.deduct_one(world.session, order.id)

    assert err.value.status_code == 409
    assert "оприходуйте" in err.value.detail
    assert order.stock_deducted is False


@needs_db
async def test_deduct_one_rejects_double_and_not_paid(world) -> None:
    from fastapi import HTTPException

    from app.services import stock_pending as sp

    done = await world.make_order(stock_deducted=True)
    unpaid = await world.make_order(status=OrderStatus.PREPAYMENT_ISSUED)
    for order_id, needle in ((done.id, "уже списан"), (unpaid.id, "не оплачен")):
        with pytest.raises(HTTPException) as err:
            await sp.deduct_one(world.session, order_id)
        assert err.value.status_code == 409 and needle in err.value.detail
    with pytest.raises(HTTPException) as err:
        await sp.deduct_one(world.session, 10**9)
    assert err.value.status_code == 404


@needs_db
async def test_deduct_available_processes_oldest_first_and_stops_at_stock(world) -> None:
    from app.services import stock_pending as sp

    first = await world.make_order()
    second = await world.make_order()
    third = await world.make_order()
    await _stock(world.session, base=2, plate=5)  # балванок хватит только на два заказа

    out = await sp.deduct_available(world.session)

    assert out == {"deducted": 2, "remaining": 1}
    flags = (first.stock_deducted, second.stock_deducted, third.stock_deducted)
    assert flags == (True, True, False)


@needs_db
async def test_custom_order_is_not_pending_before_postpayment(world) -> None:
    from app.services import stock_pending as sp

    await world.make_order(branch=CaseBranch.CUSTOM, status=OrderStatus.PREPAYMENT_PAID)
    late = await world.make_order(branch=CaseBranch.CUSTOM, status=OrderStatus.POSTPAYMENT_PAID)

    assert [i["order_id"] for i in await sp.list_pending(world.session)] == [late.id]


# ── API ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def api(world):
    import httpx

    from app.api.v1.admin.deps import get_current_admin
    from app.core.database import get_session
    from app.enums import AdminRole
    from app.main import app

    async def fake_session():
        yield world.session

    role = {"value": AdminRole.ADMIN}
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        id=None, role=role["value"], is_active=True
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.set_role = lambda r: role.update(value=r)
        yield client
    app.dependency_overrides.clear()


@needs_db
async def test_api_list_and_deduct_flow(api, world) -> None:
    order = await world.make_order()

    listed = (await api.get("/api/v1/admin/warehouse/pending-deductions")).json()
    assert [i["order_id"] for i in listed] == [order.id]
    assert listed[0]["can_deduct"] is False and listed[0]["model_name"] == "iPhone 15"

    res = await api.post(f"/api/v1/admin/warehouse/pending-deductions/{order.id}/deduct")
    assert res.status_code == 409  # остатка нет — честный отказ

    await _stock(world.session, base=1, plate=1)
    res = await api.post(f"/api/v1/admin/warehouse/pending-deductions/{order.id}/deduct")
    assert res.status_code == 200, res.text
    assert res.json() == {"deducted": 1, "remaining": 0}
    assert (await api.get("/api/v1/admin/warehouse/pending-deductions")).json() == []


@needs_db
async def test_api_deduct_available(api, world) -> None:
    await world.make_order()
    await world.make_order()
    await _stock(world.session, base=1, plate=1)
    res = await api.post("/api/v1/admin/warehouse/pending-deductions/deduct-available")
    assert res.json() == {"deducted": 1, "remaining": 1}


@needs_db
@pytest.mark.parametrize("role", ["admin", "printer"])
async def test_api_staff_can_use_pending_deductions(api, role) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole(role))
    assert (await api.get("/api/v1/admin/warehouse/pending-deductions")).status_code == 200


@needs_db
async def test_api_designer_cannot_touch_pending_deductions(api) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole.DESIGNER)
    base = "/api/v1/admin/warehouse/pending-deductions"
    assert (await api.get(base)).status_code == 403
    assert (await api.post(f"{base}/deduct-available")).status_code == 403
    assert (await api.post(f"{base}/1/deduct")).status_code == 403


@needs_db
async def test_orders_list_flags_orders_waiting_for_stock(api, world) -> None:
    waiting = await world.make_order()
    fine = await world.make_order(stock_deducted=True)

    rows = (await api.get("/api/v1/admin/orders")).json()
    flags = {r["id"]: r["stock_pending"] for r in rows}

    assert flags[waiting.id] is True
    assert flags[fine.id] is False
