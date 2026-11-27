"""Управление моделями iPhone из админки: создание, переименование, удаление.

Запуск: TEST_DATABASE_URL=postgresql+asyncpg://… pytest tests/test_iphone_model_manage_db.py
(каждый тест идёт в транзакции и откатывается).
"""

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.enums import Channel
from app.models import CaseType, Client, Order
from app.models.catalog import CaseTypeModel
from app.models.warehouse import StockComponent, StockMovement
from app.services import iphone_models as im
from app.services import stock_groups as sg
from app.services import warehouse as wh

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

OLD = "iPhone 99 Test"
NEW = "iPhone 99|100"


@pytest.fixture
async def session():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield s
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _names(s: AsyncSession) -> list[str]:
    return await im.list_model_names(s)


async def _make_model(s: AsyncSession, name: str = OLD) -> CaseType:
    """Новая модель с позициями склада и строкой в типе чехла."""
    await im.add_model(s, name, enable_on_all=True)
    case = CaseType(name="Тип для теста", plate_type="black", cost=1, margin=1)
    s.add(case)
    await s.flush()
    s.add(CaseTypeModel(case_type_id=case.id, model_name=name))
    await s.flush()
    return case


async def _order(s: AsyncSession, case: CaseType, model: str) -> Order:
    client = Client(channel=Channel.TG, channel_user_id=f"u-{model}")
    s.add(client)
    await s.flush()
    order = Order(client_id=client.id, case_type_id=case.id, model_name=model)
    s.add(order)
    await s.flush()
    return order


async def test_rename_updates_catalog_types_stock_and_orders(session) -> None:
    case = await _make_model(session)
    await wh.supply(session, kind="base", model_name=OLD, qty=3)
    order = await _order(session, case, OLD)

    assert await im.rename_model(session, OLD, "  iPhone 99|100 ") == NEW

    names = await _names(session)
    assert NEW in names and OLD not in names
    assert (
        await session.scalar(
            select(func.count()).select_from(CaseTypeModel).where(CaseTypeModel.model_name == OLD)
        )
        == 0
    )
    assert (
        await session.scalar(
            select(func.count()).select_from(CaseTypeModel).where(CaseTypeModel.model_name == NEW)
        )
        >= 1
    )
    comps = (
        await session.scalars(select(StockComponent).where(StockComponent.model_name == NEW))
    ).all()
    assert len(comps) == 3 and sum(c.qty for c in comps) == 3  # остаток и позиции на месте
    assert (
        await session.scalar(select(StockComponent.id).where(StockComponent.model_name == OLD))
        is None
    )
    await session.refresh(order)
    assert order.model_name == NEW  # старые заказы не теряют модель


async def test_rename_keeps_stock_history(session) -> None:
    await _make_model(session)
    await wh.supply(session, kind="base", model_name=OLD, qty=2)
    before = await session.scalar(select(func.count()).select_from(StockMovement))
    await im.rename_model(session, OLD, NEW)
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == before


async def test_rename_to_same_name_is_noop(session) -> None:
    await _make_model(session)
    assert await im.rename_model(session, OLD, OLD) == OLD
    assert OLD in await _names(session)


async def test_rename_rejects_duplicates_empty_and_unknown(session) -> None:
    await _make_model(session)
    await im.add_model(session, NEW)
    with pytest.raises(HTTPException) as dup:
        await im.rename_model(session, OLD, NEW)
    assert dup.value.status_code == 409
    with pytest.raises(HTTPException) as empty:
        await im.rename_model(session, OLD, "   ")
    assert empty.value.status_code == 400
    with pytest.raises(HTTPException) as unknown:
        await im.rename_model(session, "Нет такой", "X")
    assert unknown.value.status_code == 404


async def test_rename_rejects_name_of_existing_group(session) -> None:
    await _make_model(session)
    a, b = (await _names(session))[:2]
    await sg.save_group(session, name="Группа X", scope="both", models=[a, b])
    with pytest.raises(HTTPException) as exc:
        await im.rename_model(session, OLD, "Группа X")
    assert exc.value.status_code == 409 and "группой" in exc.value.detail


