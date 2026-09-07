"""Тесты Яндекс.Диска: OAuth-заголовки, URL авторизации, разбор ответов.

Сеть не трогаем — только разбор ответов и форма URL из quickstart.
"""

from app.services import yandex_disk as yd


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ("Unauthorized" if status_code >= 400 else "")
        self.content = b"{}" if payload is not None else b""

    def json(self):
        return self._payload


def _fake_client(routes: dict[str, _FakeResponse], monkeypatch, *, capture: dict | None = None):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            if capture is not None:
                capture["headers"] = kw.get("headers")
            if "/resources/upload" in url and "/v1/disk/resources/upload" in routes:
                return routes["/v1/disk/resources/upload"]
            if "/resources" in url and "/v1/disk/resources" in routes:
                return routes["/v1/disk/resources"]
            if url.rstrip("/").endswith("/v1/disk") and "/v1/disk" in routes:
                return routes["/v1/disk"]
            raise AssertionError(f"неожиданный GET: {url}")

        async def put(self, url, **kw):
            if url.startswith("https://uploader") or "upload-target" in url:
                return routes.get("/uploader", _FakeResponse(201))
            if "/publish" in url:
                return routes.get("/v1/disk/resources/publish", _FakeResponse(200))
            if "/resources" in url:
                return routes.get("/v1/disk/resources:put", _FakeResponse(201))
            raise AssertionError(f"неожиданный PUT: {url}")

        async def post(self, url, **kw):
            if url.endswith("/token") and "/token" in routes:
                return routes["/token"]
            raise AssertionError(f"неожиданный POST: {url}")

    monkeypatch.setattr(yd.httpx, "AsyncClient", Client)


def test_safe_filename_strips_path_and_punctuation():
    name = "Изображение Со, 6 г., 02_25_12.png"
    assert yd.safe_filename(name) == "Изображение_Со_6_г._02_25_12.png"
    assert yd.safe_filename("../../x.png") == "x.png"
    assert yd.safe_filename("a/b\\c.jpeg") == "c.jpeg"
    path = yd.design_path("/chechlii/orders", 20, "Макет, v2.png")
    assert path.endswith("/20/design/Макет_v2.png")


def test_sanitize_strips_oauth_prefix_and_quotes():
    assert yd.sanitize_token("  OAuth y0_abc  ") == "y0_abc"
    assert yd.sanitize_token("Bearer y0_abc") == "y0_abc"
    assert yd.sanitize_token('"y0_abc"') == "y0_abc"
    assert yd.sanitize_token("") == ""


def test_sanitize_extracts_token_from_yandex_redirect():
    pasted = (
        "https://oauth.yandex.ru/verification_code#"
        "access_token=y0_AgAAreal&token_type=bearer&expires_in=31536000"
    )
    assert yd.sanitize_token(pasted) == "y0_AgAAreal"
    assert yd.sanitize_token("y0_Ag\nAA xx") == "y0_AgAAxx"


def test_authorize_url_matches_quickstart():
    url = yd.authorize_url("client-123")
    assert url.startswith("https://oauth.yandex.ru/authorize?")
    assert "response_type=token" in url
    assert "client_id=client-123" in url
    assert "redirect_uri" not in url
    assert "force_confirm=yes" in url
    assert "scope" not in url


def test_authorize_url_optional_redirect_is_encoded():
    url = yd.authorize_url("client-123", redirect_uri="http://localhost:5174/settings")
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5174%2Fsettings" in url


def test_headers_are_oauth_and_json():
    h = yd._headers("  OAuth y0_token ")
    assert h["Authorization"] == "OAuth y0_token"
    assert h["Accept"] == "application/json"
    assert h["Content-Type"] == "application/json"


async def test_check_connection_ok(monkeypatch):
    seen: dict = {}
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
        capture=seen,
    )
    ok, detail = await yd.check_connection(token="y0_token", root="/chechlii/orders")
    assert ok is True
    assert "casetop" in detail
    assert "Папка /chechlii/orders есть" in detail
    assert seen["headers"]["Authorization"] == "OAuth y0_token"
    assert seen["headers"]["Accept"] == "application/json"


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
    assert "401" in detail
    assert "Получить токен" in detail


async def test_disk_info_forbidden_falls_back_to_listing(monkeypatch):
    _fake_client(
        {
            "/v1/disk": _FakeResponse(403, payload={"error": "ForbiddenError"}, text="Forbidden"),
            "/v1/disk/resources": _FakeResponse(200, {"type": "dir"}),
        },
        monkeypatch,
    )
    ok, detail = await yd.check_connection(token="y0_token", root="/chechlii/orders")
    assert ok is True
    assert "disk.info" in detail


async def test_empty_token_does_not_hit_network(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("без токена сеть трогать нельзя")

    monkeypatch.setattr(yd.httpx, "AsyncClient", boom)
    ok, detail = await yd.check_connection(token="")
    assert ok is False
    assert "не задан" in detail


async def test_exchange_code_returns_access_token(monkeypatch):
    _fake_client(
        {"/token": _FakeResponse(200, {"access_token": "y0_from_code", "token_type": "bearer"})},
        monkeypatch,
    )
    token = await yd.exchange_code(client_id="id", client_secret="sec", code="abc")
    assert token == "y0_from_code"


async def test_upload_publishes_and_returns_public_url(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(yd.asyncio, "sleep", no_sleep)
    _fake_client(
        {
            "/v1/disk/resources:put": _FakeResponse(201),
            "/v1/disk/resources/upload": _FakeResponse(
                200, {"href": "https://uploader.disk.yandex.net/upload-target/1"}
            ),
            "/uploader": _FakeResponse(201),
            "/v1/disk/resources/publish": _FakeResponse(200),
            "/v1/disk/resources": _FakeResponse(
                200, {"public_url": "https://yadi.sk/d/abc", "file": "https://downloader/x"}
            ),
        },
        monkeypatch,
    )
    url = await yd.upload("/chechlii/orders/1/design/a.png", b"png", token="y0_token")
    assert url == "https://yadi.sk/d/abc"


async def test_upload_accepts_202_and_returns_public_url(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(yd.asyncio, "sleep", no_sleep)
    _fake_client(
        {
            "/v1/disk/resources:put": _FakeResponse(201),
            "/v1/disk/resources/upload": _FakeResponse(
                200, {"href": "https://uploader.disk.yandex.net/upload-target/1"}
            ),
            "/uploader": _FakeResponse(202),
            "/v1/disk/resources/publish": _FakeResponse(200),
            "/v1/disk/resources": _FakeResponse(200, {"public_url": "https://yadi.sk/d/waited"}),
        },
        monkeypatch,
    )
    url = await yd.upload("/chechlii/orders/1/design/a.png", b"png", token="y0_token")
    assert url == "https://yadi.sk/d/waited"


async def test_upload_401_asks_to_reauth(monkeypatch):
    _fake_client(
        {
            "/v1/disk/resources:put": _FakeResponse(
                401, payload={"error": "UnauthorizedError", "message": "Не авторизован."}
            ),
        },
        monkeypatch,
    )
    try:
        await yd.upload("/chechlii/orders/1/design/a.png", b"png", token="stale")
    except yd.YandexDiskError as e:
        assert "401" in str(e)
        assert "Получить токен" in str(e)
    else:
        raise AssertionError("ожидали YandexDiskError")
