"""Tests for upload validation — the security-relevant trust boundary."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

_PDF_BYTES = b"%PDF-1.4 minimal test document"


def _post_file(client: TestClient, name: str, content: bytes, content_type: str):
    return client.post("/api/uploads", files={"file": (name, content, content_type)})


def test_accepts_valid_pdf(client: TestClient, upload_dir: Path) -> None:
    response = _post_file(client, "report.pdf", _PDF_BYTES, "application/pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "report.pdf"
    assert body["size"] == len(_PDF_BYTES)
    assert body["status"] == "received"
    assert body["id"]

    stored = list(upload_dir.iterdir())
    assert len(stored) == 1
    assert stored[0].name == f"{body['id']}.pdf"
    assert stored[0].read_bytes() == _PDF_BYTES


def test_rejects_unsupported_type(client: TestClient, upload_dir: Path) -> None:
    response = _post_file(client, "malware.exe", b"MZ...", "application/octet-stream")

    assert response.status_code == 415
    body = response.json()
    assert "Allowed types" in body["detail"]
    assert body["correlation_id"]
    assert list(upload_dir.iterdir()) == []


def test_rejects_empty_file(client: TestClient, upload_dir: Path) -> None:
    response = _post_file(client, "empty.pdf", b"", "application/pdf")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
    assert list(upload_dir.iterdir()) == []


def test_rejects_file_exceeding_size_limit(client: TestClient, upload_dir: Path) -> None:
    oversized = b"%PDF-1.4 " + b"x" * 2048  # exceeds the 1024-byte test limit

    response = _post_file(client, "big.pdf", oversized, "application/pdf")

    assert response.status_code == 413
    assert "maximum size" in response.json()["detail"]
    assert list(upload_dir.iterdir()) == []


def test_missing_file_returns_400(client: TestClient) -> None:
    response = client.post("/api/uploads")

    assert response.status_code == 400
    assert response.json()["correlation_id"]


def test_sanitizes_traversal_filename_and_stores_under_uuid(
    client: TestClient, upload_dir: Path
) -> None:
    response = _post_file(client, "../../etc/passwd.pdf", _PDF_BYTES, "application/pdf")

    assert response.status_code == 201
    returned_name = response.json()["filename"]
    assert "/" not in returned_name and ".." not in returned_name

    stored = list(upload_dir.iterdir())
    assert len(stored) == 1
    assert stored[0].parent == upload_dir
