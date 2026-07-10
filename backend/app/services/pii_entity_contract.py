"""Anchor-bound review-ready PII entity contract builder (ADR-0031 Phase C, on top of ADR-0029).

Turns a document's latest immutable ``pii_result`` into a stable, review-facing
:class:`PiiEntityContractV1` of **anchor-bound** entities. Detection results are normalized against
the OCR/Text-owned Text Anchor Graph v1 (ADR-0031 Phase B) by ``pii_anchor_binding.py``: entity
identity derives from anchor identity + type where an exact binding exists, and offsets/canonical
ranges/values remain as evidence/display rather than the source of truth.

This is a pure, additive, derived view — like ``pii_grouping.py`` and ``pii_review_service.py``:

- It never mutates ``pii_result`` or its entities/offsets, and adds no detection.
- Raw text stays the primary detection source; the anchor graph is owned by OCR/Text and only read.
  Missing/partial/ambiguous anchor binding never drops an entity — it is classified, surfaced as a
  review reason, and kept. When no matching anchor graph exists for the run, identity degrades to an
  explicit evidence-only fallback (``anchor_graph_available`` is ``False``).
- Canonical reading ranges are a view-specific display projection (ADR-0029 mapping status), not
  identity. ``value`` mirrors ``PiiEntity.text`` (already on ``GET …/pii``); it appears only on the
  entity, never inside binding refs, display metadata, warnings, or provenance, and no surrounding
  text snippet is ever copied anywhere.
"""

from __future__ import annotations

from typing import cast

from app.config import Settings
from app.schemas import (
    AnchorBoundPiiEntityV1,
    DocumentTextAnchorGraphV1,
    PiiAnchorBindingReason,
    PiiAnchorBindingSummary,
    PiiEntity,
    PiiEntityContractV1,
    PiiEntityDisplay,
    PiiEntityDisplaySpan,
    PiiEntityMappingStatus,
    PiiEntityMappingSummary,
    PiiEntityProvenance,
    PiiEntityReviewReasonCode,
    PiiEntitySpan,
    PiiOverlapReason,
    PiiReviewOccurrence,
    ReviewReadyAnchorBoundPiiEntity,
    TextArtifact,
)
from app.services.artifact_service import get_latest_pii_artifact, get_latest_text_artifact
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors
from app.services.pii_review_service import PiiReviewArtifactNotFoundError, get_pii_review_result

# Anchor-binding gaps that make an entity worth a human look. ``not_applicable`` (no anchor graph)
# and ``exact`` do not force review — the entity is either solidly bound or degraded for a reason
# outside its control.
_BINDING_REVIEW_REASON: dict[str, PiiEntityReviewReasonCode] = {
    "partial": "anchor_binding_partial",
    "missing": "anchor_binding_missing",
    "ambiguous": "anchor_binding_ambiguous",
}
# Canonical display-mapping gaps, surfaced the same way as in ADR-0029. Under the anchor-first model
# these describe the reading-view projection, not identity, but still flag an incomplete display.
_MAPPING_REASON: dict[PiiEntityMappingStatus, PiiEntityReviewReasonCode] = {
    "partial": "canonical_mapping_partial",
    "missing": "canonical_mapping_missing",
    "ambiguous": "canonical_mapping_ambiguous",
}
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


def build_pii_entity_contract(settings: Settings, document_id: str) -> PiiEntityContractV1:
    """Build the anchor-bound review-ready entity contract for a document's latest PII result.

    Raises the same clean 404 as the review endpoint when the document or its PII result is missing.
    """
    review = get_pii_review_result(settings, document_id)
    artifact = get_latest_pii_artifact(settings, document_id)
    if artifact is None:  # pragma: no cover - the review call above already guaranteed one
        raise PiiReviewArtifactNotFoundError

    content = artifact.content
    package_id = content.input_text_artifact_id
    canonical_available = content.reading_text_char_count is not None
    matching_text = _matching_text_artifact(settings, document_id, package_id)
    reading_text = matching_text.content.reading_text if matching_text is not None else None
    graph = _anchor_graph(matching_text)

    bound_entities, binding_summary = bind_pii_entities_to_anchors(
        content.entities, graph, document_id=document_id
    )
    review_by_occurrence: dict[str, PiiReviewOccurrence] = {
        occurrence.occurrence_id: occurrence for occurrence in review.occurrences
    }
    entity_by_id: dict[str, PiiEntity] = {entity.id: entity for entity in content.entities}

    entities = [
        _to_review_ready(
            bound,
            review_by_occurrence,
            entity_by_id,
            canonical_available=canonical_available,
            reading_text=reading_text,
        )
        for bound in bound_entities
    ]
    binding_summary = _binding_summary(entities)

    return PiiEntityContractV1(
        document_id=document_id,
        pii_artifact_id=artifact.id,
        package_id=package_id,
        text_artifact_id=package_id,
        reading_text_available=canonical_available,
        anchor_graph_available=graph is not None,
        anchor_graph_status=(graph.validation.status if graph is not None else None),
        input_contract=content.input_contract,
        overlap_resolution=content.overlap_resolution,
        entities=entities,
        binding_summary=binding_summary,
        mapping_summary=_mapping_summary(entities),
        needs_review_count=sum(entity.display.needs_review for entity in entities),
    )


