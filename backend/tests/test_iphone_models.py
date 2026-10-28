"""Нормализация и канон моделей iPhone."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.iphone_models import normalize_iphone_model_name


def test_normalize_strips_and_collapses() -> None:
    assert normalize_iphone_model_name("  iPhone  19   Pro  ") == "iPhone 19 Pro"


def test_normalize_rejects_empty() -> None:
    with pytest.raises(HTTPException) as exc:
        normalize_iphone_model_name("   ")
    assert exc.value.status_code == 400


def test_normalize_rejects_too_long() -> None:
    with pytest.raises(HTTPException) as exc:
        normalize_iphone_model_name("x" * 65)
    assert exc.value.status_code == 400
