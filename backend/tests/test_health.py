"""Tests for the health endpoints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_ok_when_both_storage_directories_are_writable(
    client: TestClient,
) -> None:
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_unavailable_when_document_data_is_not_writable(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_access = os.access

    def storage_access(path: Path, mode: int) -> bool:
        if path == settings.document_data_dir:
            return False
        return real_access(path, mode)

    monkeypatch.setattr("app.api.health.os.access", storage_access)

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
