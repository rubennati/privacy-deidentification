"""Review-ready PII entity contract builder (ADR-0029).

Turns a document's latest immutable ``pii_result`` into a stable, review-facing
:class:`PiiEntityContractV1`: every detected entity gets a deterministic ``entity_id`` (stable for
the same document + raw span + type across re-runs), its authoritative raw span, its canonical
reading span where a mapping exists, an explicit ``mapping_status``, the deterministic overlap
provenance already recorded on the artifact, the resolved review state from the decision overlay,
and a text-free display model.

This is a pure, additive, derived view — like ``pii_grouping.py`` and ``pii_review_service.py``:

- It never mutates ``pii_result`` or its entities/offsets, and adds no detection.
- Raw text stays the primary detection source; canonical reading text is display/context/projection
  only. Missing canonical mapping never drops an entity — it is classified and flagged for review.
- ``value`` mirrors ``PiiEntity.text`` (already returned by ``GET …/pii``); it appears only on the
  entity, never inside display metadata, warnings, or provenance, and no surrounding text snippet is
  ever copied anywhere.
"""

from __future__ import annotations

import hashlib

from app.config import Settings
from app.schemas import (
    PiiEntity,
    PiiEntityContractV1,
    PiiEntityDisplay,
    PiiEntityDisplaySpan,
    PiiEntityMappingStatus,
    PiiEntityMappingSummary,
    PiiEntityProvenance,
    PiiEntityReviewReasonCode,
    PiiEntitySourceSpan,
    PiiEntitySpan,
    PiiOverlapReason,
    PiiReviewOccurrence,
    ReviewReadyPiiEntity,
)
from app.services.artifact_service import get_latest_pii_artifact, get_latest_text_artifact
from app.services.pii_review_service import PiiReviewArtifactNotFoundError, get_pii_review_result

# Overlap-decision reason codes lifted onto the review-ready entity, mapped to the review reason
# vocabulary. ``longer_span_selected``/``stronger_confidence_selected`` collapse to one code because
# a reviewer only cares that a stronger candidate was chosen, not the exact tie-break rule.
_OVERLAP_DECISION_TO_REASON: dict[PiiOverlapReason, PiiEntityReviewReasonCode] = {
    "merged_provenance": "merged_provenance",
    "longer_span_selected": "stronger_candidate_selected",
    "stronger_confidence_selected": "stronger_candidate_selected",
    "conflicting_entity_type": "conflicting_entity_type",
}
_MERGE_REASON_TO_REASON: dict[PiiOverlapReason, PiiEntityReviewReasonCode] = {
    "exact_duplicate": "exact_duplicate",
    "recognizer_duplicate": "recognizer_duplicate",
    "same_type_overlap": "same_type_overlap",
    "nested_entity": "nested_entity",
}
_MAPPING_REASON: dict[PiiEntityMappingStatus, PiiEntityReviewReasonCode] = {
    "partial": "canonical_mapping_partial",
    "missing": "canonical_mapping_missing",
    "ambiguous": "canonical_mapping_ambiguous",
}


def build_pii_entity_contract(settings: Settings, document_id: str) -> PiiEntityContractV1:
    """Build the review-ready entity contract for a document's latest PII result.

    Raises the same clean 404 as the review endpoint when the document or its PII result is missing.
    """
    review = get_pii_review_result(settings, document_id)
    artifact = get_latest_pii_artifact(settings, document_id)
    if artifact is None:  # pragma: no cover - the review call above already guaranteed one
        raise PiiReviewArtifactNotFoundError

    content = artifact.content
    package_id = content.input_text_artifact_id
    canonical_available = content.reading_text_char_count is not None
    reading_text = _canonical_reading_text(settings, document_id, package_id)
    review_by_occurrence: dict[str, PiiReviewOccurrence] = {
        occurrence.occurrence_id: occurrence for occurrence in review.occurrences
    }

    entities = [
        _build_review_ready_entity(
            entity,
            review_by_occurrence[entity.id],
            document_id=document_id,
            package_id=package_id,
            canonical_available=canonical_available,
            reading_text=reading_text,
        )
        for entity in content.entities
    ]

    return PiiEntityContractV1(
        document_id=document_id,
        pii_artifact_id=artifact.id,
        package_id=package_id,
        text_artifact_id=package_id,
        reading_text_available=canonical_available,
        input_contract=content.input_contract,
        overlap_resolution=content.overlap_resolution,
        entities=entities,
        mapping_summary=_mapping_summary(entities),
        needs_review_count=sum(entity.display.needs_review for entity in entities),
    )


