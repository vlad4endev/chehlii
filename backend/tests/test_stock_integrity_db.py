"""Целостность склада на реальной PostgreSQL: гонки, границы, неизвестные модели.

Запуск: TEST_DATABASE_URL=postgresql+asyncpg://… pytest tests/test_stock_integrity_db.py
Тесты на гонки работают с отдельными сессиями и реальными коммитами (транзакцию не
откатить, когда запросы идут параллельно), поэтому чистят за собой склад и свои заказы.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.enums import Channel
from app.models import CaseType, Client, Order
from app.models.catalog import CaseTypeModel, IphoneModel
from app.models.warehouse import StockComponent, StockGroup, StockMovement
from app.services import warehouse as wh

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

MODEL = "iPhone 15"


async def _clean(s: AsyncSession) -> None:
    await s.execute(delete(StockMovement))
    await s.execute(delete(StockComponent))
    await s.execute(update(IphoneModel).values(stock_group_id=None))
    await s.execute(delete(StockGroup))
    await s.execute(delete(Order).where(Order.model_name == MODEL))
    await s.execute(delete(Client).where(Client.channel_user_id.like("race-%")))
    await s.execute(delete(CaseTypeModel).where(CaseTypeModel.model_name == MODEL))
    await s.execute(delete(CaseType).where(CaseType.name == "Гонка"))
    await s.commit()


@pytest.fixture
async def maker():
    engine = create_async_engine(DB_URL, pool_size=30)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _clean(s)
    yield factory
    async with factory() as s:
        await _clean(s)
    await engine.dispose()


async def _qty(factory, kind: str, plate: str | None = None) -> int | None:
    async with factory() as s:
        stmt = select(StockComponent.qty).where(
            StockComponent.kind == kind, StockComponent.model_name == MODEL
        )
        plate_filter = (
            StockComponent.plate_type.is_(None)
            if plate is None
            else StockComponent.plate_type == plate
        )
        stmt = stmt.where(plate_filter)
        return await s.scalar(stmt)


async def _journal_sum(factory) -> int:
    async with factory() as s:
        return int(await s.scalar(select(func.coalesce(func.sum(StockMovement.delta), 0))) or 0)


async def test_concurrent_supplies_are_not_lost(maker) -> None:
    async def one() -> None:
        async with maker() as s:
            await wh.supply(s, kind="base", model_name=MODEL, qty=1)
            await s.commit()

    await asyncio.gather(*[one() for _ in range(20)])

    assert await _qty(maker, "base") == 20
    assert await _journal_sum(maker) == 20  # остаток и журнал совпадают


async def test_concurrent_defects_never_go_negative(maker) -> None:
    async with maker() as s:
        await wh.supply(s, kind="base", model_name=MODEL, qty=5)
        await s.commit()

    async def one() -> str:
        async with maker() as s:
            try:
                await wh.write_off_defect(
                    s, kind="base", model_name=MODEL, qty=1, reason="defect_print"
                )
                await s.commit()
                return "ok"
            except HTTPException as exc:
                await s.rollback()
                return str(exc.status_code)

    results = await asyncio.gather(*[one() for _ in range(10)])

    assert results.count("ok") == 5  # ровно столько, сколько было
    assert results.count("409") == 5  # остальные получили понятный отказ, а не потерю
    assert await _qty(maker, "base") == 0
    assert await _journal_sum(maker) == 0


async def test_first_creation_race_does_not_crash(maker) -> None:
    async def one() -> None:
        async with maker() as s:
            await wh.supply(s, kind="plate", model_name=MODEL, plate_type="black", qty=1)
            await s.commit()

    await asyncio.gather(*[one() for _ in range(10)])  # без IntegrityError на уникальном индексе

    assert await _qty(maker, "plate", "black") == 10


async def test_two_orders_for_the_last_item_deduct_exactly_one(maker) -> None:
    async with maker() as s:
        await wh.supply(s, kind="base", model_name=MODEL, qty=1)
        await wh.supply(s, kind="plate", model_name=MODEL, plate_type="black", qty=1)
        case = CaseType(name="Гонка", plate_type="black", cost=1, margin=1)
        s.add(case)
        await s.flush()
        ids = []
        for i in range(2):
            client = Client(channel=Channel.TG, channel_user_id=f"race-{i}")
            s.add(client)
            await s.flush()
            order = Order(client_id=client.id, case_type_id=case.id, model_name=MODEL)
            s.add(order)
            await s.flush()
            ids.append(order.id)
        await s.commit()

    async def deduct(order_id: int) -> bool:
        async with maker() as s:
            order = await s.get(Order, order_id)
            await wh.deduct_for_order(s, order)
            await s.commit()
            return bool(order.stock_deducted)

    flags = await asyncio.gather(*[deduct(i) for i in ids])

    assert sorted(flags) == [False, True]  # один заказ списан, второй честно «не списан»
    assert await _qty(maker, "base") == 0
    assert await _qty(maker, "plate", "black") == 0  # пара списывается целиком, без половинок


# ── Граничные значения и неизвестные модели (через API) ────────────────────


@pytest.fixture
async def api(maker):
    import httpx

    from app.api.v1.admin.deps import get_current_admin
    from app.core.database import get_session
    from app.enums import AdminRole
    from app.main import app

    async def fake_session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        id=None, role=AdminRole.ADMIN, is_active=True
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["supply", "defect"])
async def test_huge_quantity_is_rejected_not_500(api, path) -> None:
    body = {"kind": "base", "model_name": MODEL, "qty": 3_000_000_000, "reason": "defect_print"}
    res = await api.post(f"/api/v1/admin/warehouse/{path}", json=body)
    assert res.status_code == 422


async def test_adjust_and_create_reject_huge_quantity(api) -> None:
    res = await api.post(
        "/api/v1/admin/warehouse/components",
        json={"kind": "base", "model_name": MODEL, "qty": 3_000_000_000},
    )
    assert res.status_code == 422


@pytest.mark.parametrize("path", ["supply", "defect"])
async def test_unknown_model_is_rejected(api, path) -> None:
    body = {"kind": "base", "model_name": "Nokia 3310", "qty": 1, "reason": "defect_print"}
    res = await api.post(f"/api/v1/admin/warehouse/{path}", json=body)
    assert res.status_code == 400
    assert "справочнике" in res.json()["detail"]


async def test_shortage_message_is_in_russian_without_jargon(api) -> None:
    res = await api.post(
        "/api/v1/admin/warehouse/supply", json={"kind": "base", "model_name": MODEL, "qty": 1}
    )
    assert res.status_code == 201
    res = await api.post(
        "/api/v1/admin/warehouse/defect",
        json={"kind": "base", "model_name": MODEL, "qty": 5, "reason": "defect_print"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "Балванка" in detail and "iPhone 15" in detail
    assert "base" not in detail and "plate" not in detail
    assert "есть 1" in detail and "нужно 5" in detail
