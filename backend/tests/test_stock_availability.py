"""«Можно собрать» и «заканчивается»: правила и расчёт на реальной PostgreSQL."""

import os
from types import SimpleNamespace

import pytest

from app.services.stock_availability import DEFAULT_LOW_STOCK, classify

A, B = "iPhone 15", "iPhone 16"


@pytest.mark.parametrize(
    ("sellable", "used", "expected"),
    [
        ({"black": 10, "silver": 0}, ["black"], (False, False)),  # серебро не продаётся — не в счёт
        ({"black": 3, "silver": 0}, ["black"], (True, False)),  # ровно порог — мало
        ({"black": 4, "silver": 0}, ["black"], (False, False)),
        ({"black": 0, "silver": 9}, ["black"], (False, True)),  # нет нужной пластины
        ({"black": 0, "silver": 0}, ["black", "silver"], (False, True)),
        # хватает чёрных, мало серебра
        ({"black": 9, "silver": 2}, ["black", "silver"], (True, False)),
        ({"black": 0, "silver": 0}, [], (False, False)),  # модель нигде не продаётся
    ],
)
def test_classify(sellable, used, expected) -> None:
    assert classify(sellable, used, threshold=3) == expected


def test_default_threshold_is_positive() -> None:
    assert DEFAULT_LOW_STOCK > 0


DB_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")


@pytest.fixture
async def world():
    from sqlalchemy import delete, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.models import CaseType, Order
    from app.models.catalog import CaseTypeModel, IphoneModel
    from app.models.settings import IntegrationSetting
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
        await s.execute(delete(CaseTypeModel))
        await s.execute(delete(CaseType))
        await s.execute(
            delete(IntegrationSetting).where(IntegrationSetting.key == "warehouse.low_stock")
        )

        async def sells(model: str, plate: str = "black", active: bool = True) -> None:
            case = CaseType(
                name=f"T-{model}-{plate}", plate_type=plate, cost=1, margin=1, is_active=active
            )
            s.add(case)
            await s.flush()
            s.add(CaseTypeModel(case_type_id=case.id, model_name=model, is_available=True))
            await s.flush()

        async def threshold(value: str) -> None:
            s.add(IntegrationSetting(key="warehouse.low_stock", value=value))
            await s.flush()

        yield SimpleNamespace(session=s, sells=sells, threshold=threshold)
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def _put(s, kind, model, qty, plate=None):
    from app.services import warehouse as wh

    await wh.supply(s, kind=kind, model_name=model, qty=qty, plate_type=plate)


def _row(data, model):
    return next(m for m in data["models"] if m["model_name"] == model)


@needs_db
async def test_sellable_is_min_of_base_and_plate(world) -> None:
    from app.services import stock_availability as sa

    await world.sells(A, "black")
    await _put(world.session, "base", A, 7)
    await _put(world.session, "plate", A, 4, "black")
    await _put(world.session, "plate", A, 9, "silver")

    row = _row(await sa.availability(world.session), A)

    assert (row["black"], row["silver"]) == (4, 7)  # min(7,4) и min(7,9)
    assert row["used_plates"] == ["black"]
    assert (row["low"], row["out"]) == (False, False)


@needs_db
async def test_low_and_out_follow_threshold_and_only_sold_plates(world) -> None:
    from app.services import stock_availability as sa

    await world.sells(A, "black")
    await world.sells(B, "silver")
    await _put(world.session, "base", A, 10)
    await _put(world.session, "plate", A, 3, "black")  # = порогу 3 → мало
    await _put(world.session, "base", B, 10)           # серебра нет → закончилось

    data = await sa.availability(world.session)

    assert (_row(data, A)["low"], _row(data, A)["out"]) == (True, False)
    assert (_row(data, B)["low"], _row(data, B)["out"]) == (False, True)
    assert data["low"] == 1 and data["out"] == 1
    # остальные модели нигде не продаются — не считаются «закончившимися»
    assert _row(data, "iPhone 11")["out"] is False


@needs_db
async def test_inactive_case_types_do_not_count(world) -> None:
    from app.services import stock_availability as sa

    await world.sells(A, "black", active=False)
    assert _row(await sa.availability(world.session), A)["out"] is False


@needs_db
async def test_threshold_setting_and_garbage_fallback(world) -> None:
    from app.services import stock_availability as sa

    await world.sells(A, "black")
    await _put(world.session, "base", A, 10)
    await _put(world.session, "plate", A, 5, "black")

    assert _row(await sa.availability(world.session), A)["low"] is False  # порог 3, осталось 5
    await world.threshold("5")
    data = await sa.availability(world.session)
    assert data["threshold"] == 5 and _row(data, A)["low"] is True

    for garbage in ("много", "-4", "10000000", ""):
        from app.models.settings import IntegrationSetting

        row = await world.session.get(IntegrationSetting, "warehouse.low_stock")
        row.value = garbage
        await world.session.flush()
        assert (await sa.availability(world.session))["threshold"] == DEFAULT_LOW_STOCK


@needs_db
async def test_group_stock_counts_for_every_member(world) -> None:
    from app.services import stock_availability as sa
    from app.services import stock_groups as sg

    await world.sells(A, "black")
    await world.sells(B, "black")
    await _put(world.session, "base", A, 6)
    await _put(world.session, "plate", A, 6, "black")
    await sg.save_group(world.session, name="Общая", scope="both", models=[A, B])

    data = await sa.availability(world.session)

    assert _row(data, A)["black"] == _row(data, B)["black"] == 6
    assert _row(data, A)["group_name"] == "Общая"


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
@pytest.mark.parametrize(("role", "code"), [("admin", 200), ("printer", 200), ("designer", 403)])
async def test_api_availability_roles(api, role, code) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole(role))
    res = await api.get("/api/v1/admin/warehouse/availability")
    assert res.status_code == code
    if code == 200:
        assert {"threshold", "models", "low", "out"} <= set(res.json())


@needs_db
async def test_dashboard_attention_shows_stock_only_to_admin(api, world) -> None:
    from app.enums import AdminRole

    await world.sells(A, "black")  # продаётся, остатка нет → «закончилось»

    def keys(res) -> set[str]:
        return {a["key"] for a in res.json()["attention"]}

    admin = await api.get("/api/v1/admin/stats")
    assert admin.status_code == 200, admin.text
    assert "stock_low" in keys(admin)
    item = next(a for a in admin.json()["attention"] if a["key"] == "stock_low")
    assert item["href"] == "/warehouse?low=1" and item["count"] == 1

    api.set_role(AdminRole.DESIGNER)
    designer = await api.get("/api/v1/admin/stats")
    assert designer.status_code == 200
    assert not keys(designer) & {"stock_low", "stock_pending"}
