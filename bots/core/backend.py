"""Клиент единого backend (FastAPI). Боты не держат свою БД — всё через API."""

from __future__ import annotations

import httpx

from bots.core.config import settings


class Backend:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.backend_url, timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def upsert_client(
        self, channel: str, channel_user_id: str, nickname: str | None = None,
        phone: str | None = None,
    ) -> dict:
        r = await self._client.post(
            "/clients/upsert",
            json={
                "channel": channel,
                "channel_user_id": channel_user_id,
                "nickname": nickname,
                "phone": phone,
            },
        )
        r.raise_for_status()
        return r.json()

    async def get_messages(self) -> list[dict]:
        r = await self._client.get("/bot-messages")
        r.raise_for_status()
        return r.json()

    async def create_order(
        self, client_id: int, case_type_id: int, branch: str, model_name: str
    ) -> dict:
        r = await self._client.post(
            "/orders",
            json={
                "client_id": client_id,
                "case_type_id": case_type_id,
                "branch": branch,
                "model_name": model_name,
            },
        )
        r.raise_for_status()
        return r.json()

    async def update_order(self, order_id: int, **fields) -> dict:
        r = await self._client.patch(f"/orders/{order_id}", json=fields)
        r.raise_for_status()
        return r.json()


backend = Backend()