def _to_review_ready(
    bound: AnchorBoundPiiEntityV1,
    review_by_occurrence: dict[str, PiiReviewOccurrence],
    entity_by_id: dict[str, PiiEntity],
    *,
    canonical_available: bool,
    reading_text: str | None,
) -> ReviewReadyAnchorBoundPiiEntity:
    occurrence_ids = sorted(obs.detection_id for obs in bound.source_observations)
    representative = review_by_occurrence[occurrence_ids[0]]
    representative_entity = entity_by_id[occurrence_ids[0]]

    anchor_canonical_range = _anchor_display_range(bound, "canonical_reading_text")
    mapping_status = _mapping_status(
        representative_entity,
        canonical_available,
        reading_text,
        anchor_canonical_range=anchor_canonical_range,
    )
    canonical_range = _canonical_range(
        representative_entity, mapping_status, anchor_canonical_range=anchor_canonical_range
    )
    review_reason_codes = _review_reason_codes(
        bound.binding_status, mapping_status, bound.provenance
    )
    display = PiiEntityDisplay(
        preferred_text_source=(
            "canonical_reading_text" if canonical_range is not None else "technical_raw_text"
        ),
        raw_highlight_range=PiiEntitySpan(
            start=bound.raw_text_range.start, end=bound.raw_text_range.end
        ),
        canonical_highlight_range=(
            PiiEntitySpan(start=canonical_range.start, end=canonical_range.end)
            if canonical_range is not None
            else None
        ),
        display_label=bound.entity_type,
        display_context_available=canonical_range is not None,
        needs_review=bool(review_reason_codes),
        review_reason_codes=review_reason_codes,
    )
    return ReviewReadyAnchorBoundPiiEntity(
        **bound.model_dump(),
        entity_group_id=representative.entity_group_id,
        source_entity_ids=occurrence_ids,
        mapping_status=mapping_status,
        canonical_reading_text_range=canonical_range,
        review_state=representative.review_status,
        review_decision=representative.review_decision,
        decision_scope=representative.decision_scope,
        display=display,
        warnings=_entity_warnings(review_reason_codes, bound.binding_reasons, bound.provenance),
    )


def _mapping_status(
    entity: PiiEntity,
    canonical_available: bool,
    reading_text: str | None,
    *,
    anchor_canonical_range: PiiEntityDisplaySpan | None,
) -> PiiEntityMappingStatus:
    """Classify how the entity's raw span connects to the canonical reading text (display view).

    ``not_applicable`` when the run produced no canonical text at all; otherwise a mapped
    (``exact``/``projected``) or unmapped (``partial``/``missing``/``ambiguous``) state. An unmapped
    entity whose exact value appears more than once in the canonical text is ``ambiguous`` (multiple
    candidate positions), else ``missing`` — never dropped in any case.
    """
    if anchor_canonical_range is not None:
        return "exact"
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
    entity: PiiEntity,
    mapping_status: PiiEntityMappingStatus,
    *,
    anchor_canonical_range: PiiEntityDisplaySpan | None,
) -> PiiEntityDisplaySpan | None:
    if anchor_canonical_range is not None:
        return anchor_canonical_range
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
    binding_status: str,
    mapping_status: PiiEntityMappingStatus,
    provenance: PiiEntityProvenance | None,
) -> list[PiiEntityReviewReasonCode]:
    """The reasons this entity needs human review: anchor-binding gaps, display-mapping gaps, and
    cross-type overlap conflicts. Deterministic order; ``exact``/``not_applicable`` add nothing."""
    codes: list[PiiEntityReviewReasonCode] = []
    binding_reason = _BINDING_REVIEW_REASON.get(binding_status)
    if binding_reason is not None:
        codes.append(binding_reason)
    mapping_reason = _MAPPING_REASON.get(mapping_status)
    if mapping_reason is not None:
        codes.append(mapping_reason)
    if provenance is not None and provenance.review_required:
        codes.append("conflicting_entity_type")
        codes.append("ambiguous_overlap_review_required")
    return codes


def _entity_warnings(
    review_reason_codes: list[PiiEntityReviewReasonCode],
    binding_reasons: list[PiiAnchorBindingReason],
    provenance: PiiEntityProvenance | None,
) -> list[PiiEntityReviewReasonCode]:
    """Full reason-code picture: the review reasons plus informational overlap outcomes.

    Deterministic order, de-duplicated: review reasons first, then the merge reason, then the
    overlap decision. Informational codes (a merge or a stronger-candidate selection) explain what
    the deterministic resolver did without necessarily forcing review.
    """
    codes: list[PiiEntityReviewReasonCode] = list(review_reason_codes)
    for reason in binding_reasons:
        if reason != "anchor_exact_match":
            codes.append(cast(PiiEntityReviewReasonCode, reason))
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


