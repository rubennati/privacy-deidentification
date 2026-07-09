"""Tests for the isolated OCR worker (ADR-0023 Phase 3).

The worker executes the same synchronous ``create_text_artifact`` station out-of-process against
pending SQLite jobs. These tests drive ``OcrJobWorker.process_next`` directly with a real store and
a DOCX document (which never invokes the OCR runtime), so no PaddleOCR dependency is required. All
fixtures are synthetic — no private corpus text is used.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobStatus,
)
from app.services.job_store import JobStore, get_job_store
from app.services.ocr_worker import OcrJobWorker


class _UnusedOcrAdapter:
    """OCR adapter that fails loudly if the worker ever calls it for a text/DOCX document."""

    def extract_text(self, image_path: Path) -> str:  # pragma: no cover - must not run
        raise AssertionError("OCR adapter must not be used for a DOCX/text document")

    def tool_versions(self) -> dict[str, str]:  # pragma: no cover - not reached
        return {}


class _UnusedPdfRenderer:
    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        raise AssertionError("PDF renderer must not be used for a DOCX document")


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def _allow_larger_uploads(settings: Settings) -> None:
    """DOCX fixtures exceed the tiny default upload limit used by the shared settings fixture."""
    settings.max_upload_bytes = 2 * 1024 * 1024


def _docx_bytes(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, name: str, content: bytes, content_type: str) -> str:
    response = client.post("/api/uploads", files={"file": (name, content, content_type)})
    assert response.status_code == 201
    return str(response.json()["id"])


def _upload_and_audit(client: TestClient, name: str, content: bytes, content_type: str) -> str:
    document_id = _upload(client, name, content, content_type)
    audit = client.post(f"/api/documents/{document_id}/audit")
    assert audit.status_code == 201
    return document_id


def _pending_ocr_job(store: JobStore, document_id: str) -> JobRecord:
    record = JobRecord.from_context(
        JobContext.create(
            kind=JobKind.OCR_TEXT,
            document_id=document_id,
            execution_mode=JobExecutionMode.FUTURE_WORKER,
        )
    )
    store.create_job(record)
    return record


def _worker(settings: Settings, store: JobStore) -> OcrJobWorker:
    return OcrJobWorker(
        settings,
        store,
        _UnusedOcrAdapter(),
        _UnusedPdfRenderer(),
        max_attempts=settings.ocr_worker_max_attempts,
    )


def test_process_next_returns_false_when_no_pending_job(
    client: TestClient, settings: Settings
) -> None:
    store = get_job_store(settings)
    store.initialize()

    assert _worker(settings, store).process_next() is False


def test_worker_runs_pending_job_and_marks_succeeded(
    client: TestClient, settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_and_audit(
        client, "document.docx", _docx_bytes("First", "Second"), _DOCX_MIME
    )
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)

    processed = _worker(settings, store).process_next()

    assert processed is True
    loaded = store.get_job(record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.SUCCEEDED
    assert loaded.artifact_type == "text_result"
    assert loaded.artifact_id is not None
    assert loaded.attempt_count == 1
    # The worker produced a real, readable text artifact via the API's own read path.
    ocr = client.get(f"/api/documents/{document_id}/ocr")
    assert ocr.status_code == 200
    assert ocr.json()["id"] == loaded.artifact_id
    assert ocr.json()["content"]["text"] == "First\nSecond"


def test_worker_marks_failed_with_sanitized_error_when_audit_missing(
    client: TestClient, settings: Settings, document_data_dir: Path
) -> None:
    # Uploaded but never audited: create_text_artifact raises a curated 409 ApiError.
    document_id = _upload(client, "document.docx", _docx_bytes("Only upload"), _DOCX_MIME)
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)

    processed = _worker(settings, store).process_next()

    assert processed is True
    loaded = store.get_job(record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.FAILED
    assert loaded.error_code == "api_error_409"
    assert loaded.error_message == "Document has no valid audit result."
    # A failed OCR job never fabricates a produced artifact.
    assert loaded.artifact_id is None
    # No text_result artifact was written for the document.
    artifacts = list((document_data_dir / document_id / "artifacts").glob("*.json"))
    types = {
        json.loads(path.read_text(encoding="utf-8")).get("artifact_type") for path in artifacts
    }
    assert "text_result" not in types


def test_worker_skips_pii_jobs(client: TestClient, settings: Settings) -> None:
    document_id = _upload(client, "document.docx", _docx_bytes("PII"), _DOCX_MIME)
    store = get_job_store(settings)
    pii_record = JobRecord.from_context(
        JobContext.create(
            kind=JobKind.PII_DETECTION,
            document_id=document_id,
            execution_mode=JobExecutionMode.FUTURE_WORKER,
        )
    )
    store.create_job(pii_record)

    assert _worker(settings, store).process_next() is False
    remaining = store.get_job(pii_record.job_id)
    assert remaining is not None
    assert remaining.status is JobStatus.PENDING


def test_worker_job_metadata_never_contains_document_text(
    client: TestClient, settings: Settings
) -> None:
    secret = "Kennwort Geheimnis Vertraulich"
    document_id = _upload_and_audit(client, "document.docx", _docx_bytes(secret), _DOCX_MIME)
    store = get_job_store(settings)
    _pending_ocr_job(store, document_id)

    assert _worker(settings, store).process_next() is True

    db_bytes = b"".join(
        path.read_bytes()
        for path in settings.resolved_job_store_db_path.parent.glob("jobs.sqlite3*")
        if path.is_file()
    )
    assert secret.encode() not in db_bytes
    assert b"Geheimnis" not in db_bytes


def test_two_workers_do_not_both_process_the_same_job(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_and_audit(client, "document.docx", _docx_bytes("Shared"), _DOCX_MIME)
    store = get_job_store(settings)
    _pending_ocr_job(store, document_id)

    first = _worker(settings, store)
    second = _worker(settings, store)

    assert first.process_next() is True
    # The single job is already claimed/terminal, so a second worker finds nothing to do.
    assert second.process_next() is False
