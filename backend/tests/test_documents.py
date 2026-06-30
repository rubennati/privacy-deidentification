"""Tests for document listing and deletion — including the id trust boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.document_service import is_valid_document_id

_PDF_BYTES = b"%PDF-1.4 minimal test document"


def _post_file(client: TestClient, name: str, content: bytes, content_type: str):
    return client.post("/api/uploads", files={"file": (name, content, content_type)})


def test_list_documents_empty_when_nothing_uploaded(client: TestClient) -> None:
    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_uploaded_documents(client: TestClient) -> None:
    upload = _post_file(client, "report.pdf", _PDF_BYTES, "application/pdf")
    document_id = upload.json()["id"]

    response = client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == document_id
    assert body[0]["filename"] == "report.pdf"
    assert body[0]["size"] == len(_PDF_BYTES)
    assert body[0]["content_type"] == "application/pdf"
    assert body[0]["sha256"] == hashlib.sha256(_PDF_BYTES).hexdigest()
    assert body[0]["detected_mime_type"] == "application/pdf"
    assert body[0]["original_artifact"]["document_id"] == document_id
    assert body[0]["original_artifact"]["kind"] == "original"
    assert body[0]["status"] == "received"
    assert body[0]["uploaded_at"]


def test_list_documents_returns_newest_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    timestamps = iter(["2026-06-30T18:00:00Z", "2026-06-30T19:00:00Z"])
    monkeypatch.setattr("app.services.document_service.now_utc_iso", lambda: next(timestamps))

    _post_file(client, "first.pdf", _PDF_BYTES, "application/pdf")
    _post_file(client, "second.pdf", _PDF_BYTES, "application/pdf")

    response = client.get("/api/documents")

    assert [doc["filename"] for doc in response.json()] == ["second.pdf", "first.pdf"]


def test_delete_removes_file_and_metadata(client: TestClient, upload_dir: Path) -> None:
    upload = _post_file(client, "report.pdf", _PDF_BYTES, "application/pdf")
    document_id = upload.json()["id"]

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 204
    assert list(upload_dir.iterdir()) == []
    assert client.get("/api/documents").json() == []


def test_delete_unknown_id_returns_404(client: TestClient) -> None:
    response = client.delete("/api/documents/" + "a" * 32)

    assert response.status_code == 404
    body = response.json()
    assert body["correlation_id"]
    assert "/" not in body["detail"]


@pytest.mark.parametrize(
    "malicious_id",
    [
        "." * 32,
        "../../../../etc/passwd",
        "abc",
        "ABCDEF0123456789ABCDEF0123456789",
    ],
)
def test_delete_rejects_unsafe_ids_without_leaking_internals(
    client: TestClient, upload_dir: Path, malicious_id: str
) -> None:
    response = client.delete(f"/api/documents/{malicious_id}")

    assert response.status_code in (400, 404)
    assert "Traceback" not in response.text
    assert str(upload_dir) not in response.text


@pytest.mark.parametrize(
    "candidate",
    [
        "../../etc/passwd",
        "abc/def",
        "abc",
        "",
        "a" * 31,
        "a" * 33,
        "ABCDEF0123456789ABCDEF0123456789",
    ],
)
def test_is_valid_document_id_rejects_unsafe_values(candidate: str) -> None:
    assert is_valid_document_id(candidate) is False


def test_is_valid_document_id_accepts_uuid_hex() -> None:
    assert is_valid_document_id("a" * 32) is True
