"""Isolated OCR worker (ADR-0023 Phase 3, recovery per ADR-0041).

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
- The claim transaction is short; OCR runs *outside* any DB transaction, under a processing lease.

Recovery contract (ADR-0041):

- At startup the worker reclaims every worker-mode ``running`` job of its kind — with the enforced
  single-worker deployment any such row is provably an orphan of its own previous life — so a
  container restart deterministically requeues (attempts remaining) or explicitly fails
  (``interrupted``) interrupted work.
- Each poll cycle additionally recovers expired-lease rows, covering the case where a *different*
  process's claim was abandoned without a worker restart.
- Terminal transitions are fenced to the claiming attempt: a worker that lost its lease mid-run
  has its late result refused (``StaleJobClaimError``) instead of overwriting the recovered job,
  and its artifact publication is refused at the same fence (see ``artifact_lifecycle``).
"""

from __future__ import annotations

import logging
import os
import socket
import threading

from app.config import Settings
from app.services.job_models import JobKind, JobRecord, sanitize_job_error
from app.services.job_store import JobNotFoundError, JobStore, StaleJobClaimError
from app.services.ocr_adapters import OcrAdapter, get_ocr_adapter
from app.services.ocr_service import create_text_artifact
from app.services.pdf_renderer import PdfRenderer, get_pdf_renderer

logger = logging.getLogger("app.ocr_worker")


def worker_identity() -> str:
    """A short, non-sensitive identity for heartbeat rows (host + pid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


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
        lease_seconds: float = 3600.0,
    ) -> None:
        self._settings = settings
        self._store = store
        self._ocr_adapter = ocr_adapter
        self._pdf_renderer = pdf_renderer
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    def recover_on_startup(self) -> None:
        """Deterministically resolve work this worker's previous life left ``running``.

        Reclaims worker-mode ``running`` jobs of this kind regardless of lease age (the deployment
        enforces a single OCR worker, so any such row is an orphan): attempts remaining → requeued
        and processed again by this very loop; exhausted → explicit ``interrupted`` failure.
        """
        requeued, failed = self._store.recover_abandoned_jobs(
            kind=JobKind.OCR_TEXT,
            max_attempts=self._max_attempts,
            reclaim_active_worker_leases=True,
        )
        if requeued or failed:
            logger.warning(
                "ocr worker startup recovered abandoned jobs",
                extra={"requeued": requeued, "failed": failed},
            )

    def recover_abandoned(self) -> None:
        """Recover expired-lease rows during normal polling (idempotent, usually a no-op)."""
        requeued, failed = self._store.recover_abandoned_jobs(
            kind=JobKind.OCR_TEXT, max_attempts=self._max_attempts
        )
        if requeued or failed:
            logger.warning(
                "ocr worker recovered abandoned jobs",
                extra={"requeued": requeued, "failed": failed},
            )

    def process_next(self) -> bool:
        """Claim and run the next pending OCR job. Returns ``True`` if a job was processed.

        ``False`` means the queue was empty this cycle (the caller should sleep). A claimed job is
        always driven to a terminal ``succeeded``/``failed`` status — or explicitly refused when
        this worker's claim was lost to recovery mid-run. The original station exception is
        intentionally swallowed here (it is only used to derive a sanitized error) because there
        is no HTTP caller to re-raise it to — unlike the synchronous ``SyncJobRunner``.
        """
        self.recover_abandoned()
        record = self._store.claim_next_pending_job(
            JobKind.OCR_TEXT,
            max_attempts=self._max_attempts,
            lease_seconds=self._lease_seconds,
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
                authority_job_id=record.job_id,
                authority_claim_attempt=record.attempt_count,
            )
        except StaleJobClaimError:
            # This worker's lease expired and recovery already resolved the job; the late result
            # must not overwrite that resolution, and no artifact authority was published.
            logger.warning(
                "ocr job claim lost before publication; result discarded",
                extra={"job_id": record.job_id, "attempt": record.attempt_count},
            )
            return
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
            except StaleJobClaimError:
                logger.warning(
                    "ocr job claim lost; failure already resolved by recovery",
                    extra={"job_id": record.job_id, "attempt": record.attempt_count},
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
        except StaleJobClaimError:
            # The artifact was published, but the job was recovered mid-run: the published
            # authority cannot activate without this success, so reads stay explicit (409)
            # until the requeued attempt publishes a coherent run.
            logger.warning(
                "ocr job claim lost after publication; success not recorded",
                extra={"job_id": record.job_id, "attempt": record.attempt_count},
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


def run_heartbeat_loop(
    store: JobStore,
    *,
    interval_seconds: float,
    stop_event: threading.Event,
    worker_id: str,
) -> None:
    """Record a liveness heartbeat until shutdown, independent of in-flight OCR work.

    Runs in its own thread so a long-running OCR job never makes the worker look dead. A transient
    store error is logged and retried on the next tick; readiness treats a stale heartbeat as
    "worker processing unavailable" (see ``/api/health/ready``).
    """
    while not stop_event.is_set():
        try:
            store.record_worker_heartbeat(JobKind.OCR_TEXT, worker_id)
        except Exception:  # heartbeat must never kill the worker
            logger.exception("ocr worker heartbeat failed")
        stop_event.wait(interval_seconds)


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
        lease_seconds=settings.job_lease_seconds,
    )
