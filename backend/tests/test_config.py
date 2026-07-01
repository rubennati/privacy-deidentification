"""Tests for the public configuration endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings


def test_storage_configuration_uses_clear_names_and_accepts_legacy_upload_dir() -> None:
    settings = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
    )
    legacy = Settings(UPLOAD_DIR="/tmp/legacy-uploads", DOCUMENT_DATA_DIR="/tmp/app-data")

    assert settings.upload_storage_dir == Path("/tmp/originals")
    assert settings.document_data_dir == Path("/tmp/document-data")
    assert legacy.upload_storage_dir == Path("/tmp/legacy-uploads")


@pytest.mark.parametrize(
    ("upload_dir", "document_data_dir"),
    [
        ("/tmp/storage", "/tmp/storage"),
        ("/tmp/storage", "/tmp/storage/document-data"),
        ("/tmp/storage/uploads", "/tmp/storage"),
    ],
)
def test_storage_configuration_rejects_equal_or_nested_roots(
    upload_dir: str, document_data_dir: str
) -> None:
    with pytest.raises(ValueError, match="must be separate"):
        Settings(
            UPLOAD_STORAGE_DIR=upload_dir,
            DOCUMENT_DATA_DIR=document_data_dir,
        )


def test_config_returns_effective_upload_constraints(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_bytes"] == 1024  # from the test settings fixture
    assert body["allowed_extensions"] == ["docx", "jpeg", "jpg", "pdf", "png"]


def test_empty_ocr_model_directory_is_unconfigured() -> None:
    settings = Settings(OCR_MODEL_DIR="")

    assert settings.ocr_model_dir is None


def test_ocr_model_names_default_to_latin_capable_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCR_DETECTION_MODEL_NAME", raising=False)
    monkeypatch.delenv("OCR_RECOGNITION_MODEL_NAME", raising=False)

    settings = Settings()

    assert settings.ocr_detection_model_name == "PP-OCRv5_mobile_det"
    # The Latin recognizer covers German/Latin-script documents (umlauts, ß).
    assert settings.ocr_recognition_model_name == "latin_PP-OCRv5_mobile_rec"


def test_empty_ocr_model_names_fall_back_to_paddle_default() -> None:
    settings = Settings(OCR_DETECTION_MODEL_NAME="", OCR_RECOGNITION_MODEL_NAME="")

    assert settings.ocr_detection_model_name is None
    assert settings.ocr_recognition_model_name is None


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


def test_default_pii_entity_types_are_structured_recognizers_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PII_ENTITY_TYPES", raising=False)

    settings = Settings()

    assert settings.pii_entity_types == (
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "URL",
    )
    # The noisy spaCy NER types and DATE_TIME are opt-in, not default.
    for opt_in in ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME"):
        assert opt_in not in settings.pii_entity_types


def test_spacy_ner_types_remain_supported_and_opt_in() -> None:
    settings = Settings(PII_ENTITY_TYPES="PERSON,ORGANIZATION,LOCATION,DATE_TIME")

    assert settings.pii_entity_types == ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME")