def _build_review_ready_entity(
    entity: PiiEntity,
    review: PiiReviewOccurrence,
    *,
    document_id: str,
    package_id: str,
    canonical_available: bool,
    reading_text: str | None,
) -> ReviewReadyPiiEntity:
    mapping_status = _mapping_status(entity, canonical_available, reading_text)
    raw_range = PiiEntitySourceSpan(
        start=entity.start_offset,
        end=entity.end_offset,
        page_number=entity.page_number,
        page_start=entity.page_start_offset,
        page_end=entity.page_end_offset,
    )
    canonical_range = _canonical_range(entity, mapping_status)
    provenance = entity.provenance
    review_reason_codes = _review_reason_codes(mapping_status, provenance)
    display = PiiEntityDisplay(
        preferred_text_source=(
            "canonical_reading_text" if canonical_range is not None else "technical_raw_text"
        ),
        raw_highlight_range=PiiEntitySpan(start=raw_range.start, end=raw_range.end),
        canonical_highlight_range=(
            PiiEntitySpan(start=canonical_range.start, end=canonical_range.end)
            if canonical_range is not None
            else None
        ),
        display_label=entity.entity_type,
        display_context_available=canonical_range is not None,
        needs_review=bool(review_reason_codes),
        review_reason_codes=review_reason_codes,
    )
    return ReviewReadyPiiEntity(
        entity_id=_stable_entity_id(document_id, entity.entity_type, entity.start_offset,
                                    entity.end_offset),
        source_entity_id=entity.id,
        entity_group_id=review.entity_group_id,
        document_id=document_id,
        package_id=package_id,
        text_artifact_id=package_id,
        entity_type=entity.entity_type,
        value=entity.text,
        confidence=entity.score,
        detection_source=(provenance.detection_source if provenance is not None else "raw_text"),
        source_role=(provenance.source_role if provenance is not None else "primary"),
        page_number=entity.page_number,
        raw_text_range=raw_range,
        canonical_reading_text_range=canonical_range,
        mapping_status=mapping_status,
        overlap_decision=(provenance.overlap_decision if provenance is not None else None),
        provenance=provenance,
        review_state=review.review_status,
        review_decision=review.review_decision,
        decision_scope=review.decision_scope,
        display=display,
        warnings=_entity_warnings(review_reason_codes, provenance),
    )


def _mapping_status(
    entity: PiiEntity, canonical_available: bool, reading_text: str | None
) -> PiiEntityMappingStatus:
    """Classify how the entity's raw span connects to the canonical reading text.

    ``not_applicable`` when the run produced no canonical text at all; otherwise a mapped
    (``exact``/``projected``) or unmapped (``partial``/``missing``/``ambiguous``) state. An unmapped
    entity whose exact value appears more than once in the canonical text is ``ambiguous`` (multiple
    candidate positions), else ``missing`` — never dropped in any case.
    """
    if not canonical_available:
        return "not_applicable"
    if entity.projection_status == "exact":
        return "exact" if entity.projection_method == "offset_map" else "projected"
    if entity.projection_status == "partial":
        return "partial"
    if reading_text is not None and reading_text.count(entity.text) > 1:
        return "ambiguous"
    return "missing"


