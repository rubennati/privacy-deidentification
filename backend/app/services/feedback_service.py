"""Dev-only, append-only capture of human review feedback on detected PII entities.

This is deliberately *not* a learning system and *not* the L2 ``review_result`` model: it only
records structured feedback lines locally so recurring detection errors can be analysed later.
It is gated behind ``ENABLE_DEV_ENGINE_SETTINGS`` and writes nothing when the gate is off.

Only offsets, entity type, recognizer, the artifact-authoritative score, and an optional validated
SHA-256 ``text_hash`` are stored — never document text, OCR full text, or raw entity values. Entity
identity and engine settings are derived from the referenced PII artifact, not trusted from the
client.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app import __version__
from app.config import Settings
from app.errors import ApiError
from app.schemas import (
    PiiEntity,
    PiiFeedbackAck,
    PiiFeedbackEntityRef,
    PiiFeedbackRecord,
    PiiFeedbackRequest,
    PiiFeedbackSummary,
    PiiFeedbackSummaryItem,
)
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


class FeedbackEntityNotFoundError(ApiError):
    """Raised when the submitted fingerprint is not present in the referenced PII artifact."""

    def __init__(self) -> None:
        super().__init__(
            "Feedback entity reference does not match any entity in the referenced PII artifact.",
            422,
        )


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

    matched_entity = _find_matching_entity(artifact.content.entities, request.entity)
    if matched_entity is None:
        raise FeedbackEntityNotFoundError

    authoritative_entity = PiiFeedbackEntityRef(
        type=matched_entity.entity_type,
        start=matched_entity.start_offset,
        end=matched_entity.end_offset,
        score=matched_entity.score,
        recognizer=matched_entity.recognizer,
        text_hash=request.entity.text_hash,
    )

    engine_settings = artifact.content.engine_settings
    record = PiiFeedbackRecord(
        app_version=__version__,
        recorded_at=_now_utc_iso(),
        document_id=document_id,
        artifact_id=request.artifact_id,
        entity=authoritative_entity,
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


def summarize_pii_feedback(
    settings: Settings, document_id: str, artifact_id: str
) -> PiiFeedbackSummary:
    """Return the *latest* verdict per entity fingerprint for one artifact.

    Same gate/validation order as recording. The append-only log is collapsed by entity key
    (type + start + end + recognizer) with the last line winning, so the UI can restore a stable
    per-entity review state. Malformed or legacy lines are skipped rather than failing the read.
    No comment or raw value is returned.
    """
    if not settings.enable_dev_engine_settings:
        raise FeedbackDisabledError
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_pii_artifact(settings, document_id, artifact_id)
    if artifact is None:
        raise FeedbackArtifactNotFoundError

    destination = _feedback_directory(settings, document_id) / _FEEDBACK_FILENAME
    latest_by_key: dict[tuple[str, int, int, str], PiiFeedbackSummaryItem] = {}
    if destination.is_file():
        for line in destination.read_text(encoding="utf-8").splitlines():
            record = _parse_record(line)
            if record is None or record.artifact_id != artifact_id:
                continue
            entity = record.entity
            if _find_matching_entity(artifact.content.entities, entity) is None:
                continue
            key = (entity.type, entity.start, entity.end, entity.recognizer)
            latest_by_key[key] = PiiFeedbackSummaryItem(
                type=entity.type,
                start=entity.start,
                end=entity.end,
                recognizer=entity.recognizer,
                verdict=record.feedback.verdict,
                issue_type=record.feedback.issue_type,
                recorded_at=record.recorded_at,
            )
    return PiiFeedbackSummary(
        document_id=document_id,
        artifact_id=artifact_id,
        items=list(latest_by_key.values()),
    )


def _find_matching_entity(
    artifact_entities: list[PiiEntity], reference: PiiFeedbackEntityRef
) -> PiiEntity | None:
    """Find an artifact entity by the stable feedback identity fields.

    Score, page mapping, entity id, and optional legacy fields are deliberately not identity
    fields. This keeps matching stable across artifacts that lack optional metadata while ensuring
    the client cannot invent a type, span, or recognizer.
    """
    for entity in artifact_entities:
        if (
            entity.entity_type == reference.type
            and entity.start_offset == reference.start
            and entity.end_offset == reference.end
            and entity.recognizer == reference.recognizer
        ):
            return entity
    return None


def _parse_record(line: str) -> PiiFeedbackRecord | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        return PiiFeedbackRecord.model_validate_json(stripped)
    except ValidationError:
        return None


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
