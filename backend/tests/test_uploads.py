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
    assert {path.name for path in stored} == {f"{body['id']}.pdf", f"{body['id']}.meta.json"}
    stored_file = upload_dir / f"{body['id']}.pdf"
    assert stored_file.read_bytes() == _PDF_BYTES


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
    assert len(stored) == 2  # stored file + metadata sidecar
    assert all(path.parent == upload_dir for path in stored)


def test_rejects_content_not_matching_extension(client: TestClient, upload_dir: Path) -> None:
    # Allowed extension, but the bytes are not a PDF — must be rejected on content.
    response = _post_file(client, "fake.pdf", b"GIF89a definitely not a pdf", "application/pdf")

    assert response.status_code == 415
    assert "does not match" in response.json()["detail"]
    assert list(upload_dir.iterdir()) == []


def test_accepts_png_by_signature(client: TestClient, upload_dir: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"rest of the image"

    response = _post_file(client, "image.png", png, "image/png")

    assert response.status_code == 201
    assert response.json()["filename"] == "image.png"


def test_accepts_docx_zip_signature(client: TestClient, upload_dir: Path) -> None:
    docx = b"PK\x03\x04" + b"zip container bytes"

    response = _post_file(
        client,
        "report.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "report.docx"
