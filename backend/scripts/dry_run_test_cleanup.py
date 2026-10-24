#!/usr/bin/env python3
"""Сухой прогон: кандидаты на удаление тестовых данных (п. 3 приёмки).

Ничего не удаляет. Печатает списки заказов, клиентов, отзывов и рассылок,
похожих на тестовые. Перед реальной чисткой — бэкап БД и согласование списка.

Запуск из backend/:
  .venv/bin/python -m scripts.dry_run_test_cleanup
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.client import Client
from app.models.engagement import Review
from app.models.messaging import Broadcast
from app.models.order import Order

TEST_NICK_RE = re.compile(
    r"(марина|илья|sofia|ольга|vl4endev|test|тест|demo|демо|dev)",
    re.IGNORECASE,
)
TEST_PHONES = {"+70000000000", "+79999999999"}


def _client_suspect(c: Client) -> bool:
    if c.nickname and TEST_NICK_RE.search(c.nickname):
        return True
    if c.phone and (c.phone in TEST_PHONES or c.phone.startswith("+7000")):
        return True
    return False


async def main() -> None:
    async with SessionLocal() as session:
        clients = (await session.scalars(select(Client).where(Client.deleted_at.is_(None)))).all()
        suspect_clients = [c for c in clients if _client_suspect(c)]
        client_ids = {c.id for c in suspect_clients}

        all_orders = (
            await session.scalars(select(Order).where(Order.deleted_at.is_(None)))
        ).all()
        suspect_orders = [
            o for o in all_orders if o.is_test or o.client_id in client_ids
        ]

        all_reviews = (await session.scalars(select(Review))).all()
        suspect_reviews = [
            r
            for r in all_reviews
            if (r.client_id in client_ids)
            or (r.author_name and TEST_NICK_RE.search(r.author_name))
        ]

        broadcasts = (await session.scalars(select(Broadcast))).all()
        suspect_broadcasts = [
            b
            for b in broadcasts
            if (b.text and TEST_NICK_RE.search(b.text))
            or (b.segment and "test" in str(b.segment).lower())
        ]

    print("=== DRY RUN: кандидаты на чистку (ничего не удалено) ===\n")
    print(f"Клиенты ({len(suspect_clients)}):")
    for c in suspect_clients:
        print(f"  #{c.id}  {c.channel}  nick={c.nickname!r}  phone={c.phone!r}")
    print(f"\nЗаказы ({len(suspect_orders)}):")
    for o in sorted(suspect_orders, key=lambda x: x.id):
        print(f"  #{o.id}  client={o.client_id}  status={o.status}  is_test={o.is_test}")
    print(f"\nОтзывы ({len(suspect_reviews)}):")
    for r in suspect_reviews:
        print(
            f"  #{r.id}  client={r.client_id}  author={r.author_name!r}  status={r.status}"
        )
    print(f"\nРассылки-кандидаты ({len(suspect_broadcasts)}):")
    for b in suspect_broadcasts:
        preview = (b.text or "")[:80].replace("\n", " ")
        print(f"  #{b.id}  sent_at={b.sent_at}  text={preview!r}")
    print("\nСогласуйте список с заказчиком, сделайте бэкап БД, затем чистите вручную.")


if __name__ == "__main__":
    asyncio.run(main())
