"""Группы «универсальных» моделей на реальной PostgreSQL.

Запуск: TEST_DATABASE_URL=postgresql+asyncpg://… pytest tests/test_stock_groups_db.py
(база с применёнными миграциями; каждый тест идёт в транзакции и откатывается).
Без переменной тесты пропускаются — в CI нет PostgreSQL.
"""

import os

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.enums import Channel, StockKind, StockMovementReason
from app.models import CaseType, Client, Order
from app.models.catalog import CaseTypeModel, IphoneModel
from app.models.warehouse import StockComponent, StockGroup, StockMovement
from app.services import stock_groups as sg
from app.services import warehouse as wh

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

A, B, C = "iPhone 15 Pro Max", "iPhone 16 Pro Max", "iPhone 17 Pro Max"


@pytest.fixture
async def session():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        # Чистый склад: тесты считают остатки в абсолютных числах. Всё внутри транзакции,
        # которая откатывается, — реальные данные базы не страдают.
        await s.execute(update(IphoneModel).values(stock_group_id=None))
        await s.execute(delete(StockGroup))
        await s.execute(delete(StockMovement))
        await s.execute(delete(StockComponent))
        yield s
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def stock(session: AsyncSession, kind: str, key: str, plate: str | None = None) -> int | None:
    stmt = select(StockComponent.qty).where(
        StockComponent.kind == kind, StockComponent.model_name == key
    )
    stmt = stmt.where(
        StockComponent.plate_type.is_(None) if plate is None else StockComponent.plate_type == plate
    )
    return await session.scalar(stmt)


async def supply(session, kind, model, qty, plate=None):
    await wh.supply(session, kind=kind, model_name=model, qty=qty, plate_type=plate)


async def movements_total(session) -> int:
    return await session.scalar(select(func.count(StockMovement.id))) or 0


async def test_merge_sums_stock_and_keeps_history(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 3)
    await supply(session, "base", B, 4)
    await supply(session, "plate", A, 2, "black")
    await supply(session, "plate", B, 5, "black")
    before = await movements_total(session)

    out = await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])

    assert out["models"] == [A, B]
    assert await stock(session, "base", "Pro Max") == 7
    assert await stock(session, "plate", "Pro Max", "black") == 7
    # собственные позиции моделей исчезли — остаток один, общий
    assert await stock(session, "base", A) is None
    assert await stock(session, "base", B) is None
    # история не потеряна: все прежние движения на месте + записи об объединении
    assert await movements_total(session) >= before
    reasons = (await session.scalars(select(StockMovement.reason).where(
        StockMovement.comment.like("Объединение:%")))).all()
    assert reasons and set(reasons) == {StockMovementReason.ADJUST}


async def test_shared_stock_is_visible_and_spent_by_any_member(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 2)
    await supply(session, "plate", A, 2, "black")
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])

    # приход «на B» виден для A: остаток общий
    await supply(session, "base", B, 1)
    assert await wh.available_for_sale(session, model_name=A, plate_type="black") == 2
    assert await wh.available_for_sale(session, model_name=B, plate_type="black") == 2

    # брак «на A» уменьшает общий остаток, а значит и доступное для B
    await wh.write_off_defect(
        session, kind="plate", model_name=A, qty=1, reason="defect_print", plate_type="black"
    )
    assert await wh.available_for_sale(session, model_name=B, plate_type="black") == 1


async def test_order_for_one_model_draws_from_group_and_syncs_all_members(session) -> None:
    await wh.ensure_components(session)
    case = CaseType(name="Тест", plate_type="black", cost=1, margin=1)
    session.add(case)
    await session.flush()
    for m in (A, B):
        session.add(CaseTypeModel(case_type_id=case.id, model_name=m))
    client = Client(channel=Channel.TG, channel_user_id="u-groups")
    session.add(client)
    await session.flush()
    order = Order(client_id=client.id, case_type_id=case.id, model_name=A)
    session.add(order)
    await session.flush()
    await supply(session, "base", A, 5)
    await supply(session, "plate", A, 5, "black")
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])

    await wh.deduct_for_order(session, order)

    assert await stock(session, "base", "Pro Max") == 4
    assert await stock(session, "plate", "Pro Max", "black") == 4
    stocks = (await session.scalars(select(CaseTypeModel.stock).where(
        CaseTypeModel.case_type_id == case.id))).all()
    assert stocks == [4, 4]  # кэш «в наличии» обновился у обеих моделей группы

    await wh.restore_for_order(session, order)
    assert await stock(session, "base", "Pro Max") == 5


async def test_plate_only_group_keeps_bases_separate(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 3)
    await supply(session, "base", B, 4)
    await supply(session, "plate", A, 1, "silver")
    await supply(session, "plate", B, 2, "silver")

    await sg.save_group(session, name="Пластина PM", scope="plate", models=[A, B])

    assert await stock(session, "plate", "Пластина PM", "silver") == 3
    assert await stock(session, "base", A) == 3  # балванки остались у моделей
    assert await stock(session, "base", B) == 4
    assert await stock(session, "plate", A, "silver") is None


async def test_model_leaving_group_starts_from_zero_and_group_keeps_stock(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 3)
    await supply(session, "base", B, 4)
    await supply(session, "base", C, 1)
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B, C])

    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])

    assert await stock(session, "base", "Pro Max") == 8  # остаток остался группе
    assert await stock(session, "base", C) == 0  # у вышедшей модели свои позиции с нуля
    assert await wh.available_for_sale(session, model_name=C, plate_type="black") == 0


async def test_delete_group_gives_stock_to_first_member_without_loss(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 3)
    await supply(session, "base", B, 4)
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])
    before = await movements_total(session)

    await sg.delete_group(session, "Pro Max")

    assert await stock(session, "base", A) == 7
    assert await stock(session, "base", B) == 0
    assert await stock(session, "base", "Pro Max") is None
    assert await session.scalar(select(StockGroup).where(StockGroup.name == "Pro Max")) is None
    assert await movements_total(session) >= before  # история не потеряна
    assert await sg.list_groups(session) == []


async def test_moving_model_between_groups_does_not_leak_stock(session) -> None:
    await wh.ensure_components(session)
    await supply(session, "base", A, 2)
    await supply(session, "base", B, 3)
    await supply(session, "base", C, 5)
    await sg.save_group(session, name="G1", scope="both", models=[A, B])
    assert await stock(session, "base", "G1") == 5

    await sg.save_group(session, name="G2", scope="both", models=[B, C])

    assert await stock(session, "base", "G1") == 5  # остаток G1 не уехал вместе с B
    assert await stock(session, "base", "G2") == 5  # у G2 только то, что было у C (B вышла с нулём)
    assert await stock(session, "base", B) is None


async def test_list_components_marks_group_rows_with_members(session) -> None:
    await wh.ensure_components(session)
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])
    rows = await wh.list_components(session)
    group_rows = [r for r in rows if r["model_name"] == "Pro Max"]
    assert len(group_rows) == 3  # балванка + две пластины
    assert all(r["members"] == [A, B] for r in group_rows)
    assert all(r["members"] == [] for r in rows if r["model_name"] != "Pro Max")


async def test_ensure_components_does_not_recreate_member_positions(session) -> None:
    await wh.ensure_components(session)
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])
    await wh.ensure_components(session)
    own = (await session.scalars(select(StockComponent).where(
        StockComponent.model_name.in_([A, B])))).all()
    assert own == []


