"""Tests for the public configuration endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings


def test_config_returns_effective_upload_constraints(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_bytes"] == 1024  # from the test settings fixture
    assert body["allowed_extensions"] == ["docx", "jpeg", "jpg", "pdf", "png"]


def test_empty_ocr_model_directory_is_unconfigured() -> None:
    settings = Settings(OCR_MODEL_DIR="")

    assert settings.ocr_model_dir is None
