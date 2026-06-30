"""Tests for upload validation — the security-relevant trust boundary."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

_PDF_BYTES = b"%PDF-1.4 minimal test document"


def _post_file(client: TestClient, name: str, content: bytes, content_type: str):
    return client.post("/api/uploads", files={"file": (name, content, content_type)})


def _docx_bytes(*, include_content_types: bool = True, include_word_entry: bool = True) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        if include_content_types:
            archive.writestr("[Content_Types].xml", "<Types />")
        if include_word_entry:
            archive.writestr("word/document.xml", "<document />")
    return buffer.getvalue()


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


def test_upload_returns_hash_detected_mime_and_original_artifact(
    client: TestClient, upload_dir: Path
) -> None:
    response = _post_file(client, "report.pdf", _PDF_BYTES, "application/octet-stream")

    assert response.status_code == 201
    body = response.json()
    expected_sha256 = hashlib.sha256(_PDF_BYTES).hexdigest()
    assert body["sha256"] == expected_sha256
    assert body["detected_mime_type"] == "application/pdf"

    artifact = body["original_artifact"]
    assert artifact == {
        "id": artifact["id"],
        "document_id": body["id"],
        "kind": "original",
        "storage_filename": f"{body['id']}.pdf",
        "sha256": expected_sha256,
        "mime_type": "application/pdf",
        "size_bytes": len(_PDF_BYTES),
        "created_at": artifact["created_at"],
    }
    assert len(artifact["id"]) == 32
    assert artifact["id"] != body["id"]
    assert artifact["created_at"]

    metadata = json.loads((upload_dir / f"{body['id']}.meta.json").read_text(encoding="utf-8"))
    assert metadata["sha256"] == expected_sha256
    assert metadata["detected_mime_type"] == "application/pdf"
    assert metadata["content_type"] == "application/pdf"
    assert metadata["original_artifact"] == artifact


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


def test_accepts_docx_with_plausible_ooxml_structure(client: TestClient) -> None:
    docx = _docx_bytes()

    response = _post_file(
        client,
        "report.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "report.docx"
    assert response.json()["detected_mime_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.parametrize(
    "docx",
    [
        b"PK\x03\x04not a valid zip archive",
        _docx_bytes(include_content_types=False),
        _docx_bytes(include_word_entry=False),
    ],
)
def test_rejects_docx_without_plausible_ooxml_structure(
    client: TestClient, upload_dir: Path, docx: bytes
) -> None:
    response = _post_file(
        client,
        "report.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert response.status_code == 415
    assert list(upload_dir.iterdir()) == []


def test_metadata_failure_rolls_back_finalized_file(
    client: TestClient, upload_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_save_metadata(*args: object, **kwargs: object) -> None:
        raise OSError("simulated metadata write failure")

    monkeypatch.setattr("app.services.upload_service.save_metadata", fail_save_metadata)

    with pytest.raises(OSError, match="simulated metadata write failure"):
        _post_file(client, "report.pdf", _PDF_BYTES, "application/pdf")

    assert list(upload_dir.iterdir()) == []
