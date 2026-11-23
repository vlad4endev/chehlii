"""Права ролей AdminUI: Админ / Дизайнер / Печатник."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.admin.deps import require_order_editor, require_warehouse_staff
from app.api.v1.admin.orders import _allowed_next
from app.enums import AdminRole, OrderStatus


def _user(role: AdminRole) -> SimpleNamespace:
    return SimpleNamespace(role=role)


@pytest.mark.parametrize("role", [AdminRole.ADMIN, AdminRole.DESIGNER])
async def test_order_editor_allows_admin_and_designer(role: AdminRole) -> None:
    user = _user(role)
    assert await require_order_editor(user) is user


async def test_order_editor_denies_printer() -> None:
    with pytest.raises(HTTPException) as err:
        await require_order_editor(_user(AdminRole.PRINTER))
    assert err.value.status_code == 403


@pytest.mark.parametrize("role", [AdminRole.ADMIN, AdminRole.PRINTER])
async def test_warehouse_staff_allows_admin_and_printer(role: AdminRole) -> None:
    user = _user(role)
    assert await require_warehouse_staff(user) is user


async def test_warehouse_staff_denies_designer() -> None:
    with pytest.raises(HTTPException) as err:
        await require_warehouse_staff(_user(AdminRole.DESIGNER))
    assert err.value.status_code == 403


def test_printer_has_no_status_options() -> None:
    order = SimpleNamespace(status=OrderStatus.PREPAYMENT_PAID)
    assert _allowed_next(order, AdminRole.PRINTER) == []
    assert _allowed_next(order, AdminRole.DESIGNER)  # у дизайнера варианты остаются
