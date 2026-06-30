"""File-based persistence for immutable derived artifacts."""

from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.schemas import AuditArtifact, TextArtifact

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACTS_DIRECTORY = "artifacts"


def save_audit_artifact(settings: Settings, artifact: AuditArtifact) -> None:
    """Write an audit artifact through a temporary file and atomic rename."""
    _save_artifact_json(settings, artifact.document_id, artifact.id, artifact.model_dump_json())


def save_text_artifact(settings: Settings, artifact: TextArtifact) -> None:
    """Write a text artifact through a temporary file and atomic rename."""
    _save_artifact_json(settings, artifact.document_id, artifact.id, artifact.model_dump_json())


def get_latest_audit_artifact(settings: Settings, document_id: str) -> AuditArtifact | None:
    """Return the newest valid audit artifact for a document, if one exists."""
    directory = _document_artifact_directory(settings, document_id)
    if not directory.is_dir():
        return None

    artifacts = [
        artifact
        for path in directory.glob("*.json")
        if (artifact := _read_audit_artifact(path, document_id)) is not None
    ]
    if not artifacts:
        return None
    return max(artifacts, key=lambda artifact: (artifact.created_at, artifact.id))


def get_latest_text_artifact(settings: Settings, document_id: str) -> TextArtifact | None:
    """Return the newest valid text artifact for a document, if one exists."""
    directory = _document_artifact_directory(settings, document_id)
    if not directory.is_dir():
        return None

    artifacts = [
        artifact
        for path in directory.glob("*.json")
        if (artifact := _read_text_artifact(path, document_id)) is not None
    ]
    if not artifacts:
        return None
    return max(artifacts, key=lambda artifact: (artifact.created_at, artifact.id))


def delete_document_artifacts(settings: Settings, document_id: str) -> None:
    """Delete all derived artifacts for one validated document id."""
    directory = _document_artifact_directory(settings, document_id)
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
    directory.rmdir()
    with suppress(OSError):
        directory.parent.rmdir()


def _document_artifact_directory(settings: Settings, document_id: str) -> Path:
    if not _ID_PATTERN.fullmatch(document_id):
        raise ValueError("invalid document id")
    return settings.upload_dir / _ARTIFACTS_DIRECTORY / document_id


def _save_artifact_json(
    settings: Settings, document_id: str, artifact_id: str, content: str
) -> None:
    directory = _document_artifact_directory(settings, document_id)
    if not _ID_PATTERN.fullmatch(artifact_id):
        raise ValueError("invalid artifact id")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{artifact_id}.json"
    partial = destination.with_name(destination.name + ".part")
    try:
        with partial.open("w", encoding="utf-8") as artifact_file:
            artifact_file.write(content)
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
        partial.replace(destination)
    except Exception:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise


def _read_audit_artifact(path: Path, document_id: str) -> AuditArtifact | None:
    try:
        artifact = AuditArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return artifact if artifact.document_id == document_id else None


def _read_text_artifact(path: Path, document_id: str) -> TextArtifact | None:
    try:
        artifact = TextArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return artifact if artifact.document_id == document_id else None
