"""Unit tests for the internal job abstraction (ADR-0023 Phase 1).

These cover the job model lifecycle, the synchronous runner's success/failure handling, and the
privacy invariant that raw exception text never reaches a job record. All data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import ApiError
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobResult,
    JobStatus,
    sanitize_job_error,
)
from app.services.job_runner import SyncJobRunner, get_job_runner
from app.services.job_store import JobStore


def _context(kind: JobKind = JobKind.OCR_TEXT) -> JobContext:
    return JobContext.create(
        kind=kind,
        document_id="doc-123",
        execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
    )


def test_context_create_populates_identity_and_defaults() -> None:
    context = _context(JobKind.PII_DETECTION)
    assert context.job_id
    assert context.document_id == "doc-123"
    assert context.kind is JobKind.PII_DETECTION
    assert context.execution_mode is JobExecutionMode.SYNCHRONOUS_INLINE
    assert context.created_at.endswith("Z")
    assert context.metadata == {}


def test_record_represents_pending_running_succeeded() -> None:
    record = JobRecord.from_context(_context())
    assert record.status is JobStatus.PENDING
    assert record.started_at is None
    assert record.attempt_count == 0

    record.mark_running()
    assert record.status is JobStatus.RUNNING
    assert record.started_at is not None
    assert record.attempt_count == 1

    record.mark_succeeded(artifact_id="artifact-abc")
    assert record.status is JobStatus.SUCCEEDED
    assert record.finished_at is not None
    assert record.artifact_id == "artifact-abc"
    assert record.error_code is None
    assert record.error_message is None


def test_record_represents_failed_with_safe_metadata() -> None:
    record = JobRecord.from_context(_context())
    record.mark_running()
    record.mark_failed(
        error_code="api_error_422",
        error_message="Text result could not be analyzed.",
    )
    assert record.status is JobStatus.FAILED
    assert record.finished_at is not None
    assert record.artifact_id is None
    assert record.error_code == "api_error_422"
    assert record.error_message == "Text result could not be analyzed."


def test_record_rejects_illegal_transitions() -> None:
    record = JobRecord.from_context(_context())
    with pytest.raises(ValueError):
        record.mark_succeeded(artifact_id=None)  # not running yet
    record.mark_running()
    with pytest.raises(ValueError):
        record.mark_running()  # already running


def test_sanitize_api_error_passes_curated_detail() -> None:
    code, message = sanitize_job_error(ApiError("Text result not found.", 404))
    assert code == "api_error_404"
    assert message == "Text result not found."


def test_sanitize_generic_error_hides_raw_text() -> None:
    sensitive = "Patient Erika Mustermann, IBAN AT61 1904 3002 3457 3201"
    code, message = sanitize_job_error(RuntimeError(sensitive))
    assert code == "internal_error"
    assert sensitive not in message
    assert "Mustermann" not in message
    assert message == "Job execution failed unexpectedly."


def test_runner_success_returns_artifact_and_record() -> None:
    runner = SyncJobRunner()

    class _Artifact:
        id = "artifact-xyz"

    artifact = _Artifact()
    context = _context()
    result = runner.run(context, lambda: artifact)

    assert isinstance(result, JobResult)
    assert result.succeeded
    assert result.status is JobStatus.SUCCEEDED
    assert result.artifact is artifact
    assert result.unwrap() is artifact
    assert result.record.job_id == context.job_id
    assert result.record.artifact_id == "artifact-xyz"
    assert result.record.attempt_count == 1


def test_runner_persists_succeeded_job_when_store_is_attached(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    runner = SyncJobRunner(store)

    class _Artifact:
        id = "a" * 32
        artifact_type = "text_result"

    result = runner.run(_context(), lambda: _Artifact())

    loaded = store.get_job(result.record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.SUCCEEDED
    assert loaded.artifact_id == "a" * 32
    assert loaded.artifact_type == "text_result"
    assert loaded.attempt_count == 1


def test_runner_captures_api_error_and_unwrap_reraises() -> None:
    runner = SyncJobRunner()
    raised = ApiError("Document has no valid text result.", 409)

    def _operation() -> object:
        raise raised

    result = runner.run(_context(JobKind.PII_DETECTION), _operation)

    assert not result.succeeded
    assert result.status is JobStatus.FAILED
    assert result.artifact is None
    assert result.record.error_code == "api_error_409"
    assert result.record.error_message == "Document has no valid text result."
    with pytest.raises(ApiError) as excinfo:
        result.unwrap()
    assert excinfo.value is raised


def test_runner_persists_failed_job_and_reraises_original_error(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    runner = SyncJobRunner(store)
    raised = ApiError("Document has no valid text result.", 409)

    def _operation() -> object:
        raise raised

    result = runner.run(_context(JobKind.PII_DETECTION), _operation)

    loaded = store.get_job(result.record.job_id)
    assert loaded is not None
    assert loaded.status is JobStatus.FAILED
    assert loaded.error_code == "api_error_409"
    assert loaded.error_message == "Document has no valid text result."
    assert loaded.artifact_id is None
    with pytest.raises(ApiError) as excinfo:
        result.unwrap()
    assert excinfo.value is raised


def test_runner_failure_record_never_stores_raw_exception_text() -> None:
    runner = SyncJobRunner()
    sensitive = "Max Mustermann max@example.com +43 660 1234567"

    def _operation() -> object:
        raise RuntimeError(sensitive)

    result = runner.run(_context(), _operation)

    assert result.status is JobStatus.FAILED
    assert result.record.error_code == "internal_error"
    assert result.record.error_message is not None
    assert sensitive not in result.record.error_message
    # The live exception is still available for the endpoint to re-raise unchanged.
    with pytest.raises(RuntimeError):
        result.unwrap()


def test_get_job_runner_returns_sync_runner() -> None:
    runner = get_job_runner()
    assert isinstance(runner, SyncJobRunner)
    assert runner.execution_mode is JobExecutionMode.SYNCHRONOUS_INLINE
