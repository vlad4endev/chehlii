"""Журнал движений склада: автор, фильтры, постраничность, группы, Excel (реальная PostgreSQL)."""

import io
import os
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, update

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

A, B = "iPhone 15 Pro Max", "iPhone 16 Pro Max"


@pytest.fixture
async def world():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.core.security import hash_password
    from app.enums import AdminRole
    from app.models import CaseType, Client, Order
    from app.models.admin_user import AdminUser
    from app.models.catalog import IphoneModel
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
        named = AdminUser(
            email="anna@x.test", full_name="Анна", password_hash=hash_password("x" * 8),
            role=AdminRole.PRINTER,
        )
        unnamed = AdminUser(
            email="boris@x.test", full_name=None, password_hash=hash_password("x" * 8),
            role=AdminRole.ADMIN,
        )
        s.add_all([named, unnamed])
        case = CaseType(name="Журнал", plate_type="black", cost=1, margin=1)
        client = Client(channel="tg", channel_user_id="mov-1")
        s.add_all([case, client])
        await s.flush()
        yield SimpleNamespace(
            session=s, named=named, unnamed=unnamed, case=case, client=client, Order=Order
        )
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _fill(w) -> None:
    from app.services import warehouse as wh

    s = w.session
    await wh.supply(s, kind="base", model_name=A, qty=10, admin_user_id=w.named.id)
    await wh.supply(s, kind="plate", model_name=A, plate_type="black", qty=10, comment="партия 7")
    await wh.write_off_defect(
        s, kind="base", model_name=A, qty=2, reason="defect_print", admin_user_id=w.unnamed.id
    )
    await wh.supply(s, kind="base", model_name=B, qty=5, admin_user_id=w.named.id)


async def test_author_is_name_then_email_then_empty_for_system(world) -> None:
    from app.services import warehouse as wh

    await _fill(world)
    order = world.Order(
        client_id=world.client.id,
        case_type_id=world.case.id,
        model_name=A,
        status="prepayment_paid",
    )
    world.session.add(order)
    await world.session.flush()
    await wh.deduct_for_order(world.session, order)

    rows, total = await wh.list_movements(world.session)
    by = {(r["model_name"], r["reason"], r["kind"]): r for r in rows}

    assert by[(A, "supply", "base")]["admin_name"] == "Анна"
    assert by[(A, "defect_print", "base")]["admin_name"] == "boris@x.test"  # имени нет — почта
    assert by[(A, "supply", "plate")]["admin_name"] is None  # без автора
    order_rows = [r for r in rows if r["reason"] == "order"]
    assert len(order_rows) == 2 and all(r["order_id"] == order.id for r in order_rows)
    assert all(r["admin_name"] is None for r in order_rows)
    assert total == len(rows) == 6


async def test_filters_combine_and_total_matches(world) -> None:
    from app.services import warehouse as wh
    from app.services.warehouse import MovementFilter as F

    await _fill(world)
    s = world.session

    async def count(**kw) -> int:
        rows, total = await wh.list_movements(s, flt=F(**kw))
        assert total == len(rows)
        return total

    assert await count(model="pro max") == 4  # без учёта регистра, обе модели
    assert await count(model="15") == 3
    assert await count(kind="plate") == 1
    assert await count(reason="supply") == 3
    assert await count(reason="defect_print") == 1
    assert await count(model="16", reason="supply", kind="base") == 1
    assert await count(model="нет такой") == 0


async def test_date_range_is_inclusive_and_pagination_keeps_total(world) -> None:
    from app.models.warehouse import StockMovement
    from app.services import warehouse as wh
    from app.services.warehouse import MovementFilter as F

    await _fill(world)
    s = world.session
    old = datetime.now(UTC) - timedelta(days=10)
    await s.execute(
        update(StockMovement).where(StockMovement.comment == "партия 7").values(created_at=old)
    )

    day = old.date()
    rows, total = await wh.list_movements(s, flt=F(date_from=day, date_to=day))
    assert [r["comment"] for r in rows] == ["партия 7"]  # весь день включительно

    recent, total_recent = await wh.list_movements(s, flt=F(date_from=date.today()))
    assert total_recent == 3 and "партия 7" not in [r["comment"] for r in recent]

    page1, total1 = await wh.list_movements(s, limit=2, offset=0)
    page2, total2 = await wh.list_movements(s, limit=2, offset=2)
    page3, _ = await wh.list_movements(s, limit=2, offset=4)
    assert total1 == total2 == 4
    ids = [r["id"] for r in page1 + page2 + page3]
    assert len(ids) == len(set(ids)) == 4  # без повторов и пропусков


async def test_group_movements_found_by_member_model(world) -> None:
    from app.services import stock_groups as sg
    from app.services import warehouse as wh
    from app.services.warehouse import MovementFilter as F

    await _fill(world)
    await sg.save_group(world.session, name="Универсал PM", scope="both", models=[A, B])
    await wh.supply(world.session, kind="base", model_name=B, qty=1)  # теперь уходит в группу

    rows, _ = await wh.list_movements(world.session, flt=F(model="16 Pro"))

    assert rows and any(r["model_name"] == "Универсал PM" for r in rows)


@pytest.mark.parametrize("needle", ["%", "_", "\\"])
async def test_search_wildcards_are_literal(world, needle) -> None:
    from app.services import warehouse as wh
    from app.services.warehouse import MovementFilter as F

    await _fill(world)
    rows, total = await wh.list_movements(world.session, flt=F(model=needle))
    assert total == 0 and rows == []  # «%» не значит «всё»


@pytest.fixture
async def api(world):
    import httpx

    from app.api.v1.admin.deps import get_current_admin
    from app.core.database import get_session
    from app.enums import AdminRole
    from app.main import app

    async def fake_session():
        yield world.session

    role = {"value": AdminRole.PRINTER}
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        id=None, role=role["value"], is_active=True
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.set_role = lambda r: role.update(value=r)
        yield client
    app.dependency_overrides.clear()


async def test_api_filters_and_validation(api, world) -> None:
    await _fill(world)
    base = "/api/v1/admin/warehouse/movements"

    res = await api.get(base, params={"model": "16", "reason": "supply"})
    body = res.json()
    assert res.status_code == 200 and body["total"] == 1
    assert body["items"][0]["admin_name"] == "Анна"

    assert (await api.get(base, params={"reason": "nonsense"})).status_code == 422
    assert (await api.get(base, params={"kind": "nonsense"})).status_code == 422
    assert (await api.get(base, params={"date_from": "вчера"})).status_code == 422


async def test_api_export_matches_filters_and_roles(api, world) -> None:
    from openpyxl import load_workbook

    from app.enums import AdminRole

    await _fill(world)
    url = "/api/v1/admin/warehouse/movements/export.xlsx"

    res = await api.get(url, params={"reason": "supply"})  # печатник тоже может
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]
    ws = load_workbook(io.BytesIO(res.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][0] == "Когда (UTC)" and rows[0][6] == "Кто"
    assert len(rows) - 1 == 3  # только поставки
    assert {r[5] for r in rows[1:]} == {"Поставка"}

    api.set_role(AdminRole.DESIGNER)
    assert (await api.get(url)).status_code == 403
    assert (await api.get("/api/v1/admin/warehouse/movements")).status_code == 403
