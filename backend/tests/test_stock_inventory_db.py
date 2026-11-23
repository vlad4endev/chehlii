"""Инвентаризация: массовая правка остатков — только расхождения, всё или ничего, права."""

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

A, B = "iPhone 15", "iPhone 16"


@pytest.fixture
async def world():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.core.security import hash_password
    from app.enums import AdminRole
    from app.models.admin_user import AdminUser
    from app.models.catalog import IphoneModel
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
        admin = AdminUser(
            email="inv@x.test", full_name="Ирина", password_hash=hash_password("x" * 8),
            role=AdminRole.ADMIN,
        )
        s.add(admin)
        await s.flush()
        yield SimpleNamespace(session=s, admin=admin)
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _ids(s) -> dict[tuple[str, str, str | None], int]:
    from app.models.warehouse import StockComponent
    from app.services import warehouse as wh

    await wh.ensure_components(s)
    rows = (await s.scalars(select(StockComponent))).all()
    return {(c.kind, c.model_name, c.plate_type): c.id for c in rows}


async def _qty(s, comp_id: int) -> int:
    from app.models.warehouse import StockComponent

    return await s.scalar(select(StockComponent.qty).where(StockComponent.id == comp_id))


async def test_only_differences_are_changed_and_logged(world) -> None:
    from app.models.warehouse import StockMovement
    from app.services import warehouse as wh

    s = world.session
    ids = await _ids(s)
    base_a, plate_a = ids[("base", A, None)], ids[("plate", A, "black")]
    await wh.supply(s, kind="base", model_name=A, qty=10)
    await wh.supply(s, kind="plate", model_name=A, plate_type="black", qty=4)
    before = await s.scalar(select(func.count(StockMovement.id)))

    out = await wh.apply_inventory(
        s, [(base_a, 10), (plate_a, 7)], note="ревизия ноября", admin_user_id=world.admin.id
    )

    assert out == {
        "changed": 1,
        "unchanged": 1,
        "items": [{"component_id": plate_a, "before": 4, "after": 7}],
    }
    assert await _qty(s, base_a) == 10 and await _qty(s, plate_a) == 7
    assert await s.scalar(select(func.count(StockMovement.id))) == before + 1  # только расхождение
    mov = await s.scalar(select(StockMovement).order_by(StockMovement.id.desc()).limit(1))
    assert mov.reason == "adjust" and mov.delta == 3 and mov.admin_user_id == world.admin.id
    assert mov.comment == "Инвентаризация: ревизия ноября"


async def test_zero_and_group_positions_are_supported(world) -> None:
    from app.services import stock_groups as sg
    from app.services import warehouse as wh

    s = world.session
    await _ids(s)
    await sg.save_group(s, name="Пара", scope="both", models=[A, B])
    ids = await _ids(s)
    group_base = ids[("base", "Пара", None)]
    await wh.supply(s, kind="base", model_name=B, qty=9)  # общий остаток группы

    await wh.apply_inventory(s, [(group_base, 0)])

    assert await _qty(s, group_base) == 0


async def test_invalid_input_changes_nothing(world) -> None:
    from app.services import warehouse as wh

    s = world.session
    ids = await _ids(s)
    base_a = ids[("base", A, None)]
    await wh.supply(s, kind="base", model_name=A, qty=5)

    cases = [
        ([], 400, "пуст"),
        ([(base_a, 1), (base_a, 2)], 400, "несколько раз"),
        ([(base_a, 1), (10**9, 3)], 404, "не найдены"),
        ([(base_a, -1)], 400, "отрицательным"),
        ([(base_a, wh.MAX_QTY + 1)], 400, "большое"),
    ]
    for counts, code, needle in cases:
        with pytest.raises(HTTPException) as err:
            await wh.apply_inventory(s, counts)
        assert err.value.status_code == code and needle in err.value.detail
    assert await _qty(s, base_a) == 5  # ни один из неверных запросов ничего не затронул


async def test_too_many_items_is_rejected(world) -> None:
    from app.services import warehouse as wh

    with pytest.raises(HTTPException) as err:
        await wh.apply_inventory(
            world.session, [(i, 1) for i in range(1, wh.MAX_INVENTORY_ITEMS + 2)]
        )
    assert err.value.status_code == 400


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
        id=world.admin.id, role=role["value"], is_active=True
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.set_role = lambda r: role.update(value=r)
        yield client
    app.dependency_overrides.clear()


async def test_api_inventory_and_journal_author(api, world) -> None:
    ids = await _ids(world.session)
    comp = ids[("base", A, None)]

    res = await api.post(
        "/api/v1/admin/warehouse/inventory",
        json={"items": [{"component_id": comp, "qty": 12}], "comment": "сверка"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == 1

    items = (await api.get("/api/v1/admin/warehouse/movements")).json()["items"]
    assert items[0]["delta"] == 12 and items[0]["admin_name"] == "Ирина"
    assert items[0]["comment"] == "Инвентаризация: сверка"


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"items": [{"component_id": 1, "qty": -1}]},
        {"items": [{"component_id": 1, "qty": 3_000_000_000}]},
        {"items": [{"component_id": 0, "qty": 1}]},
        {"items": [{"component_id": 1, "qty": 1}], "comment": "x" * 201},
    ],
)
async def test_api_validation(api, body) -> None:
    assert (await api.post("/api/v1/admin/warehouse/inventory", json=body)).status_code == 422


@pytest.mark.parametrize("role", ["printer", "designer"])
async def test_api_inventory_is_admin_only(api, role) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole(role))
    res = await api.post(
        "/api/v1/admin/warehouse/inventory", json={"items": [{"component_id": 1, "qty": 1}]}
    )
    assert res.status_code == 403
