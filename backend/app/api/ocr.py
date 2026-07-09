"""Synchronous OCR/Text Workstation v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.jobs import to_job_status_response
from app.config import Settings, get_settings
from app.schemas import ErrorResponse, JobStatusResponse, TextArtifact
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
)
from app.services.job_runner import SyncJobRunner, provide_job_runner
from app.services.job_store import JobStore, get_job_store
from app.services.ocr_adapters import OcrAdapter, get_ocr_adapter
from app.services.ocr_service import create_text_artifact, get_latest_text
from app.services.pdf_renderer import PdfRenderer, get_pdf_renderer

router = APIRouter(prefix="/documents", tags=["ocr"])
_JOB_ID_HEADER = "X-Job-Id"


def provide_ocr_adapter(settings: Settings = Depends(get_settings)) -> OcrAdapter:
    """Bind the runtime's explicitly configured local model directory and names to the adapter."""
    model_dir = str(settings.ocr_model_dir) if settings.ocr_model_dir is not None else None
    return get_ocr_adapter(
        model_dir,
        settings.ocr_detection_model_name,
        settings.ocr_recognition_model_name,
    )


@router.post(
    "/{document_id}/ocr",
    response_model=TextArtifact,
    status_code=status.HTTP_201_CREATED,
    responses={
        202: {"model": JobStatusResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def ocr_document(
    document_id: str,
    response: Response,
    settings: Settings = Depends(get_settings),
    ocr_adapter: OcrAdapter = Depends(provide_ocr_adapter),
    pdf_renderer: PdfRenderer = Depends(get_pdf_renderer),
    runner: SyncJobRunner = Depends(provide_job_runner),
) -> TextArtifact | Response:
    """Extract text according to the latest audit and persist an immutable result.

    Behavior depends on ``OCR_EXECUTION_MODE`` (ADR-0023 Phase 3.6):

    - ``worker`` (default): a pending OCR job is enqueued in the shared SQLite store and ``202`` is
      returned with the job's safe status metadata; the isolated ``ocr-worker`` process claims and
      runs it. Clients poll ``GET /api/jobs/{job_id}`` for progress and read the artifact via
      ``GET /api/documents/{document_id}/ocr`` once the job succeeds.
    - ``sync``: extraction runs inline through the in-process job runner and the immutable
      ``text_result`` artifact is returned with ``201``. This remains a development/test fallback.

    Both modes set the ``X-Job-Id`` header.
    """
    if settings.ocr_execution_mode == "worker":
        return _enqueue_ocr_job(settings, document_id)

    context = JobContext.create(
        kind=JobKind.OCR_TEXT,
        document_id=document_id,
        execution_mode=runner.execution_mode,
    )
    result = runner.run(
        context,
        lambda: create_text_artifact(settings, document_id, ocr_adapter, pdf_renderer),
    )
    response.headers[_JOB_ID_HEADER] = result.record.job_id
    return result.unwrap()


def _enqueue_ocr_job(settings: Settings, document_id: str) -> JSONResponse:
    """Create a pending worker OCR job and return its safe status with ``202``.

    The API stays thin: it confirms the document exists (clean ``404``) and persists a pending job,
    but never touches the OCR runtime — the deeper input checks (audit present, integrity) run in
    the worker, which records a sanitized failure if they do not hold, so a missing worker simply
    leaves the job ``pending`` rather than failing the request.
    """
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError()
    context = JobContext.create(
        kind=JobKind.OCR_TEXT,
        document_id=document_id,
        execution_mode=JobExecutionMode.FUTURE_WORKER,
    )
    record = JobRecord.from_context(context)
    store: JobStore = get_job_store(settings)
    store.create_job(record)
    status_response = to_job_status_response(record)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=status_response.model_dump(),
        headers={_JOB_ID_HEADER: record.job_id},
    )


@router.get(
    "/{document_id}/ocr",
    response_model=TextArtifact,
    responses={404: {"model": ErrorResponse}},
)
def get_document_ocr(
    document_id: str, settings: Settings = Depends(get_settings)
) -> TextArtifact:
    """Return the newest text result for a document."""
    return get_latest_text(settings, document_id)
