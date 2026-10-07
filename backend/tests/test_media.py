"""Локальное медиа: расширения, атомарная запись, SHA-256."""

from app.services import media


def test_ext_for_mockup_image_and_pdf() -> None:
    assert media.ext_for("image/png", "a.png", allow_docs=True) == "png"
    assert media.ext_for("image/jpeg", "a.jpg", allow_docs=True) == "jpg"
    assert media.ext_for("application/pdf", "a.pdf", allow_docs=True) == "pdf"
    assert media.ext_for("application/pdf", "a.pdf", allow_docs=False) is None
    assert media.ext_for("text/plain", "notes.txt", allow_docs=True) is None


def test_ext_for_filename_fallback() -> None:
    assert media.ext_for(None, "mockup.WEBP", allow_docs=True) == "webp"
    assert media.ext_for(None, "scan.PDF", allow_docs=True) == "pdf"


def test_resolve_local_and_sniff(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media.settings, "media_root", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12
    url = media.save_bytes(png, "png", "orders/7")
    assert url.startswith("/media/orders/7/")
    path = media.resolve_local(url)
    assert path is not None
    assert path.read_bytes() == png
    assert media.sniff_mime(png) == "image/png"
    assert media.resolve_local("/media/../etc/passwd") is None
    assert media.resolve_local("https://yadi.sk/d/abc") is None
    assert media.resolve_local("/media/orders/7/missing.png") is None


def test_persist_bytes_atomic_and_sha(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media.settings, "media_root", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12
    saved = media.persist_bytes(png, "png", "catalog")
    assert saved.url.startswith("/media/catalog/")
    assert saved.size_bytes == len(png)
    assert saved.sha256 == media.sha256_hex(png)
    assert saved.path.is_file()
    assert media.verify_local(saved.url, expected_sha256=saved.sha256)
    assert not media.verify_local(saved.url, expected_sha256="a" * 64)
    # временных .tmp не осталось
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []


def test_file_ref_shape() -> None:
    from app.services import media_assets

    ref = media_assets.file_ref(
        "/media/a.png", disk_url="https://yadi.sk/d/x", sha256="abc", asset_id=9
    )
    assert ref == {
        "url": "/media/a.png",
        "disk_url": "https://yadi.sk/d/x",
        "sha256": "abc",
        "asset_id": 9,
    }
