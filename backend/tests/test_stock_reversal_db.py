"""Отмена движения (сторно): правила, одновременная отмена, права, журнал (реальная PostgreSQL)."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

M = "iPhone 15"


async def _clean(s) -> None:
    from app.models import CaseType, Client, Order
    from app.models.catalog import CaseTypeModel, IphoneModel
    from app.models.warehouse import StockComponent, StockGroup, StockMovement

    await s.execute(update(StockMovement).values(reverses_id=None))
    await s.execute(delete(StockMovement))
    await s.execute(delete(StockComponent))
    await s.execute(update(IphoneModel).values(stock_group_id=None))
    await s.execute(delete(StockGroup))
    await s.execute(delete(Order).where(Order.model_name == M))
    await s.execute(delete(Client).where(Client.channel_user_id.like("rev-%")))
    await s.execute(delete(CaseTypeModel).where(CaseTypeModel.model_name == M))
    await s.execute(delete(CaseType).where(CaseType.name == "Сторно"))


@pytest.fixture
async def session():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await _clean(s)
        yield s
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _qty(s, kind="base", plate=None) -> int:
    from app.models.warehouse import StockComponent

    stmt = select(StockComponent.qty).where(
        StockComponent.kind == kind, StockComponent.model_name == M
    )
    plate_filter = (
        StockComponent.plate_type.is_(None) if plate is None else StockComponent.plate_type == plate
    )
    return await s.scalar(stmt.where(plate_filter)) or 0


async def test_reversing_supply_returns_stock_and_keeps_history(session) -> None:
    from app.services import warehouse as wh

    sup = await wh.supply(session, kind="base", model_name=M, qty=5, comment="ошибся")

    undo = await wh.reverse_movement(session, sup.id, comment="не та модель")

    assert await _qty(session) == 0
    assert undo.delta == -5 and undo.reverses_id == sup.id and undo.reason == "adjust"
    assert "Отмена записи" in undo.comment and "не та модель" in undo.comment
    rows, total = await wh.list_movements(session)
    assert total == 2  # ничего не удалено: оригинал + отмена
    by = {r["id"]: r for r in rows}
    assert by[sup.id]["reversed_by_id"] == undo.id
    assert by[undo.id]["reverses_id"] == sup.id and by[undo.id]["reversed_by_id"] is None


@pytest.mark.parametrize("reason", ["defect_print", "defect_glue", "defect_supplier"])
async def test_reversing_defect_restores_the_item(session, reason) -> None:
    from app.services import warehouse as wh

    await wh.supply(session, kind="base", model_name=M, qty=10)
    defect = await wh.write_off_defect(session, kind="base", model_name=M, qty=3, reason=reason)
    assert await _qty(session) == 7

    await wh.reverse_movement(session, defect.id)

    assert await _qty(session) == 10


async def test_reversing_an_adjustment_goes_back(session) -> None:
    from app.models.warehouse import StockComponent
    from app.services import warehouse as wh

    await wh.supply(session, kind="base", model_name=M, qty=4)
    comp = await session.scalar(select(StockComponent).where(StockComponent.model_name == M))
    adj = await wh.set_qty(session, comp.id, 9, comment="пересчёт")
    assert await _qty(session) == 9

    await wh.reverse_movement(session, adj.id)

    assert await _qty(session) == 4


async def test_cannot_reverse_twice_or_reverse_a_reversal(session) -> None:
    from app.services import warehouse as wh

    sup = await wh.supply(session, kind="base", model_name=M, qty=2)
    undo = await wh.reverse_movement(session, sup.id)

    with pytest.raises(HTTPException) as err:
        await wh.reverse_movement(session, sup.id)
    assert err.value.status_code == 409 and "уже отменена" in err.value.detail

    with pytest.raises(HTTPException) as err:
        await wh.reverse_movement(session, undo.id)
    assert err.value.status_code == 400 and "уже отмена" in err.value.detail
    assert await _qty(session) == 0  # повторные попытки ничего не изменили


async def test_cannot_reverse_order_deduction_or_unknown(session) -> None:
    from app.models import CaseType, Client, Order
    from app.models.catalog import CaseTypeModel
    from app.services import warehouse as wh

    await wh.supply(session, kind="base", model_name=M, qty=1)
    await wh.supply(session, kind="plate", model_name=M, plate_type="black", qty=1)
    case = CaseType(name="Сторно", plate_type="black", cost=1, margin=1)
    client = Client(channel="tg", channel_user_id="rev-1")
    session.add_all([case, client])
    await session.flush()
    session.add(CaseTypeModel(case_type_id=case.id, model_name=M))
    order = Order(client_id=client.id, case_type_id=case.id, model_name=M, status="prepayment_paid")
    session.add(order)
    await session.flush()
    await wh.deduct_for_order(session, order)
    rows, _ = await wh.list_movements(session)
    order_row = next(r for r in rows if r["reason"] == "order")

    with pytest.raises(HTTPException) as err:
        await wh.reverse_movement(session, order_row["id"])
    assert err.value.status_code == 400 and "отменой заказа" in err.value.detail

    with pytest.raises(HTTPException) as err:
        await wh.reverse_movement(session, 10**9)
    assert err.value.status_code == 404


async def test_cannot_reverse_supply_that_was_already_used(session) -> None:
    from app.services import warehouse as wh

    sup = await wh.supply(session, kind="base", model_name=M, qty=3)
    await wh.write_off_defect(session, kind="base", model_name=M, qty=2, reason="defect_print")

    with pytest.raises(HTTPException) as err:
        await wh.reverse_movement(session, sup.id)

    assert err.value.status_code == 409
    assert "Нельзя отменить" in err.value.detail and "уже израсходован" in err.value.detail
    assert "base" not in err.value.detail
    assert await _qty(session) == 1  # осталось как было
    undone = await session.scalar(
        select(wh.StockMovement.id).where(wh.StockMovement.reverses_id == sup.id)
    )
    assert undone is None


async def test_reversing_a_group_movement_restores_group_stock(session) -> None:
    from app.services import stock_groups as sg
    from app.services import warehouse as wh

    await sg.save_group(session, name="Пара", scope="both", models=[M, "iPhone 16"])
    sup = await wh.supply(session, kind="base", model_name="iPhone 16", qty=6)  # уходит в группу

    await wh.reverse_movement(session, sup.id)

    from app.models.warehouse import StockComponent

    qty = await session.scalar(
        select(StockComponent.qty).where(
            StockComponent.model_name == "Пара", StockComponent.kind == "base"
        )
    )
    assert qty == 0


# ── Одновременная отмена: настоящие сессии и коммиты ───────────────────────


async def test_two_simultaneous_reversals_apply_once() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.warehouse import StockMovement
    from app.services import warehouse as wh

    engine = create_async_engine(DB_URL, pool_size=10)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await _clean(s)
        await s.commit()
    try:
        async with maker() as s:
            sup = await wh.supply(s, kind="base", model_name=M, qty=5)
            await s.commit()
            movement_id = sup.id

        async def one() -> str:
            async with maker() as s:
                try:
                    await wh.reverse_movement(s, movement_id)
                    await s.commit()
                    return "ok"
                except HTTPException as exc:
                    await s.rollback()
                    return str(exc.status_code)

        results = await asyncio.gather(*[one() for _ in range(5)])

        assert results.count("ok") == 1
        assert results.count("409") == 4
        async with maker() as s:
            assert await _qty(s) == 0  # отменили ровно один раз
            n = await s.scalar(
                select(wh.func.count(StockMovement.id)).where(
                    StockMovement.reverses_id == movement_id
                )
            )
            assert n == 1
    finally:
        async with maker() as s:
            await _clean(s)
            await s.commit()
        await engine.dispose()


# ── API ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def api(session):
    import httpx

    from app.api.v1.admin.deps import get_current_admin
    from app.core.database import get_session
    from app.enums import AdminRole
    from app.main import app

    async def fake_session():
        yield session

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


async def test_api_reverse_flow_and_journal_flags(api) -> None:
    sup = (
        await api.post(
            "/api/v1/admin/warehouse/supply", json={"kind": "base", "model_name": M, "qty": 4}
        )
    ).json()

    res = await api.post(
        f"/api/v1/admin/warehouse/movements/{sup['id']}/reverse", json={"comment": "ошибка ввода"}
    )
    assert res.status_code == 201, res.text
    undo = res.json()
    assert undo["delta"] == -4 and undo["reverses_id"] == sup["id"]

    items = (await api.get("/api/v1/admin/warehouse/movements")).json()["items"]
    flags = {i["id"]: (i["reverses_id"], i["reversed_by_id"]) for i in items}
    assert flags[sup["id"]] == (None, undo["id"])
    assert flags[undo["id"]] == (sup["id"], None)

    again = await api.post(f"/api/v1/admin/warehouse/movements/{sup['id']}/reverse", json={})
    assert again.status_code == 409


@pytest.mark.parametrize("role", ["printer", "designer"])
async def test_api_only_admin_can_reverse(api, role) -> None:
    from app.enums import AdminRole

    sup = (
        await api.post(
            "/api/v1/admin/warehouse/supply", json={"kind": "base", "model_name": M, "qty": 1}
        )
    ).json()
    api.set_role(AdminRole(role))
    res = await api.post(f"/api/v1/admin/warehouse/movements/{sup['id']}/reverse", json={})
    assert res.status_code == 403