@pytest.mark.parametrize(
    ("name", "scope", "models", "needle"),
    [
        ("", "both", [A, B], "название"),
        ("X" * 65, "both", [A, B], "длинное"),
        ("G", "everything", [A, B], "scope"),
        ("G", "both", [A], "минимум две"),
        ("G", "both", [A, A], "минимум две"),
        ("G", "both", [A, "iPhone 99"], "iPhone 99"),
        (A, "both", [B, C], "совпадает"),
    ],
)
async def test_validation(session, name, scope, models, needle) -> None:
    with pytest.raises(HTTPException) as err:
        await sg.save_group(session, name=name, scope=scope, models=models)
    assert err.value.status_code == 400
    assert needle in err.value.detail
    assert await sg.list_groups(session) == []


async def test_scope_of_existing_group_cannot_change(session) -> None:
    await sg.save_group(session, name="Pro Max", scope="both", models=[A, B])
    with pytest.raises(HTTPException) as err:
        await sg.save_group(session, name="Pro Max", scope="plate", models=[A, B])
    assert err.value.status_code == 400


async def test_unknown_group_delete_is_404(session) -> None:
    with pytest.raises(HTTPException) as err:
        await sg.delete_group(session, "Нет такой")
    assert err.value.status_code == 404


async def test_kinds_constants_sanity() -> None:
    assert {StockKind.BASE, StockKind.PLATE} == {"base", "plate"}
    assert IphoneModel.__tablename__ == "iphone_models"


# ── API: права и сквозной путь ─────────────────────────────────────────────


@pytest.fixture
async def api(session):
    from types import SimpleNamespace

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


async def test_api_create_list_and_dissolve(api, session) -> None:
    body = {"name": "Pro Max", "scope": "both", "models": [A, B]}
    res = await api.post("/api/v1/admin/warehouse/groups", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["models"] == [A, B]

    comps = (await api.get("/api/v1/admin/warehouse/components")).json()
    group_rows = [c for c in comps if c["model_name"] == "Pro Max"]
    assert len(group_rows) == 3 and all(c["members"] == [A, B] for c in group_rows)

    listed = (await api.get("/api/v1/admin/warehouse/groups")).json()
    assert [g["name"] for g in listed] == ["Pro Max"]

    res = await api.delete("/api/v1/admin/warehouse/groups/Pro Max")
    assert res.status_code == 204
    assert (await api.get("/api/v1/admin/warehouse/groups")).json() == []


async def test_api_rejects_bad_group_with_400(api) -> None:
    res = await api.post(
        "/api/v1/admin/warehouse/groups", json={"name": "G", "scope": "both", "models": [A]}
    )
    assert res.status_code == 400
    assert "минимум две" in res.json()["detail"]
    res = await api.delete("/api/v1/admin/warehouse/groups/Нет такой")
    assert res.status_code == 404


@pytest.mark.parametrize("role", ["designer", "printer"])
async def test_api_groups_are_admin_only(api, role) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole(role))
    body = {"name": "Pro Max", "scope": "both", "models": [A, B]}
    assert (await api.post("/api/v1/admin/warehouse/groups", json=body)).status_code == 403
    assert (await api.get("/api/v1/admin/warehouse/groups")).status_code == 403
    assert (await api.delete("/api/v1/admin/warehouse/groups/Pro Max")).status_code == 403


async def test_printer_can_load_everything_the_warehouse_page_needs(api) -> None:
    """Печатник открывает склад: остатки, движения, модели — без 403 (каталог ему закрыт)."""
    from app.enums import AdminRole

    api.set_role(AdminRole.PRINTER)
    for path in ("components", "movements", "models"):
        res = await api.get(f"/api/v1/admin/warehouse/{path}")
        assert res.status_code == 200, (path, res.text)
    assert A in (await api.get("/api/v1/admin/warehouse/models")).json()
    # а вот каталожный эндпоинт по-прежнему только для админа
    assert (await api.get("/api/v1/admin/case-types/iphone-models")).status_code == 403


async def test_designer_cannot_read_warehouse_models(api) -> None:
    from app.enums import AdminRole

    api.set_role(AdminRole.DESIGNER)
    assert (await api.get("/api/v1/admin/warehouse/models")).status_code == 403
