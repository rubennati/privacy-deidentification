"""Internal job model for OCR/PII execution (ADR-0023 Phase 1/2).

This is the smallest useful seam between "schedule work" and "do work". It lets the current
synchronous, in-process OCR/PII stations run *through* a job abstraction so a later phase can move
the same work behind a durable job store (SQLite) and isolated worker containers **without touching
the station code or the public API again**.

Phase 1 introduced the in-memory lifecycle. Phase 2 can persist the same safe record to SQLite via
``app.services.job_store`` while execution still stays synchronous/in-process. There is still no
queue, no worker, and no background task.

Privacy invariant: a ``JobRecord`` is the loggable/serializable part of a job and must never carry
raw document text, OCR text, or PII. Timestamps, ids, status, a coarse error *code*, and a
sanitized error *message* only. The live result artifact and any original exception travel in
``JobResult`` (in-process, transient) and are handled exactly as they are today — see
``app.services.job_runner``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from app.errors import ApiError


class JobKind(StrEnum):
    """What kind of work a job performs. Extend only when a real execution path exists."""

    OCR_TEXT = "ocr_text"
    PII_DETECTION = "pii_detection"


class JobStatus(StrEnum):
    """Lifecycle state of a job. ``canceled`` is defined for the future worker path; Phase 1's
    synchronous runner never produces it."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class JobExecutionMode(StrEnum):
    """How a job is executed. Current OCR/PII routes use ``synchronous_inline``; ``future_worker``
    names the target the abstraction is preparing for (ADR-0023 Phase 3+)."""

    SYNCHRONOUS_INLINE = "synchronous_inline"
    FUTURE_WORKER = "future_worker"


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class JobContext:
    """Immutable description of a unit of work to run.

    ``metadata`` is a small, non-sensitive key/value bag (e.g. profile name, source label). It must
    never contain raw document text, OCR text, or PII.
    """

    job_id: str
    document_id: str
    kind: JobKind
    execution_mode: JobExecutionMode
    created_at: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        kind: JobKind,
        document_id: str,
        execution_mode: JobExecutionMode,
        metadata: Mapping[str, str] | None = None,
    ) -> JobContext:
        """Build a pending-work context with a fresh id and creation timestamp."""
        return cls(
            job_id=uuid4().hex,
            document_id=document_id,
            kind=kind,
            execution_mode=execution_mode,
            created_at=_now_utc_iso(),
            metadata=dict(metadata or {}),
        )


@dataclass
class JobRecord:
    """Mutable lifecycle state for one job. Safe to log/serialize — carries no sensitive text.

    Created via :meth:`from_context` in ``pending`` state, then advanced through ``running`` and a
    terminal ``succeeded``/``failed``/``canceled`` state. ``artifact_id`` references an immutable
    artifact produced by the job; the artifact bytes themselves never enter this record.
    """

    job_id: str
    document_id: str
    kind: JobKind
    execution_mode: JobExecutionMode
    status: JobStatus
    created_at: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    attempt_count: int = 0
    artifact_id: str | None = None
    artifact_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_context(cls, context: JobContext) -> JobRecord:
        """Create a ``pending`` record mirroring a context's identity and metadata."""
        return cls(
            job_id=context.job_id,
            document_id=context.document_id,
            kind=context.kind,
            execution_mode=context.execution_mode,
            status=JobStatus.PENDING,
            created_at=context.created_at,
            updated_at=context.created_at,
            metadata=dict(context.metadata),
        )

    def mark_running(self) -> None:
        """Transition ``pending`` → ``running`` and count the attempt."""
        if self.status is not JobStatus.PENDING:
            raise ValueError(f"Cannot start a job in status {self.status}.")
        self.status = JobStatus.RUNNING
        self.started_at = _now_utc_iso()
        self.updated_at = self.started_at
        self.attempt_count += 1

    def mark_succeeded(
        self, *, artifact_id: str | None, artifact_type: str | None = None
    ) -> None:
        """Transition ``running`` → ``succeeded`` and record the produced artifact id."""
        if self.status is not JobStatus.RUNNING:
            raise ValueError(f"Cannot succeed a job in status {self.status}.")
        self.status = JobStatus.SUCCEEDED
        self.finished_at = _now_utc_iso()
        self.updated_at = self.finished_at
        self.artifact_id = artifact_id
        self.artifact_type = artifact_type

    def mark_failed(self, *, error_code: str, error_message: str) -> None:
        """Transition ``running`` → ``failed`` with a safe, non-sensitive error code and message."""
        if self.status is not JobStatus.RUNNING:
            raise ValueError(f"Cannot fail a job in status {self.status}.")
        self.status = JobStatus.FAILED
        self.finished_at = _now_utc_iso()
        self.updated_at = self.finished_at
        self.error_code = error_code
        self.error_message = error_message


@dataclass(frozen=True)
class JobResult[T]:
    """Outcome of a job run. Success carries the produced ``artifact``; failure carries the original
    ``error`` so the caller can re-raise it and preserve exact API behavior.

    The ``error`` is a live in-process exception and may contain sensitive detail in its args; it is
    only ever re-raised, never logged or copied into the (safe) ``JobRecord``.
    """

    record: JobRecord
    artifact: T | None = None
    error: Exception | None = None

    @property
    def status(self) -> JobStatus:
        return self.record.status

    @property
    def succeeded(self) -> bool:
        return self.record.status is JobStatus.SUCCEEDED

    def unwrap(self) -> T:
        """Return the produced artifact, or re-raise the original failure exception unchanged."""
        if self.error is not None:
            raise self.error
        if self.artifact is None:
            raise RuntimeError("Job result has neither an artifact nor an error.")
        return self.artifact


def sanitize_job_error(exc: Exception) -> tuple[str, str]:
    """Reduce an exception to a safe (error_code, error_message) pair for a ``JobRecord``.

    ``ApiError`` details are already curated, static, non-sensitive strings, so they pass through
    with a status-derived code. Any other exception is collapsed to a generic message so that raw
    exception text — which may echo document content or PII — never reaches job metadata or logs.
    """
    if isinstance(exc, ApiError):
        return (f"api_error_{exc.status_code}", exc.detail)
    return ("internal_error", "Job execution failed unexpectedly.")