async def test_delete_unused_model_removes_everything(session) -> None:
    await _make_model(session)
    await wh.supply(session, kind="base", model_name=OLD, qty=2)
    await wh.write_off_defect(session, kind="base", model_name=OLD, qty=2, reason="defect_print")
    await im.delete_model(session, OLD)

    assert OLD not in await _names(session)
    for table, col in (
        (CaseTypeModel, CaseTypeModel.model_name),
        (StockComponent, StockComponent.model_name),
    ):
        assert await session.scalar(select(func.count()).select_from(table).where(col == OLD)) == 0


async def test_delete_blocked_by_orders(session) -> None:
    case = await _make_model(session)
    await _order(session, case, OLD)
    with pytest.raises(HTTPException) as exc:
        await im.delete_model(session, OLD)
    assert exc.value.status_code == 409 and "заказы" in exc.value.detail
    assert OLD in await _names(session)


async def test_delete_blocked_by_stock_and_group(session) -> None:
    await _make_model(session)
    await wh.supply(session, kind="base", model_name=OLD, qty=4)
    with pytest.raises(HTTPException) as stock:
        await im.delete_model(session, OLD)
    assert stock.value.status_code == 409 and "4 шт" in stock.value.detail

    await wh.write_off_defect(session, kind="base", model_name=OLD, qty=4, reason="defect_print")
    other = (await _names(session))[0]
    await sg.save_group(session, name="Группа Y", scope="both", models=[OLD, other])
    with pytest.raises(HTTPException) as grp:
        await im.delete_model(session, OLD)
    assert grp.value.status_code == 409 and "Группа Y" in grp.value.detail


async def test_details_report_usage_and_blockers(session) -> None:
    case = await _make_model(session)
    await wh.supply(session, kind="base", model_name=OLD, qty=2)
    await _order(session, case, OLD)
    row = next(d for d in await im.model_details(session) if d["name"] == OLD)
    assert row["orders"] == 1 and row["stock_qty"] == 2 and row["can_delete"] is False
    assert "заказы" in row["delete_blocker"]
    fresh = await im.add_model(session, "iPhone 98 Fresh")
    row = next(d for d in await im.model_details(session) if d["name"] == fresh)
    assert row["can_delete"] is True and row["delete_blocker"] is None


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


BASE = "/api/v1/admin/case-types/iphone-models"


async def test_api_create_rename_delete_with_pipe_and_slash_in_name(api) -> None:
    res = await api.post(BASE, json={"name": "iPhone 17|18"})
    assert res.status_code == 201 and "iPhone 17|18" in res.json()

    res = await api.patch(f"{BASE}/iPhone 17%7C18", json={"name": "iPhone 17/18"})
    assert res.status_code == 200, res.text
    assert "iPhone 17/18" in res.json() and "iPhone 17|18" not in res.json()

    res = await api.delete(f"{BASE}/iPhone 17/18")
    assert res.status_code == 200, res.text
    assert "iPhone 17/18" not in res.json()


async def test_api_conflicts_and_details(api, session) -> None:
    await im.add_model(session, OLD)
    res = await api.get(f"{BASE}/details")
    assert res.status_code == 200
    assert any(d["name"] == OLD and d["can_delete"] for d in res.json())

    other = (await _names(session))[0]
    res = await api.patch(f"{BASE}/{OLD}", json={"name": other})
    assert res.status_code == 409
    assert (await api.delete(f"{BASE}/Нет такой")).status_code == 404


@pytest.mark.parametrize("role", ["designer", "printer"])
async def test_api_model_management_is_admin_only(api, role) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole(role))
    assert (await api.patch(f"{BASE}/{OLD}", json={"name": "X"})).status_code == 403
    assert (await api.delete(f"{BASE}/{OLD}")).status_code == 403
    assert (await api.get(f"{BASE}/details")).status_code == 403


async def test_api_accepts_fully_encoded_names_like_the_admin_ui_sends(api) -> None:
    """Админка кодирует имя целиком (encodeURIComponent): «|» → %7C, «/» → %2F, пробел → %20."""
    assert (await api.post(BASE, json={"name": "iPhone 20|21"})).status_code == 201
    res = await api.patch(f"{BASE}/iPhone%2020%7C21", json={"name": "iPhone 20/21"})
    assert res.status_code == 200, res.text
    res = await api.delete(f"{BASE}/iPhone%2020%2F21")
    assert res.status_code == 200, res.text
    assert "iPhone 20/21" not in res.json()
