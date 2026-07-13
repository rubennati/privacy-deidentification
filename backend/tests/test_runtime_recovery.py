"""Runtime recovery and compatibility integrity (ADR-0041).

All data is synthetic. This suite reproduces the audited failure modes and proves the corrected
product behavior:

- a claimed job whose worker disappears is deterministically requeued (attempts remaining) or
  explicitly failed (``interrupted``) — at worker restart, during polling, and lazily when the job
  is observed through the status API;
- a live claim is never stolen, retries never produce conflicting or duplicated successful
  results (terminal transitions and artifact publication are fenced to the claiming attempt);
- synchronous inline rows recover only by lease expiry and only to an explicit failure;
- readiness reflects storage, job-store compatibility, and worker liveness;
- an unsupported or foreign job database fails explicitly and is never stamped or overwritten,
  while the known legacy schema migrates preserving its rows.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.artifact_lifecycle import publish_artifact_files
from app.services.job_models import (
    JobContext,
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobStatus,
)
from app.services.job_store import (
    INTERRUPTED_ERROR_CODE,
    JobStore,
    JobStoreIncompatibleError,
    StaleJobClaimError,
    get_job_store,
)
from app.services.ocr_worker import OcrJobWorker

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _UnusedOcrAdapter:
    def extract_text(self, image_path: Path) -> str:  # pragma: no cover - must not run
        raise AssertionError("OCR adapter must not be used for a DOCX/text document")

    def tool_versions(self) -> dict[str, str]:  # pragma: no cover - not reached
        return {}


class _UnusedPdfRenderer:
    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        raise AssertionError("PDF renderer must not be used for a DOCX document")


@pytest.fixture(autouse=True)
def _allow_larger_uploads(settings: Settings) -> None:
    settings.max_upload_bytes = 2 * 1024 * 1024


def _docx_bytes(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload_and_audit(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/uploads", files={"file": ("document.docx", content, _DOCX_MIME)}
    )
    assert response.status_code == 201
    document_id = str(response.json()["id"])
    assert client.post(f"/api/documents/{document_id}/audit").status_code == 201
    return document_id


def _pending_ocr_job(store: JobStore, document_id: str) -> JobRecord:
    record = JobRecord.from_context(
        JobContext.create(
            kind=JobKind.OCR_TEXT,
            document_id=document_id,
            execution_mode=JobExecutionMode.FUTURE_WORKER,
        )
    )
    store.create_job(record)
    return record


def _worker(settings: Settings, store: JobStore, *, max_attempts: int = 2) -> OcrJobWorker:
    return OcrJobWorker(
        settings,
        store,
        _UnusedOcrAdapter(),
        _UnusedPdfRenderer(),
        max_attempts=max_attempts,
        lease_seconds=3600.0,
    )


def _get(store: JobStore, job_id: str) -> JobRecord:
    record = store.get_job(job_id)
    assert record is not None
    return record


# --- Interruption, restart, and retry ------------------------------------------------------------


def test_worker_restart_requeues_interrupted_job_and_retry_succeeds(
    client: TestClient, settings: Settings
) -> None:
    """A job claimed by a worker that dies mid-run is requeued at the next worker startup and the
    retry produces exactly one successful result — ordinary processing works after recovery."""
    document_id = _upload_and_audit(client, _docx_bytes("Erster Absatz", "Zweiter Absatz"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)

    # First worker claims the job, then its process disappears before any terminal transition.
    claimed = store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=2)
    assert claimed is not None and claimed.job_id == record.job_id
    assert _get(store, record.job_id).status is JobStatus.RUNNING

    # A restarted worker deterministically reclaims its own orphan, then processes it.
    restarted = _worker(settings, store)
    restarted.recover_on_startup()
    requeued = _get(store, record.job_id)
    assert requeued.status is JobStatus.PENDING
    assert requeued.attempt_count == 1  # the interrupted attempt stays counted

    assert restarted.process_next() is True
    finished = _get(store, record.job_id)
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.attempt_count == 2
    assert finished.artifact_id is not None
    # Exactly one durable success claims the produced artifact — no duplicated results.
    successes = store.list_succeeded_jobs_for_artifact(
        document_id, finished.artifact_id, "text_result"
    )
    assert len(successes) == 1
    ocr = client.get(f"/api/documents/{document_id}/ocr")
    assert ocr.status_code == 200
    assert ocr.json()["id"] == finished.artifact_id


def test_worker_restart_fails_exhausted_job_explicitly(
    client: TestClient, settings: Settings
) -> None:
    """With the retry budget spent, restart recovery ends in an explicit terminal failure."""
    document_id = _upload_and_audit(client, _docx_bytes("Inhalt"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    assert store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=1) is not None

    worker = _worker(settings, store, max_attempts=1)
    worker.recover_on_startup()

    failed = _get(store, record.job_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error_code == INTERRUPTED_ERROR_CODE
    assert failed.artifact_id is None
    # The status API reports the explicit terminal state to any poller.
    response = client.get(f"/api/jobs/{record.job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["is_terminal"] is True
    assert response.json()["error_code"] == INTERRUPTED_ERROR_CODE


def test_expired_lease_is_recovered_when_the_job_is_observed(
    client: TestClient, settings: Settings
) -> None:
    """Without any worker restart, merely polling the job recovers an expired-lease claim — a job
    can never stay ``running`` forever just because its worker disappeared."""
    document_id = _upload_and_audit(client, _docx_bytes("Beobachtung"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    assert (
        store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=2, lease_seconds=0.0)
        is not None
    )
    assert _get(store, record.job_id).status is JobStatus.RUNNING

    response = client.get(f"/api/jobs/{record.job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"  # requeued: one attempt remains
    assert response.json()["attempt_count"] == 1


def test_active_lease_is_never_reclaimed_by_polling_recovery(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_and_audit(client, _docx_bytes("Aktiv"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    assert store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=2) is not None

    requeued, failed = store.recover_abandoned_jobs(max_attempts=2)

    assert (requeued, failed) == (0, 0)
    assert _get(store, record.job_id).status is JobStatus.RUNNING


def test_sync_inline_row_recovers_only_by_lease_expiry_and_only_to_failure(
    client: TestClient, settings: Settings
) -> None:
    """A synchronous inline run is owned by a live API request until its lease runs out; nothing
    can ever re-run it, so recovery is an explicit failure — never a requeue."""
    document_id = _upload_and_audit(client, _docx_bytes("Synchron"))
    store = get_job_store(settings)
    active = JobRecord.from_context(
        JobContext.create(
            kind=JobKind.PII_DETECTION,
            document_id=document_id,
            execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
        )
    )
    store.create_job(active)
    active.mark_running()
    store.mark_running(active, lease_seconds=3600.0)
    interrupted = JobRecord.from_context(
        JobContext.create(
            kind=JobKind.PII_DETECTION,
            document_id=document_id,
            execution_mode=JobExecutionMode.SYNCHRONOUS_INLINE,
        )
    )
    store.create_job(interrupted)
    interrupted.mark_running()
    store.mark_running(interrupted, lease_seconds=0.0)

    requeued, failed = store.recover_abandoned_jobs(max_attempts=5)

    assert (requeued, failed) == (0, 1)
    assert _get(store, active.job_id).status is JobStatus.RUNNING
    recovered = _get(store, interrupted.job_id)
    assert recovered.status is JobStatus.FAILED
    assert recovered.error_code == INTERRUPTED_ERROR_CODE


# --- Claim fencing: retries never conflict or duplicate ------------------------------------------


def test_lost_claim_cannot_overwrite_the_recovered_job(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_and_audit(client, _docx_bytes("Zaun"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    stale = store.claim_next_pending_job(
        JobKind.OCR_TEXT, max_attempts=2, lease_seconds=0.0
    )
    assert stale is not None
    store.recover_abandoned_jobs(max_attempts=2)
    assert _get(store, record.job_id).status is JobStatus.PENDING

    stale.mark_succeeded(artifact_id="a" * 32, artifact_type="text_result")
    with pytest.raises(StaleJobClaimError):
        store.mark_succeeded(stale)

    survivor = _get(store, record.job_id)
    assert survivor.status is JobStatus.PENDING
    assert survivor.artifact_id is None


def test_lost_claim_cannot_publish_artifact_authority(
    client: TestClient, settings: Settings, document_data_dir: Path
) -> None:
    """A worker whose claim was recovered must not even publish artifact files/authority."""
    document_id = _upload_and_audit(client, _docx_bytes("Autorität"))
    store = get_job_store(settings)
    _pending_ocr_job(store, document_id)
    stale = store.claim_next_pending_job(
        JobKind.OCR_TEXT, max_attempts=2, lease_seconds=0.0
    )
    assert stale is not None
    store.recover_abandoned_jobs(max_attempts=2)

    with pytest.raises(StaleJobClaimError):
        publish_artifact_files(
            settings,
            document_id,
            {"text_result": ("b" * 32, "{}")},
            authority_job_id=stale.job_id,
            authority_job_result=("b" * 32, "text_result"),
            authority_claim_attempt=stale.attempt_count,
        )

    assert not (document_data_dir / document_id / "artifacts" / ("b" * 32 + ".json")).exists()


def test_stale_worker_result_is_discarded_while_retry_succeeds(
    client: TestClient, settings: Settings
) -> None:
    """End to end through the real worker: a lost claim's late outcome is refused, the retry runs,
    and the document ends with exactly one coherent, readable OCR result."""
    document_id = _upload_and_audit(client, _docx_bytes("Ein Ergebnis"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    stale = store.claim_next_pending_job(
        JobKind.OCR_TEXT, max_attempts=2, lease_seconds=0.0
    )
    assert stale is not None

    worker = _worker(settings, store)
    assert worker.process_next() is True  # recovers the expired claim, then runs the retry

    finished = _get(store, record.job_id)
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.attempt_count == 2

    # The stale first claim reports its late failure; the fenced store refuses it quietly inside
    # the worker path — simulate the direct store write to prove the fence.
    stale.mark_failed(error_code="api_error_409", error_message="late")
    with pytest.raises(StaleJobClaimError):
        store.mark_failed(stale)
    assert _get(store, record.job_id).status is JobStatus.SUCCEEDED
    ocr = client.get(f"/api/documents/{document_id}/ocr")
    assert ocr.status_code == 200


def test_enqueue_recovers_abandoned_rows_first(
    client: TestClient, settings: Settings
) -> None:
    """Submitting new work in worker mode resolves a dead worker's leftovers up front."""
    document_id = _upload_and_audit(client, _docx_bytes("Warteschlange"))
    store = get_job_store(settings)
    record = _pending_ocr_job(store, document_id)
    assert (
        store.claim_next_pending_job(JobKind.OCR_TEXT, max_attempts=1, lease_seconds=0.0)
        is not None
    )
    settings.ocr_execution_mode = "worker"
    settings.ocr_worker_max_attempts = 1

    response = client.post(f"/api/documents/{document_id}/ocr")

    assert response.status_code == 202
    abandoned = _get(store, record.job_id)
    assert abandoned.status is JobStatus.FAILED
    assert abandoned.error_code == INTERRUPTED_ERROR_CODE


