"""Страница склада не должна делать запрос на каждую модель (раньше — 82 запроса на открытие)."""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, func, select, update

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="нужна PostgreSQL: TEST_DATABASE_URL")

# С запасом: важно, что число запросов не растёт вместе с числом моделей.
MAX_QUERIES = 12


@pytest.fixture
async def session():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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
        await s.flush()
        s.sql = SimpleNamespace(count=0)

        def count(*_args, **_kwargs) -> None:
            s.sql.count += 1

        event.listen(conn.sync_connection, "before_cursor_execute", count)
        yield s
        event.remove(conn.sync_connection, "before_cursor_execute", count)
        await s.close()
        await outer.rollback()
    await engine.dispose()


async def test_listing_stock_uses_a_constant_number_of_queries(session) -> None:
    from app.models.catalog import IphoneModel
    from app.services import warehouse as wh

    models = await session.scalar(select(func.count()).select_from(IphoneModel))
    assert models and models > 20  # справочник засеян — проверка осмысленна

    session.sql.count = 0
    rows = await wh.list_components(session)
    first = session.sql.count
    session.sql.count = 0
    await wh.list_components(session)
    again = session.sql.count

    assert len(rows) == models * 3  # балванка + две пластины на модель
    assert first <= MAX_QUERIES, f"первое открытие: {first} запросов"
    assert again <= MAX_QUERIES, f"повторное открытие: {again} запросов"


async def test_ensure_components_is_idempotent_and_creates_only_missing(session) -> None:
    from app.models.warehouse import StockComponent
    from app.services import warehouse as wh

    await wh.ensure_components(session)
    total = await session.scalar(select(func.count()).select_from(StockComponent))
    await wh.supply(session, kind="base", model_name="iPhone 15", qty=4)

    await wh.ensure_components(session)  # второй вызов ничего не создаёт и не трогает остатки

    assert await session.scalar(select(func.count()).select_from(StockComponent)) == total
    qty = await session.scalar(
        select(StockComponent.qty).where(
            StockComponent.kind == "base", StockComponent.model_name == "iPhone 15"
        )
    )
    assert qty == 4


async def test_ensure_components_restores_only_what_is_deleted(session) -> None:
    from app.models.warehouse import StockComponent
    from app.services import warehouse as wh

    await wh.ensure_components(session)
    total = await session.scalar(select(func.count()).select_from(StockComponent))
    await session.execute(delete(StockComponent).where(StockComponent.model_name == "iPhone 16"))

    await wh.ensure_components(session)

    assert await session.scalar(select(func.count()).select_from(StockComponent)) == total


async def test_ensure_components_respects_groups(session) -> None:
    from app.models.warehouse import StockComponent
    from app.services import stock_groups as sg
    from app.services import warehouse as wh

    await wh.ensure_components(session)
    await sg.save_group(session, name="Пара", scope="both", models=["iPhone 15", "iPhone 16"])
    await wh.ensure_components(session)

    own = (
        await session.scalars(
            select(StockComponent).where(StockComponent.model_name.in_(["iPhone 15", "iPhone 16"]))
        )
    ).all()
    assert own == []  # у членов группы нет собственных позиций
    group_rows = (
        await session.scalars(select(StockComponent).where(StockComponent.model_name == "Пара"))
    ).all()
    assert len(group_rows) == 3