def _canonical_range(
    entity: PiiEntity, mapping_status: PiiEntityMappingStatus
) -> PiiEntityDisplaySpan | None:
    if mapping_status not in ("exact", "projected"):
        return None
    if entity.reading_start_offset is None or entity.reading_end_offset is None:
        return None
    return PiiEntityDisplaySpan(
        start=entity.reading_start_offset,
        end=entity.reading_end_offset,
        projection_method=entity.projection_method,
    )


def _review_reason_codes(
    mapping_status: PiiEntityMappingStatus, provenance: PiiEntityProvenance | None
) -> list[PiiEntityReviewReasonCode]:
    """The reasons this entity needs human review: mapping gaps and cross-type overlap conflicts."""
    codes: list[PiiEntityReviewReasonCode] = []
    mapping_reason = _MAPPING_REASON.get(mapping_status)
    if mapping_reason is not None:
        codes.append(mapping_reason)
    if provenance is not None and provenance.review_required:
        codes.append("conflicting_entity_type")
        codes.append("ambiguous_overlap_review_required")
    return codes


def _entity_warnings(
    review_reason_codes: list[PiiEntityReviewReasonCode], provenance: PiiEntityProvenance | None
) -> list[PiiEntityReviewReasonCode]:
    """Full reason-code picture: the review reasons plus informational overlap outcomes.

    Deterministic order, de-duplicated: review reasons first, then the merge reason, then the
    overlap decision. Informational codes (a merge or a stronger-candidate selection) explain what
    the deterministic resolver did without necessarily forcing review.
    """
    codes: list[PiiEntityReviewReasonCode] = list(review_reason_codes)
    if provenance is not None:
        if provenance.merge_reason is not None:
            merge_code = _MERGE_REASON_TO_REASON.get(provenance.merge_reason)
            if merge_code is not None:
                codes.append(merge_code)
        if provenance.overlap_decision is not None:
            decision_code = _OVERLAP_DECISION_TO_REASON.get(provenance.overlap_decision)
            if decision_code is not None:
                codes.append(decision_code)
    seen: set[str] = set()
    unique: list[PiiEntityReviewReasonCode] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique.append(code)
    return unique


def _mapping_summary(entities: list[ReviewReadyPiiEntity]) -> PiiEntityMappingSummary:
    return PiiEntityMappingSummary(
        exact=sum(entity.mapping_status == "exact" for entity in entities),
        projected=sum(entity.mapping_status == "projected" for entity in entities),
        partial=sum(entity.mapping_status == "partial" for entity in entities),
        missing=sum(entity.mapping_status == "missing" for entity in entities),
        ambiguous=sum(entity.mapping_status == "ambiguous" for entity in entities),
        not_applicable=sum(entity.mapping_status == "not_applicable" for entity in entities),
    )


def _canonical_reading_text(
    settings: Settings, document_id: str, package_id: str
) -> str | None:
    """The canonical reading text of the exact text artifact this PII result was built from.

    Only used to distinguish ``missing`` from ``ambiguous`` for unmapped entities. If the latest
    text artifact no longer matches the PII result's input package (an OCR re-run since), it is not
    used — the stored per-entity projection status still drives the mapping state safely.
    """
    text_artifact = get_latest_text_artifact(settings, document_id)
    if text_artifact is None or text_artifact.id != package_id:
        return None
    return text_artifact.content.reading_text


def _stable_entity_id(document_id: str, entity_type: str, start: int, end: int) -> str:
    """A deterministic 32-hex id for one entity, stable across re-runs of the same document.

    Keyed by document id, entity type, and raw span only — never the raw value — so the same span of
    the same type always yields the same id, while different types or spans never collide. Exact
    same-span/same-type duplicates are merged upstream by overlap resolution, so the key is unique
    within one resolved set.
    """
    digest_input = f"{document_id}\x00{entity_type}\x00{start}\x00{end}".encode()
    return hashlib.sha256(digest_input).hexdigest()[:32]
