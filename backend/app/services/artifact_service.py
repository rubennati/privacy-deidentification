"""File-based persistence for immutable derived artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.schemas import (
    AuditArtifact,
    PiiArtifact,
    PiiReviewResultArtifact,
    QualityReportArtifact,
    TextArtifact,
)
from app.services.artifact_lifecycle import (
    InvalidCurrentArtifactError,
    UncommittedArtifactError,
    current_artifact_id,
    has_unique_succeeded_job,
    publish_artifact_files,
)

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACTS_DIRECTORY = "artifacts"


def save_audit_artifact(settings: Settings, artifact: AuditArtifact) -> None:
    """Write an audit artifact through a temporary file and atomic rename."""
    _publish(
        settings,
        artifact.document_id,
        artifact.artifact_type,
        artifact.id,
        artifact.model_dump_json(),
    )


def save_text_artifact(settings: Settings, artifact: TextArtifact) -> None:
    """Write a text artifact through a temporary file and atomic rename."""
    _publish(
        settings,
        artifact.document_id,
        artifact.artifact_type,
        artifact.id,
        artifact.model_dump_json(),
    )


def save_quality_report_artifact(settings: Settings, artifact: QualityReportArtifact) -> None:
    """Write a quality report through a temporary file and atomic rename."""
    _publish(
        settings,
        artifact.document_id,
        artifact.artifact_type,
        artifact.id,
        artifact.model_dump_json(),
    )


def save_pii_artifact(settings: Settings, artifact: PiiArtifact) -> None:
    """Write a PII artifact through a temporary file and atomic rename."""
    _publish(
        settings,
        artifact.document_id,
        artifact.artifact_type,
        artifact.id,
        artifact.model_dump_json(),
    )


def save_job_pii_artifact(
    settings: Settings, artifact: PiiArtifact, *, authority_job_id: str
) -> None:
    """Publish a PII result whose current authority activates only after job success."""
    publish_artifact_files(
        settings,
        artifact.document_id,
        {artifact.artifact_type: (artifact.id, artifact.model_dump_json())},
        authority_job_id=authority_job_id,
        authority_job_result=(artifact.id, artifact.artifact_type),
    )


def save_pii_review_result_artifact(
    settings: Settings, artifact: PiiReviewResultArtifact
) -> None:
    """Write a PII review-result snapshot through a temporary file and atomic rename."""
    _publish(
        settings,
        artifact.document_id,
        artifact.artifact_type,
        artifact.id,
        artifact.model_dump_json(),
    )


def save_text_run(
    settings: Settings,
    text: TextArtifact,
    quality_report: QualityReportArtifact,
    *,
    authority_job_id: str | None = None,
) -> None:
    """Publish the text result and its quality report as one authoritative OCR run."""
    if text.document_id != quality_report.document_id:
        raise ValueError("OCR run artifacts belong to different documents")
    publish_artifact_files(
        settings,
        text.document_id,
        {
            text.artifact_type: (text.id, text.model_dump_json()),
            quality_report.artifact_type: (quality_report.id, quality_report.model_dump_json()),
        },
        authority_job_id=authority_job_id,
        authority_job_result=(text.id, text.artifact_type),
    )


def get_latest_audit_artifact(settings: Settings, document_id: str) -> AuditArtifact | None:
    """Return the newest valid audit artifact for a document, if one exists."""
    current = _current(settings, document_id, "audit_result", _read_audit_artifact)
    if current is not None:
        return current
    return None


def get_latest_text_artifact(settings: Settings, document_id: str) -> TextArtifact | None:
    """Return the newest valid text artifact for a document, if one exists."""
    current = _current(settings, document_id, "text_result", _read_text_artifact)
    if current is not None:
        return current
    return None


def get_text_artifact(
    settings: Settings, document_id: str, artifact_id: str
) -> TextArtifact | None:
    """Return one exact text artifact, never a newer artifact for the same document."""
    if not _ID_PATTERN.fullmatch(artifact_id):
        return None
    path = _document_artifact_directory(settings, document_id) / f"{artifact_id}.json"
    if not path.is_file():
        return None
    return _read_text_artifact(path, document_id)


def get_committed_text_artifact(
    settings: Settings, document_id: str, artifact_id: str
) -> TextArtifact | None:
    """Return exact OCR history only when one durable successful job proves its commit."""
    artifact = get_text_artifact(settings, document_id, artifact_id)
    if artifact is None:
        return None
    if not has_unique_succeeded_job(settings, document_id, artifact_id, artifact.artifact_type):
        raise UncommittedArtifactError(artifact.artifact_type)
    return artifact


def get_latest_quality_report_artifact(
    settings: Settings, document_id: str
) -> QualityReportArtifact | None:
    """Return the newest valid quality report for a document, if one exists."""
    current = _current(settings, document_id, "quality_report", _read_quality_report_artifact)
    if current is not None:
        return current
    return None


def get_latest_pii_artifact(settings: Settings, document_id: str) -> PiiArtifact | None:
    """Return the newest valid PII artifact for a document, if one exists."""
    current = _current(settings, document_id, "pii_result", _read_pii_artifact)
    if current is not None:
        return current
    return None


def get_pii_artifact(
    settings: Settings, document_id: str, artifact_id: str
) -> PiiArtifact | None:
    """Return one specific PII artifact by id, or None if missing or not a PII result.

    Used to validate an ``artifact_id`` a client refers to (e.g. review feedback) and to read
    the artifact's authoritative engine settings without trusting the client.
    """
    if not _ID_PATTERN.fullmatch(artifact_id):
        return None
    path = _document_artifact_directory(settings, document_id) / f"{artifact_id}.json"
    if not path.is_file():
        return None
    return _read_pii_artifact(path, document_id)


def get_latest_pii_review_result_artifact(
    settings: Settings, document_id: str
) -> PiiReviewResultArtifact | None:
    """Return the newest PII review-result snapshot for a document, if one exists."""
    current = _current(
        settings, document_id, "pii_review_result", _read_pii_review_result_artifact
    )
    if current is not None:
        return current
    return None


def _document_artifact_directory(settings: Settings, document_id: str) -> Path:
    if not _ID_PATTERN.fullmatch(document_id):
        raise ValueError("invalid document id")
    return settings.document_data_dir / document_id / _ARTIFACTS_DIRECTORY


def _publish(
    settings: Settings, document_id: str, artifact_type: str, artifact_id: str, content: str
) -> None:
    if not _ID_PATTERN.fullmatch(artifact_id):
        raise ValueError("invalid artifact id")
    publish_artifact_files(settings, document_id, {artifact_type: (artifact_id, content)})


def _current[T](
    settings: Settings,
    document_id: str,
    artifact_type: str,
    reader: Callable[[Path, str], T | None],
) -> T | None:
    artifact_id = current_artifact_id(settings, document_id, artifact_type)
    if artifact_id is None:
        return None
    if not _ID_PATTERN.fullmatch(artifact_id):
        raise InvalidCurrentArtifactError(artifact_type)
    path = _document_artifact_directory(settings, document_id) / f"{artifact_id}.json"
    artifact = reader(path, document_id)
    if artifact is None:
        raise InvalidCurrentArtifactError(artifact_type)
    return artifact


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


def _read_quality_report_artifact(
    path: Path, document_id: str
) -> QualityReportArtifact | None:
    try:
        artifact = QualityReportArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return artifact if artifact.document_id == document_id else None


def _read_pii_artifact(path: Path, document_id: str) -> PiiArtifact | None:
    try:
        artifact = PiiArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return artifact if artifact.document_id == document_id else None


def _read_pii_review_result_artifact(
    path: Path, document_id: str
) -> PiiReviewResultArtifact | None:
    try:
        artifact = PiiReviewResultArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return artifact if artifact.document_id == document_id else None
