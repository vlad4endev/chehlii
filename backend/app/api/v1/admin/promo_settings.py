"""Дефолты скидочной программы друзей (integration_settings)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.deps import AdminOnly
from app.core.database import get_session
from app.models.settings import IntegrationSetting
from app.services import promo

router = APIRouter()


class PromoSettings(BaseModel):
    friend_discount_pct: float = Field(ge=0, le=100)
    inviter_bonus_pct: float = Field(ge=0, le=100)
    max_total_discount_pct: float = Field(ge=0, le=100)


async def _read(session: AsyncSession) -> PromoSettings:
    return PromoSettings(
        friend_discount_pct=await promo.setting_pct(session, promo.FRIEND_KEY),
        inviter_bonus_pct=await promo.setting_pct(session, promo.INVITER_KEY),
        max_total_discount_pct=await promo.setting_pct(session, promo.MAX_KEY),
    )


@router.get("", response_model=PromoSettings)
async def get_promo_settings(
    _: AdminOnly, session: Annotated[AsyncSession, Depends(get_session)]
) -> PromoSettings:
    return await _read(session)


@router.put("", response_model=PromoSettings)
async def save_promo_settings(
    body: PromoSettings,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PromoSettings:
    for key, val in [
        (promo.FRIEND_KEY, str(body.friend_discount_pct)),
        (promo.INVITER_KEY, str(body.inviter_bonus_pct)),
        (promo.MAX_KEY, str(body.max_total_discount_pct)),
    ]:
        row = await session.get(IntegrationSetting, key)
        if row is None:
            session.add(IntegrationSetting(key=key, value=val))
        else:
            row.value = val
    await session.commit()
    return await _read(session)
