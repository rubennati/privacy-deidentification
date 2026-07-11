"""Synchronous, in-process job runner (ADR-0023 Phase 1/2).

``SyncJobRunner`` wraps an existing station call (``create_text_artifact`` /
``create_pii_artifact``) in the job lifecycle without changing what the station does or how its
result and exceptions reach the API. It is the inline implementation of the seam a future worker
will fill: same ``JobContext`` in, same ``JobResult`` out, but the work runs here in the request
thread rather than in an isolated worker process. In Phase 2 the FastAPI dependency attaches a
SQLite job store so this same inline lifecycle is persisted as safe metadata.

Behavior contract for Phase 2:

- Success returns a ``JobResult`` whose ``artifact`` is exactly the station's return value.
- Failure returns a ``JobResult`` carrying the original exception; the endpoint calls
  ``result.unwrap()`` to re-raise it, so API status codes and error details are byte-for-byte what
  they are today.
- The ``JobRecord`` captures only a sanitized error code/message — never the raw exception text —
  so nothing sensitive can leak into job metadata, the SQLite store, or logs.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress

from fastapi import Depends

from app.config import Settings, get_settings
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobRecord,
    JobResult,
    sanitize_job_error,
)
from app.services.job_store import JobNotFoundError, JobStore, get_job_store


class SyncJobRunner:
    """Run a job's operation inline in the current thread."""

    execution_mode = JobExecutionMode.SYNCHRONOUS_INLINE

    def __init__(self, store: JobStore | None = None) -> None:
        self._store = store

    def run[T](self, context: JobContext, operation: Callable[[], T]) -> JobResult[T]:
        """Execute ``operation`` under ``context``, recording lifecycle and a safe outcome.

        Never swallows failures: the original exception is captured in the returned ``JobResult``
        for the caller to re-raise, preserving the existing synchronous fail-loud behavior. The
        broad ``except`` is intentional — every failure must be recorded and then re-raised.
        """
        record = JobRecord.from_context(context)
        if self._store is not None:
            self._store.create_job(record)
        record.mark_running()
        if self._store is not None:
            self._store.mark_running(record)
        try:
            artifact = operation()
        except Exception as exc:
            error_code, error_message = sanitize_job_error(exc)
            record.mark_failed(error_code=error_code, error_message=error_message)
            if self._store is not None:
                # Deletion terminally removes jobs while a station may still be unwinding.
                with suppress(JobNotFoundError):
                    self._store.mark_failed(record)
            return JobResult(record=record, error=exc)
        record.mark_succeeded(
            artifact_id=getattr(artifact, "id", None),
            artifact_type=getattr(artifact, "artifact_type", None),
        )
        if self._store is not None:
            # Deletion may win after publication; it also removes the published files.
            with suppress(JobNotFoundError):
                self._store.mark_succeeded(record)
        return JobResult(record=record, artifact=artifact)


def get_job_runner(settings: Settings | None = None) -> SyncJobRunner:
    """Build the synchronous runner.

    When FastAPI passes request settings, Phase 2 binds the runner to the SQLite job store. A direct
    call remains usable for unit tests and small in-process callers.
    """
    return SyncJobRunner(get_job_store(settings)) if settings is not None else SyncJobRunner()


def provide_job_runner(settings: Settings = Depends(get_settings)) -> SyncJobRunner:
    """FastAPI dependency for the configured synchronous runner."""
    return get_job_runner(settings)
