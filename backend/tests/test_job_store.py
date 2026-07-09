"""Tests for the SQLite-backed job metadata store (ADR-0023 Phase 2)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobStatus,
    sanitize_job_error,
)
from app.services.job_store import JobStore


def _context(
    *,
    job_id: str | None = None,
    document_id: str | None = None,
    kind: JobKind = JobKind.OCR_TEXT,
    created_at: str = "2026-07-08T10:00:00.000001Z",
    metadata: dict[str, str] | None = None,
) -> JobContext:
    return JobContext(
        job_id=job_id or uuid4().hex,
        document_id=document_id or uuid4().hex,
        kind=kind,
        execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
        created_at=created_at,
        metadata=metadata or {},
    )


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.sqlite3")


def test_schema_initializes_idempotently(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.initialize()
    store.initialize()

    assert (tmp_path / "jobs.sqlite3").is_file()


def test_create_and_get_job_roundtrips_enums_and_timestamps(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = JobRecord.from_context(
        _context(kind=JobKind.PII_DETECTION, metadata={"profile": "structured-only"})
    )

    store.create_job(record)

    loaded = store.get_job(record.job_id)
    assert loaded is not None
    assert loaded.job_id == record.job_id
    assert loaded.document_id == record.document_id
    assert loaded.kind is JobKind.PII_DETECTION
    assert loaded.status is JobStatus.PENDING
    assert loaded.execution_mode is JobExecutionMode.SYNCHRONOUS_INLINE
    assert loaded.created_at == "2026-07-08T10:00:00.000001Z"
    assert loaded.updated_at == loaded.created_at
    assert loaded.metadata == {"profile": "structured-only"}
    assert loaded.attempt_count == 0


def test_mark_running_and_succeeded_persists_result_reference(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = JobRecord.from_context(_context())
    store.create_job(record)

    record.mark_running()
    store.mark_running(record)
    record.mark_succeeded(artifact_id="a" * 32, artifact_type="text_result")
    store.mark_succeeded(record)

    loaded = store.get_job(record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.SUCCEEDED
    assert loaded.started_at is not None
    assert loaded.finished_at is not None
    assert loaded.updated_at == loaded.finished_at
    assert loaded.attempt_count == 1
    assert loaded.artifact_id == "a" * 32
    assert loaded.artifact_type == "text_result"
    assert loaded.error_code is None
    assert loaded.error_message is None


def test_mark_failed_persists_safe_error_metadata_only(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    record = JobRecord.from_context(_context())
    store.create_job(record)
    record.mark_running()
    store.mark_running(record)
    secret = "Patient Max Mustermann max@example.at AT611904300234573201"
    error_code, error_message = sanitize_job_error(RuntimeError(secret))

    record.mark_failed(error_code=error_code, error_message=error_message)
    store.mark_failed(record)

    loaded = store.get_job(record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.FAILED
    assert loaded.finished_at is not None
    assert loaded.artifact_id is None
    assert loaded.error_code == "internal_error"
    assert loaded.error_message == "Job execution failed unexpectedly."
    persisted_bytes = b"".join(
        path.read_bytes() for path in tmp_path.glob("jobs.sqlite3*") if path.is_file()
    )
    assert secret.encode() not in persisted_bytes
    assert b"Mustermann" not in persisted_bytes


def test_list_jobs_for_document_returns_newest_first_and_bounded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document_id = uuid4().hex
    older = JobRecord.from_context(
        _context(document_id=document_id, created_at="2026-07-08T10:00:00.000001Z")
    )
    newer = JobRecord.from_context(
        _context(document_id=document_id, created_at="2026-07-08T10:00:00.000002Z")
    )
    other = JobRecord.from_context(_context(created_at="2026-07-08T10:00:00.000003Z"))
    for record in (older, newer, other):
        store.create_job(record)

    jobs = store.list_jobs_for_document(document_id, limit=1)

    assert [job.job_id for job in jobs] == [newer.job_id]


def test_claim_next_pending_job_marks_running_and_returns_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = JobRecord.from_context(_context(kind=JobKind.OCR_TEXT))
    store.create_job(record)

    claimed = store.claim_next_pending_job(JobKind.OCR_TEXT)

    assert claimed is not None
    assert claimed.job_id == record.job_id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.started_at is not None
    assert claimed.attempt_count == 1
    # The transition is persisted, not only returned.
    reloaded = store.get_job(record.job_id)
    assert reloaded is not None
    assert reloaded.status is JobStatus.RUNNING


def test_claim_returns_none_when_no_pending_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.initialize()

    assert store.claim_next_pending_job(JobKind.OCR_TEXT) is None


def test_two_claims_do_not_both_run_the_same_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_job(JobRecord.from_context(_context(kind=JobKind.OCR_TEXT)))

    first = store.claim_next_pending_job(JobKind.OCR_TEXT)
    second = store.claim_next_pending_job(JobKind.OCR_TEXT)

    assert first is not None
    assert second is None


def test_claim_skips_jobs_of_a_different_kind(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pii_record = JobRecord.from_context(_context(kind=JobKind.PII_DETECTION))
    store.create_job(pii_record)

    claimed = store.claim_next_pending_job(JobKind.OCR_TEXT)

    assert claimed is None
    # The PII job stays pending — the OCR worker never touches it.
    reloaded = store.get_job(pii_record.job_id)
    assert reloaded is not None
    assert reloaded.status is JobStatus.PENDING


def test_claim_prefers_oldest_pending_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    older = JobRecord.from_context(
        _context(kind=JobKind.OCR_TEXT, created_at="2026-07-08T10:00:00.000001Z")
    )
    newer = JobRecord.from_context(
        _context(kind=JobKind.OCR_TEXT, created_at="2026-07-08T10:00:00.000002Z")
    )
    store.create_job(newer)
    store.create_job(older)

    claimed = store.claim_next_pending_job(JobKind.OCR_TEXT)

    assert claimed is not None
    assert claimed.job_id == older.job_id


def test_claim_respects_max_attempts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # A pending job whose single allowed attempt is already spent (e.g. a future requeue) must not
    # be reclaimed under max_attempts=1, but is claimable if the bound is raised.
    record = JobRecord.from_context(_context(kind=JobKind.OCR_TEXT))
    record.attempt_count = 1
    store.create_job(record)

    assert store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=1) is None

    claimed = store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=2)
    assert claimed is not None
    assert claimed.attempt_count == 2


def test_delete_jobs_for_document_removes_only_that_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document_id = uuid4().hex
    kept = JobRecord.from_context(_context())
    deleted = JobRecord.from_context(_context(document_id=document_id))
    store.create_job(kept)
    store.create_job(deleted)

    deleted_count = store.delete_jobs_for_document(document_id)

    assert deleted_count == 1
    assert store.get_job(deleted.job_id) is None
    assert store.get_job(kept.job_id) is not None
