"""Shared pytest fixtures: a TestClient wired to an isolated, temporary upload directory."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_TEST_MAX_UPLOAD_BYTES = 1024


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    """A writable, empty upload directory for a single test."""
    directory = tmp_path / "uploads"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(upload_dir: Path) -> Settings:
    """Test settings with a small size limit so the 'too large' path is cheap to trigger."""
    return Settings(
        max_upload_bytes=_TEST_MAX_UPLOAD_BYTES,
        allowed_extensions="pdf,docx,png,jpg,jpeg",
        upload_dir=upload_dir,
        log_level="WARNING",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient whose settings dependency is overridden with the test settings."""
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