# --- Readiness ------------------------------------------------------------------------------------


def test_readiness_reflects_worker_liveness_in_worker_mode(
    client: TestClient, settings: Settings
) -> None:
    settings.ocr_execution_mode = "worker"
    store = get_job_store(settings)
    store.initialize()

    # No worker has ever sent a heartbeat: queued OCR work would never be processed.
    unknown = client.get("/api/health/ready")
    assert unknown.status_code == 503
    assert unknown.json()["components"]["ocr_worker"] == "unknown"

    store.record_worker_heartbeat(JobKind.OCR_TEXT, "test-host:1")
    alive = client.get("/api/health/ready")
    assert alive.status_code == 200
    assert alive.json()["components"]["ocr_worker"] == "ok"

    # A heartbeat far older than the staleness bound means the worker process is gone.
    stale_at = (
        (datetime.now(UTC) - timedelta(hours=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    with sqlite3.connect(settings.resolved_job_store_db_path) as connection:
        connection.execute(
            "UPDATE worker_status SET last_seen_at = ? WHERE kind = ?",
            (stale_at, JobKind.OCR_TEXT.value),
        )
    stale = client.get("/api/health/ready")
    assert stale.status_code == 503
    assert stale.json()["components"]["ocr_worker"] == "stale"


def test_readiness_reports_incompatible_job_store(
    client: TestClient, settings: Settings
) -> None:
    db_path = settings.resolved_job_store_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 99")

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["components"]["job_store"] == "incompatible"


# --- Database schema compatibility ----------------------------------------------------------------


def test_newer_schema_version_fails_explicitly_and_is_never_stamped(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 99")
        connection.execute("CREATE TABLE future_data (payload TEXT)")
        connection.execute("INSERT INTO future_data VALUES ('keep me')")

    with pytest.raises(JobStoreIncompatibleError):
        JobStore(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        preserved = connection.execute("SELECT payload FROM future_data").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert version == 99  # never stamped down to the supported version
    assert preserved == "keep me"
    assert "jobs" not in tables  # nothing was created inside the foreign file


def test_unversioned_file_with_existing_data_fails_explicitly(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY)")

    with pytest.raises(JobStoreIncompatibleError):
        JobStore(db_path).initialize()


_V1_JOBS_DDL = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    result_artifact_id TEXT,
    result_artifact_type TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
)
"""


def test_known_legacy_schema_migrates_preserving_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(_V1_JOBS_DDL)
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, document_id, kind, status, execution_mode,
                created_at, updated_at, attempt_count, metadata_json
            ) VALUES ('j1', 'd1', 'ocr_text', 'running', 'future_worker',
                      '2026-01-01T00:00:00.000000Z', '2026-01-01T00:00:00.000000Z', 1, '{}')
            """
        )
        connection.execute("PRAGMA user_version = 1")

    store = JobStore(db_path)
    migrated = store.get_job("j1")

    assert migrated is not None
    assert migrated.status is JobStatus.RUNNING
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert version == 2
    assert "lease_expires_at" in columns
    assert "worker_status" in tables

    # A pre-lease `running` row is an orphan by definition; recovery resolves it immediately.
    requeued, failed = store.recover_abandoned_jobs(max_attempts=2)
    assert (requeued, failed) == (1, 0)
    recovered = store.get_job("j1")
    assert recovered is not None
    assert recovered.status is JobStatus.PENDING