def _anchor_display_range(
    bound: AnchorBoundPiiEntityV1, source_name: str
) -> PiiEntityDisplaySpan | None:
    display_ranges = [
        ref.source_range
        for ref in bound.anchor_refs
        if ref.source_name == source_name
        and ref.source_range is not None
        and ref.binding_role == "display_span"
    ]
    if bound.binding_status != "exact" or not display_ranges:
        return None
    if len(display_ranges) != bound.anchor_set.count:
        return None
    ordered = sorted(
        display_ranges, key=lambda source_range: (source_range.start, source_range.end)
    )
    return PiiEntityDisplaySpan(
        start=ordered[0].start,
        end=ordered[-1].end,
        projection_method="offset_map",
    )


def _mapping_summary(
    entities: list[ReviewReadyAnchorBoundPiiEntity],
) -> PiiEntityMappingSummary:
    return PiiEntityMappingSummary(
        exact=sum(entity.mapping_status == "exact" for entity in entities),
        projected=sum(entity.mapping_status == "projected" for entity in entities),
        partial=sum(entity.mapping_status == "partial" for entity in entities),
        missing=sum(entity.mapping_status == "missing" for entity in entities),
        ambiguous=sum(entity.mapping_status == "ambiguous" for entity in entities),
        not_applicable=sum(entity.mapping_status == "not_applicable" for entity in entities),
    )


def _binding_summary(
    entities: list[ReviewReadyAnchorBoundPiiEntity],
) -> PiiAnchorBindingSummary:
    total = len(entities)
    anchor_bound = sum(
        entity.identity_basis in ("anchor_exact", "anchor_partial") for entity in entities
    )
    evidence_only = sum(entity.identity_basis == "evidence_only" for entity in entities)
    exact = sum(entity.binding_status == "exact" for entity in entities)
    partial = sum(entity.binding_status == "partial" for entity in entities)
    missing = sum(entity.binding_status == "missing" for entity in entities)
    ambiguous = sum(entity.binding_status == "ambiguous" for entity in entities)
    not_applicable = sum(entity.binding_status == "not_applicable" for entity in entities)
    canonical = sum(entity.display.canonical_highlight_range is not None for entity in entities)
    layout = sum(_has_display_ref(entity, "layout_text") for entity in entities)
    return PiiAnchorBindingSummary(
        total=total,
        anchor_bound=anchor_bound,
        evidence_only=evidence_only,
        exact=exact,
        partial=partial,
        missing=missing,
        ambiguous=ambiguous,
        not_applicable=not_applicable,
        total_entities=total,
        anchor_bound_entities=anchor_bound,
        evidence_only_entities=evidence_only,
        exact_bound_entities=exact,
        partial_bound_entities=partial,
        ambiguous_bound_entities=ambiguous,
        entities_with_raw_range=total,
        entities_with_canonical_range=canonical,
        entities_with_layout_range=layout,
        missing_canonical_range_count=total - canonical,
        missing_layout_range_count=total - layout,
        binding_reason_counts=_binding_reason_counts(entities),
        warning_codes=_binding_warning_codes(entities),
        anchor_bound_ratio=_ratio(anchor_bound, total),
        exact_bound_ratio=_ratio(exact, total),
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _has_display_ref(entity: ReviewReadyAnchorBoundPiiEntity, source_name: str) -> bool:
    return any(
        ref.source_name == source_name
        and ref.source_range is not None
        and ref.binding_role == "display_span"
        for ref in entity.anchor_refs
    )


def _binding_reason_counts(entities: list[ReviewReadyAnchorBoundPiiEntity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        for reason in entity.binding_reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _binding_warning_codes(entities: list[ReviewReadyAnchorBoundPiiEntity]) -> list[str]:
    warnings: set[str] = set()
    for entity in entities:
        warnings.update(
            reason for reason in entity.binding_reasons if reason != "anchor_exact_match"
        )
        warnings.update(entity.warnings)
    return sorted(warnings)


def _matching_text_artifact(
    settings: Settings, document_id: str, package_id: str
) -> TextArtifact | None:
    """The exact text artifact this PII result was built from, or ``None`` if it changed since.

    Only a byte-matching text artifact (same id as the PII input package) has offset-compatible raw
    text, so anchors and the ambiguous/missing canonical distinction stay safe; a later OCR re-run
    (different id) degrades the run to evidence-only binding rather than binding to wrong offsets.
    """
    text_artifact = get_latest_text_artifact(settings, document_id)
    if text_artifact is None or text_artifact.id != package_id:
        return None
    return text_artifact


def _anchor_graph(
    text_artifact: TextArtifact | None,
) -> DocumentTextAnchorGraphV1 | None:
    """Build Text Anchor Graph v1 from the matching text artifact (OCR/Text owns it; read-only)."""
    if text_artifact is None:
        return None
    package = build_document_text_package(text_artifact)
    return build_document_text_anchor_graph(package)
