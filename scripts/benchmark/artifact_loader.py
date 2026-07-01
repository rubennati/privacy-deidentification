"""Read-only loader for local document metadata and audit/OCR/PII artifacts.

Reads only what already exists under ``volumes/document-data`` and ``volumes/uploads``. Never
writes, deletes, or triggers any processing. Deliberately narrow: every dataclass here keeps
only counts, types, statuses, and offsets — raw extracted text (``TextContent.text``,
``TextPageResult.text``, ``PiiEntity.text``) and any ground-truth ``masked_value``/``source``
strings are never copied into these structures, so they cannot leak into a report downstream.

Artifact identity follows the same rule as the backend
(``backend/app/services/artifact_service.py``): the *latest* artifact of a given
``artifact_type`` for a document is the one with the greatest ``(created_at, id)``. Malformed or
unreadable files are skipped and recorded as a safe (filename-only) load error, never raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ARTIFACTS_DIRNAME = "artifacts"


@dataclass(frozen=True)
class LocalDocument:
    """Metadata from one ``document.json`` sidecar, plus upload-storage presence."""

    document_id: str
    display_filename: str | None
    storage_filename: str | None
    mime_type: str | None
    sha256: str | None
    size_bytes: int | None
    created_at: str | None
    upload_exists: bool
    upload_size_bytes: int | None


@dataclass(frozen=True)
class AuditPageSummary:
    page_number: int
    text_char_count: int
    has_text_layer: bool
    text_quality_status: str | None
    text_quality_score: int | None
    text_quality_reasons: tuple[str, ...]
    recommended_text_source: str | None
    needs_ocr: bool | None


@dataclass(frozen=True)
class AuditSummary:
    artifact_id: str
    created_at: str
    document_kind: str | None
    page_count: int | None
    has_text_layer: bool
    text_char_count: int
    flags: tuple[str, ...]
    pages: tuple[AuditPageSummary, ...]


@dataclass(frozen=True)
class TextPageSummary:
    page_number: int
    source: str | None
    has_text_layer: bool
    ocr_used: bool
    text_char_count: int
    word_count: int


@dataclass(frozen=True)
class TextSummary:
    artifact_id: str
    created_at: str
    source: str | None
    text_char_count: int
    word_count: int
    flags: tuple[str, ...]
    pages: tuple[TextPageSummary, ...]
    tool_versions: dict[str, str]


@dataclass(frozen=True)
class DetectedEntity:
    """One PII detection, stripped of its raw ``text`` field."""

    entity_type: str
    page_number: int | None
    start_offset: int
    end_offset: int
    page_start_offset: int | None
    page_end_offset: int | None
    recognizer: str | None
    score: float | None


@dataclass(frozen=True)
class ValidationSummary:
    """Engine-5 candidate-validation summary: counts and reason codes only, never a value."""

    enabled: bool
    kept: int
    dropped: int
    score_down: int
    dropped_by_reason: dict[str, int]
    score_down_by_reason: dict[str, int]


@dataclass(frozen=True)
class PiiSummary:
    artifact_id: str
    created_at: str
    language: str | None
    score_threshold: float | None
    text_char_count: int
    configured_entity_types: tuple[str, ...]
    entities: tuple[DetectedEntity, ...]
    entity_counts: dict[str, int]
    flags: tuple[str, ...]
    validation: ValidationSummary | None = None


@dataclass(frozen=True)
class DocumentArtifacts:
    document: LocalDocument
    audit: AuditSummary | None
    text: TextSummary | None
    pii: PiiSummary | None
    load_errors: tuple[str, ...] = field(default_factory=tuple)


def load_local_corpus(uploads_dir: Path, document_data_dir: Path) -> list[DocumentArtifacts]:
    """Load every local document's metadata and latest audit/text/pii artifact summaries."""
    if not document_data_dir.is_dir():
        return []

    results: list[DocumentArtifacts] = []
    for entry in sorted(document_data_dir.iterdir()):
        if not entry.is_dir():
            continue
        document_json = entry / "document.json"
        if not document_json.is_file():
            continue
        results.append(_load_one_document(uploads_dir, entry))
    return results


def _load_one_document(uploads_dir: Path, document_dir: Path) -> DocumentArtifacts:
    document_id = document_dir.name
    errors: list[str] = []

    raw_document = _read_json(document_dir / "document.json")
    if raw_document is None:
        errors.append("document.json:unreadable_or_invalid_json")
        raw_document = {}

    storage_filename = _dig(raw_document, "original_artifact", "storage_filename")
    upload_path = uploads_dir / storage_filename if isinstance(storage_filename, str) else None
    upload_exists = bool(upload_path and upload_path.is_file())
    upload_size_bytes = upload_path.stat().st_size if upload_exists and upload_path else None

    document = LocalDocument(
        document_id=document_id,
        display_filename=_as_str(raw_document.get("filename")),
        storage_filename=_as_str(storage_filename),
        mime_type=_as_str(raw_document.get("detected_mime_type")),
        sha256=_as_str(raw_document.get("sha256")),
        size_bytes=_as_int(raw_document.get("size")),
        created_at=_as_str(raw_document.get("uploaded_at")),
        upload_exists=upload_exists,
        upload_size_bytes=upload_size_bytes,
    )

    artifacts_dir = document_dir / _ARTIFACTS_DIRNAME
    audit = text = pii = None
    if artifacts_dir.is_dir():
        audit, audit_errors = _latest_artifact(artifacts_dir, "audit_result", _parse_audit)
        text, text_errors = _latest_artifact(artifacts_dir, "text_result", _parse_text)
        pii, pii_errors = _latest_artifact(artifacts_dir, "pii_result", _parse_pii)
        errors.extend(audit_errors + text_errors + pii_errors)

    return DocumentArtifacts(
        document=document,
        audit=audit,
        text=text,
        pii=pii,
        load_errors=tuple(errors),
    )


