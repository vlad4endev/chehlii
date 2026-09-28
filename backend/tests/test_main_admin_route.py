"""/admin без слэша должен редиректить в /admin/, а не проваливаться в SPA мини-аппа."""

import importlib

from fastapi.testclient import TestClient


def test_admin_bare_path_redirects_to_trailing_slash(tmp_path, monkeypatch) -> None:
    webroot = tmp_path / "webroot"
    webroot_admin = tmp_path / "webroot-admin"
    webroot.mkdir()
    webroot_admin.mkdir()
    (webroot / "index.html").write_text("miniapp")
    (webroot_admin / "index.html").write_text("admin")

    import app.main as main

    monkeypatch.setattr(main.settings, "webroot", str(webroot))
    monkeypatch.setattr(main.settings, "webroot_admin", str(webroot_admin))
    importlib.reload(main)
    try:
        client = TestClient(main.app)
        redirect = client.get("/admin", follow_redirects=False)
        assert redirect.status_code in (307, 308)
        assert redirect.headers["location"] == "/admin/"

        assert client.get("/admin/").text == "admin"
        assert client.get("/").text == "miniapp"
    finally:
        importlib.reload(main)
