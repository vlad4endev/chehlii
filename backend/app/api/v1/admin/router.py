"""Агрегатор роутеров AdminUI. Разделы добавляются по фазам (см. docs/ADMIN_PANEL.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.auth import router as auth_router

admin_router = APIRouter()
admin_router.include_router(auth_router, prefix="/auth", tags=["admin-auth"])
