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
