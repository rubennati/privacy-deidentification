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


def test_storage_defaults_use_document_store_and_dedicated_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "UPLOAD_STORAGE_DIR",
        "UPLOAD_DIR",
        "DOCUMENT_DATA_DIR",
        "DATA_JOB_STATE_DIR",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()

    assert settings.upload_storage_dir == Path("/data/uploads")
    assert settings.document_data_dir == Path("/data/document-store")
    assert settings.job_state_dir == Path("/data/job-state")


def test_job_store_db_path_defaults_under_dedicated_job_state_dir() -> None:
    settings = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-store",
        DATA_JOB_STATE_DIR="/tmp/job-state",
    )

    assert settings.job_store_db_path is None
    # The SQLite DB lives in its own root, never beside per-document artifact folders.
    assert settings.resolved_job_store_db_path == Path("/tmp/job-state/jobs.sqlite3")
    assert not settings.resolved_job_store_db_path.is_relative_to(settings.document_data_dir)


def test_job_store_db_path_can_be_overridden_or_left_empty() -> None:
    overridden = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-store",
        DATA_JOB_STATE_DIR="/tmp/job-state",
        JOB_STORE_DB_PATH="/tmp/jobs/custom.sqlite3",
    )
    defaulted = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-store",
        DATA_JOB_STATE_DIR="/tmp/job-state",
        JOB_STORE_DB_PATH="",
    )

    assert overridden.resolved_job_store_db_path == Path("/tmp/jobs/custom.sqlite3")
    assert defaulted.resolved_job_store_db_path == Path("/tmp/job-state/jobs.sqlite3")


def test_job_state_dir_must_be_separate_from_document_data() -> None:
    with pytest.raises(ValueError, match="must be separate"):
        Settings(
            UPLOAD_STORAGE_DIR="/tmp/originals",
            DOCUMENT_DATA_DIR="/tmp/document-store",
            DATA_JOB_STATE_DIR="/tmp/document-store/job-state",
        )


def test_ocr_execution_mode_defaults_to_worker_and_worker_settings_are_conservative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "OCR_EXECUTION_MODE",
        "OCR_WORKER_POLL_INTERVAL_SECONDS",
        "OCR_WORKER_CONCURRENCY",
        "OCR_WORKER_MAX_ATTEMPTS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
    )

    assert settings.ocr_execution_mode == "worker"
    assert settings.ocr_worker_poll_interval_seconds == 2.0
    assert settings.ocr_worker_concurrency == 1
    # One automatic retry after an interruption, then explicit `interrupted` failure (ADR-0041).
    assert settings.ocr_worker_max_attempts == 2
    assert settings.job_lease_seconds == 3600.0
    assert settings.ocr_worker_heartbeat_stale_seconds == 60.0


def test_ocr_execution_mode_is_normalized_and_empty_stays_worker() -> None:
    worker = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
        OCR_EXECUTION_MODE=" Worker ",
    )
    empty = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
        OCR_EXECUTION_MODE="",
    )

    assert worker.ocr_execution_mode == "worker"
    assert empty.ocr_execution_mode == "worker"


def test_ocr_execution_mode_sync_override_still_works() -> None:
    settings = Settings(
        UPLOAD_STORAGE_DIR="/tmp/originals",
        DOCUMENT_DATA_DIR="/tmp/document-data",
        OCR_EXECUTION_MODE="sync",
    )

    assert settings.ocr_execution_mode == "sync"


def test_unknown_ocr_execution_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(
            UPLOAD_STORAGE_DIR="/tmp/originals",
            DOCUMENT_DATA_DIR="/tmp/document-data",
            OCR_EXECUTION_MODE="celery",
        )


def test_ocr_worker_concurrency_above_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="OCR_WORKER_CONCURRENCY must be 1"):
        Settings(
            UPLOAD_STORAGE_DIR="/tmp/originals",
            DOCUMENT_DATA_DIR="/tmp/document-data",
            OCR_WORKER_CONCURRENCY=2,
        )


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
    # The lightweight pytest runner does not install or provision the real OCR/PII runtimes; see
    # test_runtime_capabilities.py for the true/false branches of the underlying checks.
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

    assert {"PERSON", "ORGANIZATION"}.issubset(broad.pii_entity_types)
    # LOCATION is deliberately excluded from every named profile (it over-tags; residence is
    # covered by ADDRESS, birthplace by BIRTH_PLACE) — selectable only via a custom allowlist.
    assert "LOCATION" not in broad.pii_entity_types
    assert "LOCATION" not in review_heavy.pii_entity_types
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
