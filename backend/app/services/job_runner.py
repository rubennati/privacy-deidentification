"""Synchronous, in-process job runner (ADR-0023 Phase 1).

``SyncJobRunner`` wraps an existing station call (``create_text_artifact`` /
``create_pii_artifact``) in the job lifecycle without changing what the station does or how its
result and exceptions reach the API. It is the inline implementation of the seam a future worker
will fill: same ``JobContext`` in, same ``JobResult`` out, but the work runs here in the request
thread rather than in an isolated worker process.

Behavior contract for Phase 1:

- Success returns a ``JobResult`` whose ``artifact`` is exactly the station's return value.
- Failure returns a ``JobResult`` carrying the original exception; the endpoint calls
  ``result.unwrap()`` to re-raise it, so API status codes and error details are byte-for-byte what
  they are today.
- The ``JobRecord`` captures only a sanitized error code/message — never the raw exception text —
  so nothing sensitive can leak into job metadata or logs.
"""

from __future__ import annotations

from collections.abc import Callable

from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobRecord,
    JobResult,
    sanitize_job_error,
)


class SyncJobRunner:
    """Run a job's operation inline in the current thread."""

    execution_mode = JobExecutionMode.SYNCHRONOUS_INLINE

    def run[T](self, context: JobContext, operation: Callable[[], T]) -> JobResult[T]:
        """Execute ``operation`` under ``context``, recording lifecycle and a safe outcome.

        Never swallows failures: the original exception is captured in the returned ``JobResult``
        for the caller to re-raise, preserving the existing synchronous fail-loud behavior. The
        broad ``except`` is intentional — every failure must be recorded and then re-raised.
        """
        record = JobRecord.from_context(context)
        record.mark_running()
        try:
            artifact = operation()
        except Exception as exc:
            error_code, error_message = sanitize_job_error(exc)
            record.mark_failed(error_code=error_code, error_message=error_message)
            return JobResult(record=record, error=exc)
        record.mark_succeeded(artifact_id=getattr(artifact, "id", None))
        return JobResult(record=record, artifact=artifact)


def get_job_runner() -> SyncJobRunner:
    """FastAPI dependency: the process-wide synchronous runner.

    A single indirection point so a later phase can bind a worker-backed runner here without
    touching the endpoints.
    """
    return SyncJobRunner()
