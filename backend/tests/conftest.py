"""Shared pytest fixtures with isolated upload, document-store, and job-state directories."""

from __future__ import annotations

import warnings

# Silence a transitive Starlette/httpx deprecation emitted at import of TestClient. It fires
# before pytest's ini filterwarnings apply, so it is suppressed here at the source. Imports
# below intentionally follow this statement (ruff E402 is ignored for this file).
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
    category=Warning,  # StarletteDeprecationWarning subclasses PendingDeprecationWarning
)

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_TEST_MAX_UPLOAD_BYTES = 1024


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    """A writable, empty original-upload directory for a single test."""
    directory = tmp_path / "uploads"
    directory.mkdir()
    return directory


@pytest.fixture
def document_data_dir(tmp_path: Path) -> Path:
    """A writable, empty application-data directory for a single test."""
    directory = tmp_path / "document-store"
    directory.mkdir()
    return directory


@pytest.fixture
def job_state_dir(tmp_path: Path) -> Path:
    """A writable, empty job-state directory (holds jobs.sqlite3) for a single test."""
    directory = tmp_path / "job-state"
    directory.mkdir()
    return directory


@pytest.fixture
def pii_feedback_archive_dir(tmp_path: Path) -> Path:
    """A writable, empty PII feedback archive directory for a single test."""
    directory = tmp_path / "pii-feedback-archive"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(
    upload_dir: Path,
    document_data_dir: Path,
    job_state_dir: Path,
    pii_feedback_archive_dir: Path,
) -> Settings:
    """Test settings with a small size limit so the 'too large' path is cheap to trigger.

    PII detection tests inject spaCy NER types (PERSON/ORGANIZATION/LOCATION), so the fixture
    enables every supported entity type explicitly. The shipped *default* allowlist (structured
    recognizers only) is asserted separately in ``test_config.py``.
    """
    return Settings(
        max_upload_bytes=_TEST_MAX_UPLOAD_BYTES,
        allowed_extensions="pdf,docx,png,jpg,jpeg",
        upload_storage_dir=upload_dir,
        document_data_dir=document_data_dir,
        job_state_dir=job_state_dir,
        pii_feedback_archive_dir=pii_feedback_archive_dir,
        ocr_execution_mode="sync",
        log_level="WARNING",
        pii_entity_types=(
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "IBAN_CODE",
            "CREDIT_CARD",
            "IP_ADDRESS",
            "URL",
            "LOCATION",
            "ORGANIZATION",
            "DATE_TIME",
        ),
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient whose settings dependency is overridden with the test settings."""
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
