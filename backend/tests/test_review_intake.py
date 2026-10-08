"""Приём отзыва: не путать с консультацией."""

from app.enums import OrderStatus, ReviewStatus
from app.services import review_intake, yandex_disk


def test_review_disk_path() -> None:
    path = yandex_disk.review_path("/disk", "case.jpg")
    assert path.startswith("/disk/reviews/")
    assert path.endswith(".jpg") or "case" in path


def test_review_status_pending_default() -> None:
    assert ReviewStatus.PENDING == "pending"
    assert OrderStatus.REVIEW_OFFERED == "review_offered"
    assert OrderStatus.REVIEW_RECEIVED == "review_received"


def test_module_exports() -> None:
    assert callable(review_intake.pending_order)
    assert callable(review_intake.submit)
