"""Tests for the public configuration endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.pii_profiles import (
    ADDRESS_CONTACT_TYPES,
    DOMAIN_SENSITIVE_TYPES,
    PII_PROFILES,
    STRUCTURED_TYPES,
)


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


def test_pii_feedback_archive_dir_defaults_to_a_third_separate_root() -> None:
    settings = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
    )

    assert settings.pii_feedback_archive_dir == Path("/data/pii-feedback-archive")


@pytest.mark.parametrize(
    ("upload_dir", "document_data_dir", "archive_dir"),
    [
        # Archive equals or nests with upload.
        ("/tmp/storage", "/tmp/document-data", "/tmp/storage"),
        ("/tmp/storage", "/tmp/document-data", "/tmp/storage/archive"),
        # Archive equals or nests with document-data.
        ("/tmp/uploads", "/tmp/storage", "/tmp/storage"),
        ("/tmp/uploads", "/tmp/storage", "/tmp/storage/archive"),
    ],
)
def test_pii_feedback_archive_dir_rejects_overlap_with_either_root(
    upload_dir: str, document_data_dir: str, archive_dir: str
) -> None:
    with pytest.raises(ValueError, match="must be separate"):
        Settings(
            UPLOAD_STORAGE_DIR=upload_dir,
            DOCUMENT_DATA_DIR=document_data_dir,
            PII_FEEDBACK_ARCHIVE_DIR=archive_dir,
        )


def test_config_returns_effective_upload_constraints(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_bytes"] == 1024  # from the test settings fixture
    assert body["allowed_extensions"] == ["docx", "jpeg", "jpg", "pdf", "png"]
    assert body["dev_engine_settings_enabled"] is False
    assert body["pii"] == {
        "default_profile": "custom",
        "available_profiles": list(PII_PROFILES),
        "candidate_validation_enabled": True,
        "score_threshold": 0.5,
    }
    # The pytest/CI backend image installs no OCR/PII extras, so both are correctly unavailable;
    # see test_runtime_capabilities.py for the true/false branches of the underlying checks.
    assert body["runtime"] == {
        "ocr_available": False,
        "pii_available": False,
        "ocr_memory_limit_low": False,
    }


def test_config_surfaces_a_low_ocr_memory_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When OCR is installed but the container memory limit is too low, `/api/config` must say
    so, rather than that only being discoverable via a live request's 502/OOM-kill."""
    monkeypatch.setattr("app.api.config.ocr_runtime_available", lambda settings: True)
    monkeypatch.setattr("app.api.config.ocr_memory_limit_is_low", lambda settings: True)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["runtime"] == {
        "ocr_available": True,
        "pii_available": False,
        "ocr_memory_limit_low": True,
    }


def test_dev_engine_settings_default_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENABLE_DEV_ENGINE_SETTINGS", raising=False)

    settings = Settings()

    assert settings.enable_dev_engine_settings is False


def test_dev_engine_settings_can_be_enabled() -> None:
    settings = Settings(ENABLE_DEV_ENGINE_SETTINGS=True)

    assert settings.enable_dev_engine_settings is True


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
    assert settings.effective_pii_profile == "custom"


def test_pii_configuration_rejects_unsupported_entity_type() -> None:
    with pytest.raises(ValueError):
        Settings(PII_ENTITY_TYPES="PERSON,CUSTOM_SECRET")


def test_default_pii_entity_types_are_structured_recognizers_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PII_ENTITY_TYPES", raising=False)

    settings = Settings()

    assert settings.pii_profile == "structured-only"
    assert settings.effective_pii_profile == "structured-only"
    assert settings.pii_entity_types == STRUCTURED_TYPES
    # The noisy spaCy NER types and DATE_TIME are opt-in, not default.
    for opt_in in ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME"):
        assert opt_in not in settings.pii_entity_types
    for address_contact_type in ADDRESS_CONTACT_TYPES:
        assert address_contact_type not in settings.pii_entity_types


def test_spacy_ner_types_remain_supported_and_opt_in() -> None:
    settings = Settings(PII_ENTITY_TYPES="PERSON,ORGANIZATION,LOCATION,DATE_TIME")

    assert settings.pii_entity_types == ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME")


def test_insurance_profile_includes_domain_types_without_ner() -> None:
    settings = Settings(PII_PROFILE="insurance-at-de")

    assert settings.effective_pii_profile == "insurance-at-de"
    assert set(DOMAIN_SENSITIVE_TYPES).issubset(settings.pii_entity_types)
    for ner_type in ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME"):
        assert ner_type not in settings.pii_entity_types


def test_broad_and_review_heavy_profiles_keep_ner_explicit() -> None:
    broad = Settings(PII_PROFILE="broad-review")
    review_heavy = Settings(PII_PROFILE="review-heavy")

    assert {"PERSON", "ORGANIZATION", "LOCATION"}.issubset(broad.pii_entity_types)
    assert "DATE_TIME" not in broad.pii_entity_types
    assert "DATE_TIME" in review_heavy.pii_entity_types


def test_explicit_entity_types_override_named_profile() -> None:
    settings = Settings(
        PII_PROFILE="insurance-at-de",
        PII_ENTITY_TYPES="EMAIL_ADDRESS,UID_AT",
    )

    assert settings.pii_entity_types == ("EMAIL_ADDRESS", "UID_AT")
    assert settings.effective_pii_profile == "custom"


def test_empty_entity_type_override_uses_named_profile() -> None:
    settings = Settings(PII_PROFILE="insurance-at-de", PII_ENTITY_TYPES="")

    assert settings.effective_pii_profile == "insurance-at-de"
    assert set(DOMAIN_SENSITIVE_TYPES).issubset(settings.pii_entity_types)


def test_unknown_pii_profile_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(PII_PROFILE="maximum-everything")
