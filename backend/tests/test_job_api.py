"""API tests for durable job status metadata."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
)
from app.services.job_store import get_job_store

_PDF_BYTES = b"%PDF-1.4 minimal test document"


def _upload_document(client: TestClient) -> str:
    response = client.post(
        "/api/uploads",
        files={"file": ("source.pdf", _PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _record(
    document_id: str,
    *,
    created_at: str = "2026-07-08T10:00:00.000001Z",
) -> JobRecord:
    return JobRecord.from_context(
        JobContext(
            job_id=uuid4().hex,
            document_id=document_id,
            kind=JobKind.OCR_TEXT,
            execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
            created_at=created_at,
            metadata={"source": "synthetic"},
        )
    )


def test_job_status_endpoint_returns_safe_metadata(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    store = get_job_store(settings)
    record = _record(document_id)
    store.create_job(record)
    record.mark_running()
    store.mark_running(record)
    record.mark_succeeded(artifact_id="a" * 32, artifact_type="text_result")
    store.mark_succeeded(record)

    response = client.get(f"/api/jobs/{record.job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "job_id": record.job_id,
        "document_id": document_id,
        "kind": "ocr_text",
        "status": "succeeded",
        "execution_mode": "synchronous_inline",
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "updated_at": record.updated_at,
        "attempt_count": 1,
        "error_code": None,
        "error_message": None,
        "result_artifact_id": "a" * 32,
        "result_artifact_type": "text_result",
        "metadata": {"source": "synthetic"},
        "is_terminal": True,
    }
    assert "text" not in body


def test_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get("/api/jobs/" + "a" * 32)

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


def test_pending_job_status_reports_not_terminal(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    store = get_job_store(settings)
    record = _record(document_id)
    store.create_job(record)

    response = client.get(f"/api/jobs/{record.job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["is_terminal"] is False


def test_failed_job_status_reports_terminal_with_controlled_error(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    store = get_job_store(settings)
    record = _record(document_id)
    store.create_job(record)
    record.mark_running()
    store.mark_running(record)
    record.mark_failed(
        error_code="internal_error",
        error_message="Job execution failed unexpectedly.",
    )
    store.mark_failed(record)

    response = client.get(f"/api/jobs/{record.job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["is_terminal"] is True
    assert body["error_code"] == "internal_error"
    assert body["error_message"] == "Job execution failed unexpectedly."
    assert body["result_artifact_id"] is None


def test_document_jobs_endpoint_returns_newest_jobs(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    store = get_job_store(settings)
    older = _record(document_id, created_at="2026-07-08T10:00:00.000001Z")
    newer = _record(document_id, created_at="2026-07-08T10:00:00.000002Z")
    for record in (older, newer):
        store.create_job(record)

    response = client.get(f"/api/documents/{document_id}/jobs")

    assert response.status_code == 200
    assert [job["job_id"] for job in response.json()] == [newer.job_id, older.job_id]


def test_document_jobs_unknown_document_returns_404(client: TestClient) -> None:
    response = client.get("/api/documents/" + "a" * 32 + "/jobs")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_document_delete_removes_job_metadata(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    store = get_job_store(settings)
    record = _record(document_id)
    store.create_job(record)

    delete_response = client.delete(f"/api/documents/{document_id}")
    job_response = client.get(f"/api/jobs/{record.job_id}")

    assert delete_response.status_code == 204
    assert job_response.status_code == 404
