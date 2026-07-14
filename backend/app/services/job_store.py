"""SQLite-backed job metadata store (ADR-0023 Phase 2, recovery/compatibility per ADR-0041).

The store is deliberately small: artifacts remain immutable JSON files, while SQLite records only
job lifecycle metadata that is safe to expose through a status API. Do not add raw OCR text,
canonical reading text, PII values, artifact payloads, stack traces, or copied document snippets.

Recovery model (ADR-0041): every ``running`` row carries a ``lease_expires_at`` deadline set when
the row was claimed/started. A row whose lease expired — or that predates leases entirely — is
*abandoned*: its process died or lost the claim, so :meth:`JobStore.recover_abandoned_jobs` either
requeues it (worker-mode rows with attempts remaining) or fails it explicitly (everything else),
and terminal transitions are fenced to the claiming attempt so a late writer whose claim was lost
can never overwrite a recovered job's authoritative outcome.

Compatibility model (ADR-0041): the database schema is versioned via ``PRAGMA user_version``. A
fresh database is created at the current version; the known previous version is migrated in one
serialized transaction; any other version — newer, unknown, or an unversioned foreign file — fails
explicitly with :class:`JobStoreIncompatibleError` and is never stamped, altered, or silently
treated as compatible.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import ApiError
from app.services.job_models import (
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobStatus,
    now_utc_iso,
)

_SCHEMA_VERSION = 2
_KNOWN_LEGACY_VERSIONS = frozenset({1})
_DEFAULT_BUSY_TIMEOUT_MS = 5000
_MAX_LIST_LIMIT = 100

# Static, non-sensitive terminal metadata for a job whose process disappeared mid-run and whose
# retry budget is exhausted (or that can never be retried, e.g. a synchronous inline run).
_DEFAULT_LEASE_SECONDS = 3600.0
INTERRUPTED_ERROR_CODE = "interrupted"
_INTERRUPTED_ERROR_MESSAGE = (
    "Processing was interrupted and could not be recovered automatically."
)


class JobStoreUnavailableError(ApiError):
    """Raised when durable job state cannot be read or written."""

    def __init__(self) -> None:
        super().__init__("Job state store is unavailable.", 503)


class JobStoreIncompatibleError(ApiError):
    """Raised when the job database's schema version is not supported by this build.

    Deliberately distinct from :class:`JobStoreUnavailableError`: an incompatible database must
    never be stamped, migrated blindly, or overwritten — it requires an operator decision, so the
    error names the versions instead of pretending the store is merely busy.
    """

    def __init__(self, found_version: int) -> None:
        super().__init__(
            "Job state database schema version "
            f"{found_version} is not supported by this application version "
            f"(supported: {_SCHEMA_VERSION}). Refusing to modify it.",
            503,
        )
        self.found_version = found_version


class JobNotFoundError(ApiError):
    """Raised when a job id does not resolve to a stored record."""

    def __init__(self) -> None:
        super().__init__("Job not found.", 404)


class StaleJobClaimError(ApiError):
    """Raised when a terminal transition no longer owns the row it tries to finish.

    The row exists but is not ``running`` at the writer's claimed attempt anymore — its lease
    expired and recovery requeued or failed it. The late writer's outcome is refused so a recovered
    job can never be silently overwritten by a process that already lost its claim.
    """

    def __init__(self) -> None:
        super().__init__("Job claim is no longer current; result was not recorded.", 409)


class JobStore:
    """Repository for durable, metadata-only job records."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        """Create or migrate the schema and set SQLite runtime pragmas.

        Raises :class:`JobStoreIncompatibleError` for an unsupported schema version instead of
        touching the file.
        """
        self._run(lambda _connection: None)

    def create_job(self, record: JobRecord) -> None:
        """Persist a newly-created pending job record."""

        def _create(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id,
                    document_id,
                    kind,
                    status,
                    execution_mode,
                    created_at,
                    started_at,
                    finished_at,
                    updated_at,
                    attempt_count,
                    error_code,
                    error_message,
                    result_artifact_id,
                    result_artifact_type,
                    metadata_json,
                    lease_expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    record.job_id,
                    record.document_id,
                    record.kind.value,
                    record.status.value,
                    record.execution_mode.value,
                    record.created_at,
                    record.started_at,
                    record.finished_at,
                    record.updated_at or record.created_at,
                    record.attempt_count,
                    record.error_code,
                    record.error_message,
                    record.artifact_id,
                    record.artifact_type,
                    _metadata_json(record),
                ),
            )

        self._run(_create)

    def mark_running(
        self, record: JobRecord, *, lease_seconds: float = _DEFAULT_LEASE_SECONDS
    ) -> None:
        """Persist the pending → running transition with a fresh processing lease."""

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = ?,
                    updated_at = ?,
                    attempt_count = ?,
                    lease_expires_at = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE job_id = ?
                """,
                (
                    record.status.value,
                    record.started_at,
                    record.updated_at,
                    record.attempt_count,
                    _lease_deadline(lease_seconds),
                    record.job_id,
                ),
            )
            _raise_if_missing(cursor)

        self._run(_mark)

    def mark_succeeded(self, record: JobRecord) -> None:
        """Persist the running → succeeded transition, fenced to the claiming attempt.

        The update applies only while the row is still ``running`` at ``record.attempt_count``.
        A row that was recovered (requeued or failed) after this writer lost its lease raises
        :class:`StaleJobClaimError` instead of overwriting the recovered state; a deleted row
        raises :class:`JobNotFoundError` exactly as before.
        """

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    result_artifact_id = ?,
                    result_artifact_type = ?,
                    lease_expires_at = NULL,
                    error_code = NULL,
                    error_message = NULL
                WHERE job_id = ? AND status = ? AND attempt_count = ?
                """,
                (
                    record.status.value,
                    record.finished_at,
                    record.updated_at,
                    record.artifact_id,
                    record.artifact_type,
                    record.job_id,
                    JobStatus.RUNNING.value,
                    record.attempt_count,
                ),
            )
            _raise_if_unfenced(connection, cursor, record.job_id)

        self._run(_mark)

    def mark_failed(self, record: JobRecord) -> None:
        """Persist the running → failed transition, fenced to the claiming attempt."""

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    error_code = ?,
                    error_message = ?,
                    lease_expires_at = NULL,
                    result_artifact_id = NULL,
                    result_artifact_type = NULL
                WHERE job_id = ? AND status = ? AND attempt_count = ?
                """,
                (
                    record.status.value,
                    record.finished_at,
                    record.updated_at,
                    record.error_code,
                    record.error_message,
                    record.job_id,
                    JobStatus.RUNNING.value,
                    record.attempt_count,
                ),
            )
            _raise_if_unfenced(connection, cursor, record.job_id)

        self._run(_mark)

    def claim_next_pending_job(
        self,
        kind: JobKind,
        *,
        max_attempts: int = 1,
        lease_seconds: float = _DEFAULT_LEASE_SECONDS,
    ) -> JobRecord | None:
        """Atomically claim the oldest pending job of ``kind`` and mark it ``running``.

        Returns the claimed record (already in ``running`` state) or ``None`` when nothing is
        pending. The transition is one ``UPDATE ... RETURNING`` statement whose ``WHERE`` re-selects
        the target row, so under SQLite's single-writer WAL lock two concurrent workers can never
        claim the same job: the second worker's statement runs after the first commits and no longer
        sees the row as ``pending``. Jobs whose ``attempt_count`` already reached ``max_attempts``
        are left untouched. The claim carries a processing lease; execution then runs *outside*
        this short transaction — the DB is only touched to claim and, later, to record the terminal
        status (fenced to this claim's attempt).
        """

        claimed_at = now_utc_iso()

        def _claim(connection: sqlite3.Connection) -> JobRecord | None:
            row = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = ?,
                    updated_at = ?,
                    attempt_count = attempt_count + 1,
                    lease_expires_at = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE job_id = (
                    SELECT job_id
                    FROM jobs
                    WHERE status = ? AND kind = ? AND attempt_count < ?
                    ORDER BY created_at ASC, job_id ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (
                    JobStatus.RUNNING.value,
                    claimed_at,
                    claimed_at,
                    _lease_deadline(lease_seconds),
                    JobStatus.PENDING.value,
                    kind.value,
                    max_attempts,
                ),
            ).fetchone()
            return _row_to_record(row) if row is not None else None

        return self._run(_claim)

    def recover_abandoned_jobs(
        self,
        *,
        max_attempts: int,
        kind: JobKind | None = None,
        reclaim_active_worker_leases: bool = False,
    ) -> tuple[int, int]:
        """Recover ``running`` rows whose claim is abandoned; returns ``(requeued, failed)``.

        A row is abandoned when its lease expired or it has no lease at all (it predates leases —
        nothing running now could have written it). ``reclaim_active_worker_leases=True`` widens
        recovery to *every* worker-mode ``running`` row of ``kind`` regardless of its lease: only
        the (single) worker process for that kind may use it, at startup, where any such row is
        provably an orphan of its own previous life. Synchronous inline rows are never reclaimed
        early — a live API request may still own them until the lease runs out.

        Worker-mode rows with attempts remaining are requeued (``pending``, keeping their consumed
        attempt count, so the retry budget is honest); every other abandoned row — retry budget
        exhausted, or a synchronous inline run whose process died — becomes an explicit terminal
        ``failed`` with the static ``interrupted`` error. Recovery is idempotent and set-based:
        the same store state always recovers to the same outcome, no matter which process runs it.
        """

        now = now_utc_iso()

        def _recover(connection: sqlite3.Connection) -> tuple[int, int]:
            kind_clause = "AND kind = ?" if kind is not None else ""
            kind_params: tuple[str, ...] = (kind.value,) if kind is not None else ()
            worker_lease_clause = (
                "1 = 1"
                if reclaim_active_worker_leases
                else "(lease_expires_at IS NULL OR lease_expires_at <= ?)"
            )
            worker_lease_params: tuple[str, ...] = (
                () if reclaim_active_worker_leases else (now,)
            )
            requeued = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?,
                    started_at = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE status = ?
                  AND execution_mode = ?
                  AND attempt_count < ?
                  {kind_clause}
                  AND {worker_lease_clause}
                """,
                (
                    JobStatus.PENDING.value,
                    now,
                    JobStatus.RUNNING.value,
                    JobExecutionMode.FUTURE_WORKER.value,
                    max_attempts,
                    *kind_params,
                    *worker_lease_params,
                ),
            ).rowcount
            failed = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    lease_expires_at = NULL,
                    error_code = ?,
                    error_message = ?,
                    result_artifact_id = NULL,
                    result_artifact_type = NULL
                WHERE status = ?
                  {kind_clause}
                  AND (
                    (
                      execution_mode = ?
                      AND attempt_count >= ?
                      AND {worker_lease_clause}
                    )
                    OR (
                      execution_mode != ?
                      AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                    )
                  )
                """,
                (
                    JobStatus.FAILED.value,
                    now,
                    now,
                    INTERRUPTED_ERROR_CODE,
                    _INTERRUPTED_ERROR_MESSAGE,
                    JobStatus.RUNNING.value,
                    *kind_params,
                    JobExecutionMode.FUTURE_WORKER.value,
                    max_attempts,
                    *worker_lease_params,
                    JobExecutionMode.FUTURE_WORKER.value,
                    now,
                ),
            ).rowcount
            return requeued, failed

        return self._run(_recover)

    def record_worker_heartbeat(self, kind: JobKind, worker_id: str) -> None:
        """Record that a worker for ``kind`` is alive right now."""

        seen_at = now_utc_iso()

        def _beat(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO worker_status (kind, worker_id, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(kind) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (kind.value, worker_id, seen_at),
            )

        self._run(_beat)

    def get_worker_heartbeat(self, kind: JobKind) -> tuple[str, str] | None:
        """Return ``(worker_id, last_seen_at)`` for ``kind``, or ``None`` if never seen."""

        def _get(connection: sqlite3.Connection) -> tuple[str, str] | None:
            row = connection.execute(
                "SELECT worker_id, last_seen_at FROM worker_status WHERE kind = ?",
                (kind.value,),
            ).fetchone()
            if row is None:
                return None
            return str(row["worker_id"]), str(row["last_seen_at"])

        return self._run(_get)

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return a job by id, or ``None`` for an unknown id."""

        def _get(connection: sqlite3.Connection) -> JobRecord | None:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return _row_to_record(row) if row is not None else None

        return self._run(_get)

    def list_jobs_for_document(
        self, document_id: str, *, limit: int = 20
    ) -> list[JobRecord]:
        """Return newest jobs for one document, bounded for predictable status reads."""
        bounded_limit = max(1, min(limit, _MAX_LIST_LIMIT))

        def _list(connection: sqlite3.Connection) -> list[JobRecord]:
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE document_id = ?
                ORDER BY created_at DESC, job_id DESC
                LIMIT ?
                """,
                (document_id, bounded_limit),
            ).fetchall()
            return [_row_to_record(row) for row in rows]

        return self._run(_list)

    def list_succeeded_jobs_for_artifact(
        self, document_id: str, artifact_id: str, artifact_type: str
    ) -> list[JobRecord]:
        """Return every durable success claiming one exact document artifact identity."""

        def _list(connection: sqlite3.Connection) -> list[JobRecord]:
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE document_id = ?
                  AND status = ?
                  AND result_artifact_id = ?
                  AND result_artifact_type = ?
                ORDER BY finished_at ASC, job_id ASC
                """,
                (
                    document_id,
                    JobStatus.SUCCEEDED.value,
                    artifact_id,
                    artifact_type,
                ),
            ).fetchall()
            return [_row_to_record(row) for row in rows]

        return self._run(_list)

    def delete_jobs_for_document(self, document_id: str) -> int:
        """Delete job metadata for a document deletion boundary."""

        def _delete(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                "DELETE FROM jobs WHERE document_id = ?",
                (document_id,),
            )
            return cursor.rowcount

        return self._run(_delete)

    def _run[T](self, action: Callable[[sqlite3.Connection], T]) -> T:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path, timeout=5.0) as connection:
                connection.row_factory = sqlite3.Row
                _configure_connection(connection)
                _ensure_schema(connection)
                return action(connection)
        except ApiError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise JobStoreUnavailableError from exc


def get_job_store(settings: Settings) -> JobStore:
    """Build a store for the configured SQLite path."""
    return JobStore(settings.resolved_job_store_db_path)


def delete_jobs_for_document(settings: Settings, document_id: str) -> int:
    """Delete job rows for a document if the job DB has been created."""
    db_path = settings.resolved_job_store_db_path
    if not db_path.exists():
        return 0
    return JobStore(db_path).delete_jobs_for_document(document_id)


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute(f"PRAGMA busy_timeout = {_DEFAULT_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create, migrate, or refuse the schema based on the file's declared version.

    - current version: nothing to do;
    - ``0`` with no ``jobs`` table: a fresh file — create the schema and stamp the version;
    - a known legacy version: migrate inside one serialized transaction;
    - anything else (an unversioned file that already contains data, or a newer/unknown version):
      :class:`JobStoreIncompatibleError` — the file is never stamped, altered, or overwritten.
    """
    version = _user_version(connection)
    if version == _SCHEMA_VERSION:
        return
    if version == 0 and not _has_jobs_table(connection):
        _create_schema(connection)
        return
    if version in _KNOWN_LEGACY_VERSIONS:
        _migrate_schema(connection, version)
        return
    raise JobStoreIncompatibleError(version)


def _user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _has_jobs_table(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone()
    return row is not None


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    # Re-check under the write lock: a concurrent process may have created it first.
    if _user_version(connection) == _SCHEMA_VERSION:
        connection.execute("COMMIT")
        return
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
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
            metadata_json TEXT NOT NULL DEFAULT '{}',
            lease_expires_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_document_created
        ON jobs (document_id, created_at DESC, job_id DESC)
        """
    )
    _create_worker_status_table(connection)
    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    connection.execute("COMMIT")


def _migrate_schema(connection: sqlite3.Connection, from_version: int) -> None:
    """Migrate a known legacy schema to the current version, serialized across processes."""
    connection.execute("BEGIN IMMEDIATE")
    # Re-check under the write lock: a concurrent process may have migrated first.
    current = _user_version(connection)
    if current == _SCHEMA_VERSION:
        connection.execute("COMMIT")
        return
    if current != from_version:
        connection.execute("ROLLBACK")
        raise JobStoreIncompatibleError(current)
    # v1 → v2: processing leases on jobs plus the worker heartbeat table.
    connection.execute("ALTER TABLE jobs ADD COLUMN lease_expires_at TEXT")
    _create_worker_status_table(connection)
    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    connection.execute("COMMIT")


def _create_worker_status_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_status (
            kind TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )


def _lease_deadline(lease_seconds: float) -> str:
    deadline = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    return deadline.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _metadata_json(record: JobRecord) -> str:
    metadata = {str(key): str(value) for key, value in record.metadata.items()}
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"))


def _metadata_from_json(value: str) -> dict[str, str]:
    decoded: Any = json.loads(value)
    if not isinstance(decoded, dict):
        return {}
    return {str(key): str(item) for key, item in decoded.items()}


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=str(row["job_id"]),
        document_id=str(row["document_id"]),
        kind=JobKind(str(row["kind"])),
        execution_mode=JobExecutionMode(str(row["execution_mode"])),
        status=JobStatus(str(row["status"])),
        created_at=str(row["created_at"]),
        metadata=_metadata_from_json(str(row["metadata_json"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        updated_at=str(row["updated_at"]),
        attempt_count=int(row["attempt_count"]),
        artifact_id=row["result_artifact_id"],
        artifact_type=row["result_artifact_type"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _raise_if_missing(cursor: sqlite3.Cursor) -> None:
    if cursor.rowcount == 0:
        raise JobNotFoundError()


def _raise_if_unfenced(
    connection: sqlite3.Connection, cursor: sqlite3.Cursor, job_id: str
) -> None:
    """Distinguish a deleted row (not found) from a lost claim (stale) after a fenced update."""
    if cursor.rowcount > 0:
        return
    row = connection.execute(
        "SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise JobNotFoundError()
    raise StaleJobClaimError()
