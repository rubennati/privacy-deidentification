"""Cross-process authority and deletion boundary for document-owned artifacts."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from app.config import Settings
from app.errors import ApiError
from app.services.job_models import JobStatus
from app.services.job_store import get_job_store

_CURRENT_FILE = "current-artifacts"


class DocumentDeletedError(ApiError):
    """Raised when delayed processing tries to publish after deletion."""

    def __init__(self) -> None:
        super().__init__("Document has been deleted; result publication was refused.", 409)


class InvalidCurrentArtifactError(ApiError):
    """Raised when the authoritative pointer cannot be resolved faithfully."""

    def __init__(self, artifact_type: str) -> None:
        super().__init__(f"Current {artifact_type} artifact is invalid or incompatible.", 409)


def current_artifact_id(settings: Settings, document_id: str, artifact_type: str) -> str | None:
    """Resolve explicit authority and verify any producing job completed successfully."""
    path = settings.document_data_dir / document_id / "artifacts" / _CURRENT_FILE
    if not path.exists():
        artifact_directory = path.parent
        if artifact_directory.is_dir() and any(artifact_directory.glob("*.json")):
            raise InvalidCurrentArtifactError(artifact_type)
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise InvalidCurrentArtifactError(artifact_type) from exc
    if not isinstance(value, dict):
        raise InvalidCurrentArtifactError(artifact_type)
    artifact_id = value.get(artifact_type)
    if artifact_id is None:
        return None
    if isinstance(artifact_id, str):
        # Authority maps emitted by lifecycle v1 predate job binding but were already explicit,
        # atomic publication commits. They remain readable; absent maps never trigger scanning.
        return artifact_id
    if not isinstance(artifact_id, dict):
        raise InvalidCurrentArtifactError(artifact_type)
    published_id = artifact_id.get("artifact_id")
    job_id = artifact_id.get("job_id")
    job_result_id = artifact_id.get("job_result_artifact_id", published_id)
    job_result_type = artifact_id.get("job_result_artifact_type", artifact_type)
    if (
        not isinstance(published_id, str)
        or not isinstance(job_id, str)
        or not isinstance(job_result_id, str)
        or not isinstance(job_result_type, str)
    ):
        raise InvalidCurrentArtifactError(artifact_type)
    job = get_job_store(settings).get_job(job_id)
    if (
        job is None
        or job.document_id != document_id
        or job.status is not JobStatus.SUCCEEDED
        or job.artifact_id != job_result_id
        or job.artifact_type != job_result_type
    ):
        raise InvalidCurrentArtifactError(artifact_type)
    return published_id


def publish_artifact_files(
    settings: Settings,
    document_id: str,
    artifacts: dict[str, tuple[str, str]],
    *,
    authority_job_id: str | None = None,
    authority_job_result: tuple[str, str] | None = None,
) -> None:
    """Atomically publish one coherent run under the document lifecycle lock.

    ``artifacts`` maps artifact type to ``(artifact_id, serialized_json)``. All files are durable
    before the authority pointer changes, so readers see either the previous run or the complete
    new run, never a subset.
    """
    with document_lifecycle_lock(settings, document_id):
        if _tombstone_path(settings, document_id).exists():
            raise DocumentDeletedError
        directory = settings.document_data_dir / document_id / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        try:
            for _artifact_type, (artifact_id, content) in artifacts.items():
                destination = directory / f"{artifact_id}.json"
                _atomic_write(destination, content)
                written.append(destination)
            pointer = directory / _CURRENT_FILE
            current = _read_current_for_update(pointer)
            current.update(
                _authority_entries(artifacts, authority_job_id, authority_job_result)
            )
            _atomic_write(pointer, json.dumps(current, sort_keys=True, separators=(",", ":")))
        except Exception:
            for path in written:
                with suppress(OSError):
                    path.unlink()
            raise


def mark_document_deleted(settings: Settings, document_id: str) -> None:
    """Persist the terminal tombstone while excluding all artifact publishers."""
    path = _tombstone_path(settings, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, "deleted\n")


def is_document_deleted(settings: Settings, document_id: str) -> bool:
    return _tombstone_path(settings, document_id).exists()


@contextmanager
def document_lifecycle_lock(settings: Settings, document_id: str) -> Iterator[None]:
    """Serialize publication and deletion across API/worker processes."""
    directory = settings.job_state_dir / "document-lifecycle"
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / f"{document_id}.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _tombstone_path(settings: Settings, document_id: str) -> Path:
    return settings.job_state_dir / "document-lifecycle" / f"{document_id}.deleted"


def _read_current_for_update(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidCurrentArtifactError("authority") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InvalidCurrentArtifactError("authority")
    return value


def _authority_entries(
    artifacts: dict[str, tuple[str, str]],
    authority_job_id: str | None,
    authority_job_result: tuple[str, str] | None,
) -> dict[str, object]:
    if authority_job_id is None:
        return {
            artifact_type: artifact_id
            for artifact_type, (artifact_id, _) in artifacts.items()
        }
    result_id, result_type = authority_job_result or next(
        (artifact_id, artifact_type)
        for artifact_type, (artifact_id, _) in artifacts.items()
    )
    return {
        artifact_type: {
            "artifact_id": artifact_id,
            "job_id": authority_job_id,
            "job_result_artifact_id": result_id,
            "job_result_artifact_type": result_type,
        }
        for artifact_type, (artifact_id, _) in artifacts.items()
    }


def _atomic_write(destination: Path, content: str) -> None:
    partial = destination.with_name(destination.name + ".part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        partial.replace(destination)
    except Exception:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise
