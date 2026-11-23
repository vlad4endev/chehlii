"""Логотип: публичное чтение, сохранение только админом, безопасные значения."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.v1.admin.deps import get_current_admin
from app.core.database import get_session
from app.enums import AdminRole
from app.main import app
from app.services.brand import MAX_LOGO_URL_LEN, clean_logo_url


class FakeSession:
    """Достаточно для integration_settings: get / add / commit."""

    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        self.rows[row.key] = row

    async def commit(self) -> None:
        return None


@pytest.fixture
def client():
    session = FakeSession()

    async def fake_session():
        yield session

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        role=AdminRole.ADMIN, is_active=True
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_public_logo_is_empty_by_default(client) -> None:
    res = client.get("/api/v1/brand")
    assert res.status_code == 200
    assert res.json() == {"logo_url": None}


def test_admin_saves_logo_and_everyone_sees_it(client) -> None:
    res = client.put("/api/v1/admin/brand/logo", json={"logo_url": "/media/catalog/logo.svg"})
    assert res.status_code == 200
    assert res.json() == {"logo_url": "/media/catalog/logo.svg"}
    assert client.get("/api/v1/brand").json() == {"logo_url": "/media/catalog/logo.svg"}
    assert client.get("/api/v1/admin/brand/logo").json() == {"logo_url": "/media/catalog/logo.svg"}


def test_empty_value_resets_to_default(client) -> None:
    client.put("/api/v1/admin/brand/logo", json={"logo_url": "/media/catalog/logo.svg"})
    for empty in ("", "   ", None):
        res = client.put("/api/v1/admin/brand/logo", json={"logo_url": empty})
        assert res.status_code == 200
        assert client.get("/api/v1/brand").json() == {"logo_url": None}


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,<svg onload=alert(1)>",
        "//evil.example/x.png",
        "logo.png",
    ],
)
def test_unsafe_values_are_rejected(client, bad: str) -> None:
    res = client.put("/api/v1/admin/brand/logo", json={"logo_url": bad})
    assert res.status_code == 400
    assert client.get("/api/v1/brand").json() == {"logo_url": None}  # ничего не сохранилось


def test_too_long_value_is_rejected(client) -> None:
    too_long = "/media/" + "a" * MAX_LOGO_URL_LEN
    res = client.put("/api/v1/admin/brand/logo", json={"logo_url": too_long})
    assert res.status_code == 400


def test_designer_cannot_change_logo(client) -> None:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        role=AdminRole.DESIGNER, is_active=True
    )
    res = client.put("/api/v1/admin/brand/logo", json={"logo_url": "/media/catalog/logo.svg"})
    assert res.status_code == 403
    assert client.get("/api/v1/brand").json() == {"logo_url": None}


def test_clean_logo_url_accepts_http_links() -> None:
    url = "https://cdn.example.com/logo.png"
    assert clean_logo_url(f" {url} ") == url
