"""Тесты пробы связи с Яндекс.Диском. Сеть не трогаем — только разбор ответов."""

from app.services import yandex_disk as yd


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ("Unauthorized" if status_code >= 400 else "")
        self.content = b"{}" if payload is not None else b""

    def json(self):
        return self._payload


def _fake_client(routes: dict[str, _FakeResponse], monkeypatch):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            # /v1/disk — префикс /v1/disk/resources, поэтому resources проверяем первым.
            if "/resources" in url and "/v1/disk/resources" in routes:
                return routes["/v1/disk/resources"]
            if url.rstrip("/").endswith("/v1/disk") and "/v1/disk" in routes:
                return routes["/v1/disk"]
            raise AssertionError(f"неожиданный запрос: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)


async def test_check_connection_ok(monkeypatch):
    _fake_client(
        {
            "/v1/disk/resources": _FakeResponse(200, {"type": "dir", "path": "disk:/chechlii"}),
            "/v1/disk": _FakeResponse(
                200,
                {
                    "used_space": 1024**3,
                    "total_space": 10 * 1024**3,
                    "user": {"display_name": "casetop"},
                },
            ),
        },
        monkeypatch,
    )
    ok, detail = await yd.check_connection(token="y0_token", root="/chechlii/orders")
    assert ok is True
    assert "casetop" in detail
    assert "Папка /chechlii/orders есть" in detail


async def test_missing_folder_is_still_connected(monkeypatch):
    # 404 на корне — токен принят, папка появится при загрузке макета.
    _fake_client(
        {
            "/v1/disk/resources": _FakeResponse(404, text="DiskNotFoundError"),
            "/v1/disk": _FakeResponse(200, {"user": {"login": "shop"}}),
        },
        monkeypatch,
    )
    ok, detail = await yd.check_connection(token="y0_token", root="/chechlii/orders")
    assert ok is True
    assert "ещё не создана" in detail


async def test_rejected_token(monkeypatch):
    _fake_client({"/v1/disk": _FakeResponse(401, text="UnauthorizedError")}, monkeypatch)
    ok, detail = await yd.check_connection(token="bad")
    assert ok is False
    assert "токен отклонён" in detail


async def test_empty_token_does_not_hit_network(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("без токена сеть трогать нельзя")

    monkeypatch.setattr(yd.httpx, "AsyncClient", boom)
    ok, detail = await yd.check_connection(token="")
    assert ok is False
    assert "не задан" in detail
