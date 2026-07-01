"""Tests for the public configuration endpoint."""

from __future__ import annotations

import pytest
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


def test_pii_configuration_is_normalized() -> None:
    settings = Settings(
        PII_LANGUAGE=" DE ",
        PII_SCORE_THRESHOLD="0.7",
        PII_ENTITY_TYPES="person, EMAIL_ADDRESS,person",
    )

    assert settings.pii_language == "de"
    assert settings.pii_score_threshold == 0.7
    assert settings.pii_entity_types == ("PERSON", "EMAIL_ADDRESS")


def test_pii_configuration_rejects_unsupported_entity_type() -> None:
    with pytest.raises(ValueError):
        Settings(PII_ENTITY_TYPES="PERSON,CUSTOM_SECRET")
