"""Isolated OCR worker (ADR-0023 Phase 3).

The worker is a DB-backed polling loop — **not** Redis/Celery/RQ. It claims pending ``ocr_text``
jobs from the SQLite job store, runs the existing synchronous ``create_text_artifact`` station in
its own process, and records the terminal job status. Moving this heavy work out of the FastAPI
process is the point: an OCR OOM/crash can no longer take the API down.

Design contract:

- One OCR job at a time (bounded concurrency; Phase 3 runs a single loop).
- Artifacts stay immutable files; only safe job metadata is written to SQLite, and the produced
  artifact is committed by the station at the *end* of a successful run, so a killed job leaves no
  partial artifact and is never marked ``succeeded``.
- Failures are sanitized (``sanitize_job_error``) before they touch job metadata or logs — raw
  document text, OCR text, and PII never leave the process.
- The claim transaction is short; OCR runs *outside* any DB transaction.
"""

from __future__ import annotations

import logging
import threading

from app.config import Settings
from app.services.job_models import JobKind, JobRecord, sanitize_job_error
from app.services.job_store import JobNotFoundError, JobStore
from app.services.ocr_adapters import OcrAdapter, get_ocr_adapter
from app.services.ocr_service import create_text_artifact
from app.services.pdf_renderer import PdfRenderer, get_pdf_renderer

logger = logging.getLogger("app.ocr_worker")


class OcrJobWorker:
    """Claim and execute one pending OCR job at a time against the shared job store."""

    def __init__(
        self,
        settings: Settings,
        store: JobStore,
        ocr_adapter: OcrAdapter,
        pdf_renderer: PdfRenderer,
        *,
        max_attempts: int = 1,
    ) -> None:
        self._settings = settings
        self._store = store
        self._ocr_adapter = ocr_adapter
        self._pdf_renderer = pdf_renderer
        self._max_attempts = max_attempts

    def process_next(self) -> bool:
        """Claim and run the next pending OCR job. Returns ``True`` if a job was processed.

        ``False`` means the queue was empty this cycle (the caller should sleep). A claimed job is
        always driven to a terminal ``succeeded``/``failed`` status; the original station exception
        is intentionally swallowed here (it is only used to derive a sanitized error) because there
        is no HTTP caller to re-raise it to — unlike the synchronous ``SyncJobRunner``.
        """
        record = self._store.claim_next_pending_job(
            JobKind.OCR_TEXT, max_attempts=self._max_attempts
        )
        if record is None:
            return False
        self._run_claimed_job(record)
        return True

    def _run_claimed_job(self, record: JobRecord) -> None:
        try:
            artifact = create_text_artifact(
                self._settings,
                record.document_id,
                self._ocr_adapter,
                self._pdf_renderer,
            )
        except Exception as exc:  # every failure is recorded and sanitized, never propagated
            error_code, error_message = sanitize_job_error(exc)
            record.mark_failed(error_code=error_code, error_message=error_message)
            try:
                self._store.mark_failed(record)
            except JobNotFoundError:
                logger.info(
                    "ocr job discarded after document deletion",
                    extra={"job_id": record.job_id},
                )
                return
            logger.warning(
                "ocr job failed",
                extra={"job_id": record.job_id, "error_code": error_code},
            )
            return
        record.mark_succeeded(
            artifact_id=getattr(artifact, "id", None),
            artifact_type=getattr(artifact, "artifact_type", None),
        )
        try:
            self._store.mark_succeeded(record)
        except JobNotFoundError:
            logger.info(
                "ocr job completion discarded after document deletion",
                extra={"job_id": record.job_id},
            )
            return
        logger.info(
            "ocr job succeeded",
            extra={"job_id": record.job_id, "artifact_type": record.artifact_type},
        )


def run_worker_loop(
    worker: OcrJobWorker,
    *,
    poll_interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    """Poll for OCR jobs until ``stop_event`` is set.

    Drains back-to-back jobs without sleeping, then waits ``poll_interval_seconds`` when the queue
    is empty. ``stop_event.wait`` returns early on shutdown so the loop exits promptly. A transient
    store error is logged and treated as an empty cycle rather than crashing the worker.
    """
    while not stop_event.is_set():
        try:
            processed = worker.process_next()
        except Exception:  # a polling worker must survive transient store errors
            logger.exception("ocr worker poll failed")
            processed = False
        if not processed:
            stop_event.wait(poll_interval_seconds)


def build_worker(settings: Settings, store: JobStore) -> OcrJobWorker:
    """Assemble a worker bound to the runtime OCR adapter and PDF renderer."""
    model_dir = str(settings.ocr_model_dir) if settings.ocr_model_dir is not None else None
    ocr_adapter = get_ocr_adapter(
        model_dir,
        settings.ocr_detection_model_name,
        settings.ocr_recognition_model_name,
    )
    return OcrJobWorker(
        settings,
        store,
        ocr_adapter,
        get_pdf_renderer(),
        max_attempts=settings.ocr_worker_max_attempts,
    )