def _latest_artifact(
    artifacts_dir: Path,
    artifact_type: str,
    parse: Any,
) -> tuple[Any | None, list[str]]:
    errors: list[str] = []
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(artifacts_dir.glob("*.json")):
        raw = _read_json(path)
        if raw is None:
            errors.append(f"{path.name}:unreadable_or_invalid_json")
            continue
        if raw.get("artifact_type") != artifact_type:
            continue
        created_at = raw.get("created_at")
        artifact_id = raw.get("id")
        if not isinstance(created_at, str) or not isinstance(artifact_id, str):
            errors.append(f"{path.name}:missing_id_or_created_at")
            continue
        candidates.append((created_at, artifact_id, raw))

    if not candidates:
        return None, errors

    _, _, latest_raw = max(candidates, key=lambda item: (item[0], item[1]))
    try:
        return parse(latest_raw), errors
    except (KeyError, TypeError, ValueError):
        errors.append(f"{artifact_type}:malformed_content")
        return None, errors


def _parse_audit(raw: dict[str, Any]) -> AuditSummary:
    content = raw.get("content") or {}
    pages = tuple(
        AuditPageSummary(
            page_number=int(page["page_number"]),
            text_char_count=int(page.get("text_char_count", 0)),
            has_text_layer=bool(page.get("has_text_layer", False)),
            text_quality_status=_as_str(page.get("text_quality_status")),
            text_quality_score=_as_int(page.get("text_quality_score")),
            text_quality_reasons=tuple(page.get("text_quality_reasons") or ()),
            recommended_text_source=_as_str(page.get("recommended_text_source")),
            needs_ocr=page.get("needs_ocr"),
        )
        for page in content.get("pages") or ()
    )
    return AuditSummary(
        artifact_id=str(raw["id"]),
        created_at=str(raw["created_at"]),
        document_kind=_as_str(content.get("document_kind")),
        page_count=_as_int(content.get("page_count")),
        has_text_layer=bool(content.get("has_text_layer", False)),
        text_char_count=int(content.get("text_char_count", 0)),
        flags=tuple(content.get("flags") or ()),
        pages=pages,
    )


def _parse_text(raw: dict[str, Any]) -> TextSummary:
    content = raw.get("content") or {}
    pages = tuple(
        TextPageSummary(
            page_number=int(page["page_number"]),
            source=_as_str(page.get("source")),
            has_text_layer=bool(page.get("has_text_layer", False)),
            ocr_used=bool(page.get("ocr_used", False)),
            text_char_count=int(page.get("text_char_count", 0)),
            # Word count only: the raw page text is read transiently here to derive a count and
            # is never assigned to a field, so it cannot propagate into a report.
            word_count=_word_count(page.get("text")),
        )
        for page in content.get("pages") or ()
    )
    return TextSummary(
        artifact_id=str(raw["id"]),
        created_at=str(raw["created_at"]),
        source=_as_str(content.get("source")),
        text_char_count=int(content.get("text_char_count", 0)),
        word_count=_word_count(content.get("text")),
        flags=tuple(content.get("flags") or ()),
        pages=pages,
        tool_versions=dict(content.get("tool_versions") or {}),
    )


def _word_count(text: Any) -> int:
    return len(text.split()) if isinstance(text, str) else 0


def _parse_pii(raw: dict[str, Any]) -> PiiSummary:
    content = raw.get("content") or {}
    entities = tuple(
        DetectedEntity(
            entity_type=str(entity["entity_type"]),
            page_number=entity.get("page_number"),
            start_offset=int(entity["start_offset"]),
            end_offset=int(entity["end_offset"]),
            page_start_offset=entity.get("page_start_offset"),
            page_end_offset=entity.get("page_end_offset"),
            recognizer=_as_str(entity.get("recognizer")),
            score=entity.get("score"),
        )
        for entity in content.get("entities") or ()
    )
    return PiiSummary(
        artifact_id=str(raw["id"]),
        created_at=str(raw["created_at"]),
        language=_as_str(content.get("language")),
        score_threshold=content.get("score_threshold"),
        text_char_count=int(content.get("text_char_count", 0)),
        configured_entity_types=tuple(content.get("configured_entity_types") or ()),
        entities=entities,
        entity_counts=dict(content.get("entity_counts") or {}),
        flags=tuple(content.get("flags") or ()),
        validation=_parse_validation(content.get("validation")),
    )


def _parse_validation(raw: Any) -> ValidationSummary | None:
    if not isinstance(raw, dict):
        return None
    return ValidationSummary(
        enabled=bool(raw.get("enabled", False)),
        kept=int(raw.get("kept", 0)),
        dropped=int(raw.get("dropped", 0)),
        score_down=int(raw.get("score_down", 0)),
        dropped_by_reason={
            str(reason): int(count) for reason, count in (raw.get("dropped_by_reason") or {}).items()
        },
        score_down_by_reason={
            str(reason): int(count)
            for reason, count in (raw.get("score_down_by_reason") or {}).items()
        },
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _dig(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
