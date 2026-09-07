"""Локальное медиа: расширения для макета и материалов клиента."""

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
