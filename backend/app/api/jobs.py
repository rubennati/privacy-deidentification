"""Job status endpoints for durable OCR/PII job metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.schemas import ErrorResponse, JobStatusResponse
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.job_models import JobRecord, JobStatus
from app.services.job_store import JobNotFoundError, JobStore, get_job_store

router = APIRouter(tags=["jobs"])

_TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED})


def provide_job_store(settings: Settings = Depends(get_settings)) -> JobStore:
    """FastAPI dependency for the configured SQLite job store."""
    return get_job_store(settings)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def get_job_status(
    job_id: str,
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(provide_job_store),
) -> JobStatusResponse:
    """Return safe status metadata for one job.

    Observation recovers first (ADR-0041): an abandoned ``running`` row whose lease expired is
    requeued or explicitly failed before it is reported, so a poller can never watch a job stay
    ``running`` forever merely because its worker disappeared.
    """
    store.recover_abandoned_jobs(max_attempts=settings.ocr_worker_max_attempts)
    record = store.get_job(job_id)
    if record is None:
        raise JobNotFoundError()
    return to_job_status_response(record)


@router.get(
    "/documents/{document_id}/jobs",
    response_model=list[JobStatusResponse],
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def get_document_jobs(
    document_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(provide_job_store),
) -> list[JobStatusResponse]:
    """Return newest safe job metadata rows for one document (recovering abandoned rows first)."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError()
    store.recover_abandoned_jobs(max_attempts=settings.ocr_worker_max_attempts)
    records = store.list_jobs_for_document(document_id, limit=limit)
    return [to_job_status_response(record) for record in records]


def to_job_status_response(record: JobRecord) -> JobStatusResponse:
    """Map a safe ``JobRecord`` to its public status view (reused by the worker-mode OCR route)."""
    return JobStatusResponse(
        job_id=record.job_id,
        document_id=record.document_id,
        kind=record.kind.value,
        status=record.status.value,
        execution_mode=record.execution_mode.value,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        updated_at=record.updated_at or record.created_at,
        attempt_count=record.attempt_count,
        error_code=record.error_code,
        error_message=record.error_message,
        result_artifact_id=record.artifact_id,
        result_artifact_type=record.artifact_type,
        metadata=dict(record.metadata),
        is_terminal=record.status in _TERMINAL_STATUSES,
    )
