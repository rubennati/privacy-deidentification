"""Synchronous PII Workstation v1 detection and immutable artifact creation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.config import Settings
from app.errors import ApiError
from app.schemas import PiiArtifact, PiiContent, PiiEntity, PiiValidationSummary, TextArtifact
from app.services.artifact_service import (
    get_latest_pii_artifact,
    get_latest_text_artifact,
    save_pii_artifact,
)
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.pii_adapters import DetectedEntity, PiiAnalyzer
from app.services.pii_candidate_validation import ValidatedEntity, validate_candidates


class PiiConflictError(ApiError):
    """Raised when no valid text input exists for the station."""

    def __init__(self) -> None:
        super().__init__("Document has no valid text result.", 409)


class PiiProcessingError(ApiError):
    """Raised when a valid text input cannot be analyzed safely."""

    def __init__(self) -> None:
        super().__init__("Text result could not be analyzed.", 422)


class PiiArtifactNotFoundError(ApiError):
    """Raised when a document has no persisted PII result."""

    def __init__(self) -> None:
        super().__init__("PII result not found.", 404)


def create_pii_artifact(
    settings: Settings, document_id: str, analyzer: PiiAnalyzer
) -> PiiArtifact:
    """Analyze the latest valid text result and persist an immutable PII result."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    text_artifact = get_latest_text_artifact(settings, document_id)
    if text_artifact is None:
        raise PiiConflictError

    content = _analyze_text(settings, text_artifact, analyzer)
    artifact = PiiArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_text_artifact_id=text_artifact.id,
        created_at=_now_utc_iso(),
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def get_latest_pii(settings: Settings, document_id: str) -> PiiArtifact:
    """Return the newest PII artifact after confirming the document exists."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_latest_pii_artifact(settings, document_id)
    if artifact is None:
        raise PiiArtifactNotFoundError
    return artifact


def _analyze_text(
    settings: Settings, text_artifact: TextArtifact, analyzer: PiiAnalyzer
) -> PiiContent:
    text = text_artifact.content.text
    configured_types = settings.pii_entity_types
    flags: list[str] = []
    detected: list[tuple[DetectedEntity, int, int | None]] = []

    if not text.strip():
        flags.append("empty_text")
    else:
        try:
            if text_artifact.content.pages:
                global_start = 0
                for page in text_artifact.content.pages:
                    page_entities = analyzer.analyze(
                        page.text,
                        settings.pii_language,
                        configured_types,
                        settings.pii_score_threshold,
                    )
                    detected.extend(
                        (entity, global_start, page.page_number) for entity in page_entities
                    )
                    global_start += len(page.text) + 2
            else:
                detected.extend(
                    (entity, 0, None)
                    for entity in analyzer.analyze(
                        text,
                        settings.pii_language,
                        configured_types,
                        settings.pii_score_threshold,
                    )
                )
        except ApiError:
            raise
        except Exception as exc:
            raise PiiProcessingError from exc

    page_texts = _page_text_map(text_artifact)
    validated_detected, validation_summary = validate_candidates(
        detected,
        page_texts,
        settings.pii_score_threshold,
        settings.pii_candidate_validation_enabled,
    )

    try:
        entities = _build_entities(text, validated_detected)
    except ApiError:
        raise
    except Exception as exc:
        raise PiiProcessingError from exc
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    return PiiContent(
        document_id=text_artifact.document_id,
        input_text_artifact_id=text_artifact.id,
        profile=settings.effective_pii_profile,
        language=settings.pii_language,
        score_threshold=settings.pii_score_threshold,
        text_char_count=len(text),
        configured_entity_types=list(configured_types),
        entities=entities,
        entity_counts=dict(sorted(counts.items())),
        tool_versions={} if flags else analyzer.tool_versions(),
        flags=flags,
        validation=PiiValidationSummary(
            enabled=validation_summary.enabled,
            kept=validation_summary.kept,
            dropped=validation_summary.dropped,
            score_down=validation_summary.score_down,
            dropped_by_reason=validation_summary.dropped_by_reason,
            score_down_by_reason=validation_summary.score_down_by_reason,
        ),
    )


def _page_text_map(text_artifact: TextArtifact) -> dict[int | None, str]:
    """Map each page number (``None`` for a non-paged document) to its exact analyzed text, so
    candidate validation can slice a local context window without re-deriving global offsets."""
    if text_artifact.content.pages:
        return {page.page_number: page.text for page in text_artifact.content.pages}
    return {None: text_artifact.content.text}


def _build_entities(
    source_text: str, validated: list[tuple[ValidatedEntity, int, int | None]]
) -> list[PiiEntity]:
    sorted_entities = sorted(
        validated,
        key=lambda item: (
            item[0].entity.start + item[1],
            item[0].entity.end + item[1],
            item[0].entity.entity_type,
            item[0].entity.recognizer,
            -item[0].entity.score,
        ),
    )
    entities: list[PiiEntity] = []
    for validated_entity, global_base, page_number in sorted_entities:
        detected_entity = validated_entity.entity
        start = detected_entity.start + global_base
        end = detected_entity.end + global_base
        if (
            detected_entity.start < 0
            or detected_entity.end <= detected_entity.start
            or end > len(source_text)
        ):
            raise PiiProcessingError
        entity_text = source_text[start:end]
        entities.append(
            PiiEntity(
                id=uuid4().hex,
                entity_type=detected_entity.entity_type,
                text=entity_text,
                start_offset=start,
                end_offset=end,
                page_number=page_number,
                page_start_offset=detected_entity.start if page_number is not None else None,
                page_end_offset=detected_entity.end if page_number is not None else None,
                score=detected_entity.score,
                recognizer=detected_entity.recognizer,
                original_score=validated_entity.original_score,
                validation_status=validated_entity.validation_status,
                validation_reasons=list(validated_entity.validation_reasons),
            )
        )
    return entities


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
