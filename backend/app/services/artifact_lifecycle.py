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
    """Return the explicitly published current id, or ``None`` for legacy state."""
    path = settings.document_data_dir / document_id / "artifacts" / _CURRENT_FILE
    if not path.exists():
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
    if not isinstance(artifact_id, str):
        raise InvalidCurrentArtifactError(artifact_type)
    return artifact_id


def publish_artifact_files(
    settings: Settings,
    document_id: str,
    artifacts: dict[str, tuple[str, str]],
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
                {
                    artifact_type: artifact_id
                    for artifact_type, (artifact_id, _) in artifacts.items()
                }
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


def _read_current_for_update(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidCurrentArtifactError("authority") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise InvalidCurrentArtifactError("authority")
    return value


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
