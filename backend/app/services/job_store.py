"""SQLite-backed job metadata store (ADR-0023 Phase 2).

The store is deliberately small: artifacts remain immutable JSON files, while SQLite records only
job lifecycle metadata that is safe to expose through a status API. Do not add raw OCR text,
canonical reading text, PII values, artifact payloads, stack traces, or copied document snippets.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import ApiError
from app.services.job_models import (
    JobExecutionMode,
    JobKind,
    JobRecord,
    JobStatus,
)

_SCHEMA_VERSION = 1
_DEFAULT_BUSY_TIMEOUT_MS = 5000
_MAX_LIST_LIMIT = 100


class JobStoreUnavailableError(ApiError):
    """Raised when durable job state cannot be read or written."""

    def __init__(self) -> None:
        super().__init__("Job state store is unavailable.", 503)


class JobNotFoundError(ApiError):
    """Raised when a job id does not resolve to a stored record."""

    def __init__(self) -> None:
        super().__init__("Job not found.", 404)


class JobStore:
    """Repository for durable, metadata-only job records."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        """Create the schema if needed and set SQLite runtime pragmas."""
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
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def mark_running(self, record: JobRecord) -> None:
        """Persist the pending → running transition."""

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = ?,
                    updated_at = ?,
                    attempt_count = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE job_id = ?
                """,
                (
                    record.status.value,
                    record.started_at,
                    record.updated_at,
                    record.attempt_count,
                    record.job_id,
                ),
            )
            _raise_if_missing(cursor)

        self._run(_mark)

    def mark_succeeded(self, record: JobRecord) -> None:
        """Persist the running → succeeded transition and produced artifact reference."""

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    result_artifact_id = ?,
                    result_artifact_type = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE job_id = ?
                """,
                (
                    record.status.value,
                    record.finished_at,
                    record.updated_at,
                    record.artifact_id,
                    record.artifact_type,
                    record.job_id,
                ),
            )
            _raise_if_missing(cursor)

        self._run(_mark)

    def mark_failed(self, record: JobRecord) -> None:
        """Persist the running → failed transition with sanitized error metadata only."""

        def _mark(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    error_code = ?,
                    error_message = ?,
                    result_artifact_id = NULL,
                    result_artifact_type = NULL
                WHERE job_id = ?
                """,
                (
                    record.status.value,
                    record.finished_at,
                    record.updated_at,
                    record.error_code,
                    record.error_message,
                    record.job_id,
                ),
            )
            _raise_if_missing(cursor)

        self._run(_mark)

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
                _initialize_schema(connection)
                return action(connection)
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


def _initialize_schema(connection: sqlite3.Connection) -> None:
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
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_document_created
        ON jobs (document_id, created_at DESC, job_id DESC)
        """
    )
    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


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
