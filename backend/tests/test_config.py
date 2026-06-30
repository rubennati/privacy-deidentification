"""Tests for the public configuration endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_config_returns_effective_upload_constraints(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["max_upload_bytes"] == 1024  # from the test settings fixture
    assert body["allowed_extensions"] == ["docx", "jpeg", "jpg", "pdf", "png"]
