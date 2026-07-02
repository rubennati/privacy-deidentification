"""Dev-only, append-only capture of human review feedback on detected PII entities.

This is deliberately *not* a learning system and *not* the L2 ``review_result`` model: it only
records structured feedback lines locally so recurring detection errors can be analysed later.
It is gated behind ``ENABLE_DEV_ENGINE_SETTINGS`` and writes nothing when the gate is off.

Privacy by construction: only offsets, entity type, recognizer, score, and an optional opaque
``text_hash`` are stored — never document text, OCR full text, or raw entity values. Engine
settings are copied from the referenced PII artifact (server-authoritative), not the client.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from app import __version__
from app.config import Settings
from app.errors import ApiError
from app.schemas import PiiFeedbackAck, PiiFeedbackRecord, PiiFeedbackRequest
from app.services.artifact_service import get_pii_artifact
from app.services.document_service import DocumentNotFoundError, get_document_record

_FEEDBACK_DIRECTORY = "feedback"
_FEEDBACK_FILENAME = "pii_feedback.jsonl"


class FeedbackDisabledError(ApiError):
    """Raised when review feedback is attempted while the dev gate is disabled."""

    def __init__(self) -> None:
        super().__init__("Review feedback capture is disabled.", 403)


class FeedbackArtifactNotFoundError(ApiError):
    """Raised when the referenced PII artifact does not exist for the document."""

    def __init__(self) -> None:
        super().__init__("Referenced PII result not found.", 404)


def record_pii_feedback(
    settings: Settings, document_id: str, request: PiiFeedbackRequest
) -> PiiFeedbackAck:
    """Append one dev-only feedback line for a PII entity and return a small confirmation.

    Order matters: the gate is checked first, so a disabled deployment never touches disk nor
    reveals whether a document exists.
    """
    if not settings.enable_dev_engine_settings:
        raise FeedbackDisabledError
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_pii_artifact(settings, document_id, request.artifact_id)
    if artifact is None:
        raise FeedbackArtifactNotFoundError

    engine_settings = artifact.content.engine_settings
    record = PiiFeedbackRecord(
        app_version=__version__,
        recorded_at=_now_utc_iso(),
        document_id=document_id,
        artifact_id=request.artifact_id,
        entity=request.entity,
        feedback=request.feedback,
        engine_settings=engine_settings,
        engine_settings_origin="artifact" if engine_settings is not None else "unknown",
    )
    _append_feedback_line(settings, document_id, record)
    return PiiFeedbackAck(
        recorded=True,
        schema_version=record.schema_version,
        recorded_at=record.recorded_at,
    )


def _append_feedback_line(
    settings: Settings, document_id: str, record: PiiFeedbackRecord
) -> None:
    directory = _feedback_directory(settings, document_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / _FEEDBACK_FILENAME
    # One JSON object per line; append-only so no run ever mutates a prior entry.
    line = record.model_dump_json() + "\n"
    try:
        with destination.open("a", encoding="utf-8") as feedback_file:
            feedback_file.write(line)
            feedback_file.flush()
            os.fsync(feedback_file.fileno())
    except OSError as exc:  # pragma: no cover - surfaced as a clean 500 by the handler
        raise ApiError("Feedback could not be stored.", 500) from exc


def _feedback_directory(settings: Settings, document_id: str) -> Path:
    # Reuse the artifact id-shape guard indirectly: document_id shape is validated by
    # get_document_record's lookup, but keep feedback co-located under document-data.
    return settings.document_data_dir / document_id / _FEEDBACK_DIRECTORY


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
