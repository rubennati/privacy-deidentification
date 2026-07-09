"""Anchor-bound PII entity normalization (ADR-0031 Phase C).

Turns offset-based PII detections (detection *evidence*) plus the OCR/Text-owned Text Anchor Graph
v1 (ADR-0031 Phase B) into stable, review-ready **anchor-bound PII entities**. A detection is an
observation on a text view; the durable domain entity is built from text anchors + that evidence.

Binding strategy (deterministic, text-free):

- Detection ranges are the entity's authoritative technical-raw offsets — raw stays the primary and
  only active detection input. Each detection span is matched to the raw ranges of anchors.
- Detection range aligned to whole anchors → ``exact``; cutting across anchors → ``partial``; no
  overlap → ``missing``; incompatible (mutually overlapping) candidate anchors → ``ambiguous``. When
  no anchor graph is available for the run, every entity is ``not_applicable`` (evidence-only).
- Repeated identical values are **never** globally married by string equality: binding is by raw
  offset overlap only, so two occurrences of the same word remain two entities bound to their own
  anchors.
- If the same anchor set + entity type is observed by several recognizers/sources, their provenance
  is **merged** into one entity rather than creating independent domain entities. Different entity
  types over the same anchor set stay separate entities.

Identity: an exact binding derives ``entity_id`` from the ordered anchor ids + type (anchor
identity, offset-independent); a partial binding additionally pins the raw span; an evidence-only
fallback uses document + type + raw span (matching the ADR-0029 stable id, so review continuity
holds). No raw token text ever enters an id or any binding metadata.

This module never mutates the anchor graph or the PII entities; it is a pure function of its inputs
with deterministic output ordering and stable ids.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from app.schemas import (
    AnchorBoundPiiEntityV1,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorSourceName,
    PiiAnchorBindingReason,
    PiiAnchorBindingRole,
    PiiAnchorBindingStatus,
    PiiAnchorBindingSummary,
    PiiEntity,
    PiiEntityAnchorRef,
    PiiEntityAnchorSet,
    PiiEntityIdentityBasis,
    PiiEntityProvenance,
    PiiEntitySourceSpan,
    PiiEntitySpan,
    PiiSourceObservation,
)

_RAW_SOURCE: DocumentTextAnchorSourceName = "technical_raw_text"
_CANONICAL_SOURCE: DocumentTextAnchorSourceName = "canonical_reading_text"


@dataclass(frozen=True)
class _RawAnchor:
    """One raw text-anchor reduced to what binding needs: its id, raw range, and canonical range."""

    anchor_id: str
    start: int
    end: int
    canonical_range: tuple[int, int] | None


@dataclass(frozen=True)
class _BoundObservation:
    """One detection with its binding, before same-identity observations are merged."""

    entity: PiiEntity
    binding_status: PiiAnchorBindingStatus
    binding_reasons: tuple[PiiAnchorBindingReason, ...]
    identity_basis: PiiEntityIdentityBasis
    anchor_ids: tuple[str, ...]
    anchor_refs: tuple[PiiEntityAnchorRef, ...]


def bind_pii_entities_to_anchors(
    entities: Sequence[PiiEntity],
    graph: DocumentTextAnchorGraphV1 | None,
    *,
    document_id: str,
) -> tuple[list[AnchorBoundPiiEntityV1], PiiAnchorBindingSummary]:
    """Normalize detection evidence into anchor-bound PII entities plus a binding summary.

    ``graph`` is ``None`` when no Text Anchor Graph could be built for this run (e.g. the
    OCR/Text artifact was re-run since detection): every entity then binds ``not_applicable``
    (evidence-only), and nothing is dropped.
    """
    raw_anchors, raw_available, raw_char_count = _raw_anchors(graph)
    observations = [
        _bind_observation(
            entity,
            raw_anchors,
            raw_available=raw_available,
            raw_char_count=raw_char_count,
        )
        for entity in entities
    ]
    bound = _merge_observations(observations, document_id=document_id)
    bound.sort(
        key=lambda entity: (
            entity.raw_text_range.start,
            entity.raw_text_range.end,
            entity.entity_type,
            entity.entity_id,
        )
    )
    return bound, _summary(bound)


def _raw_anchors(
    graph: DocumentTextAnchorGraphV1 | None,
) -> tuple[tuple[_RawAnchor, ...], bool, int]:
    """Extract raw-text anchors (with any canonical display range) sorted by raw offset."""
    if graph is None:
        return (), False, 0
    raw_source = next(
        (source for source in graph.sources if source.source_name == _RAW_SOURCE), None
    )
    raw_available = raw_source is not None and raw_source.available
    raw_char_count = (raw_source.text_char_count or 0) if raw_source is not None else 0

    anchors: list[_RawAnchor] = []
    for anchor in graph.anchors:
        raw_range = next(
            (r for r in anchor.source_ranges if r.source_name == _RAW_SOURCE), None
        )
        if raw_range is None:
            continue
        canonical = next(
            (r for r in anchor.source_ranges if r.source_name == _CANONICAL_SOURCE), None
        )
        anchors.append(
            _RawAnchor(
                anchor_id=anchor.anchor_id,
                start=raw_range.start,
                end=raw_range.end,
                canonical_range=(
                    (canonical.start, canonical.end) if canonical is not None else None
                ),
            )
        )
    anchors.sort(key=lambda anchor: (anchor.start, anchor.end, anchor.anchor_id))
    return tuple(anchors), raw_available, raw_char_count


def _bind_observation(
    entity: PiiEntity,
    raw_anchors: Sequence[_RawAnchor],
    *,
    raw_available: bool,
    raw_char_count: int,
) -> _BoundObservation:
    if not raw_available:
        return _evidence_only(
            entity, "not_applicable", ("source_not_available", "binding_not_required")
        )
    if entity.end_offset > raw_char_count:
        # The stored entity offsets no longer fit the graph's raw text: keep it as evidence, never
        # bind it to a wrong anchor.
        return _evidence_only(
            entity, "missing", ("invalid_entity_range", "detection_evidence_only")
        )

    overlapping = [
        anchor
        for anchor in raw_anchors
        if anchor.start < entity.end_offset and entity.start_offset < anchor.end
    ]
    if not overlapping:
        return _evidence_only(entity, "missing", ("anchor_missing", "detection_evidence_only"))
    if _mutually_overlapping(overlapping):
        refs = tuple(
            _anchor_ref(anchor, "ambiguous", "inferred_span", ("anchor_ambiguous",))
            for anchor in overlapping
        )
        return _BoundObservation(
            entity=entity,
            binding_status="ambiguous",
            binding_reasons=("anchor_ambiguous", "repeated_token_ambiguity"),
            identity_basis="evidence_only",
            anchor_ids=(),
            anchor_refs=refs,
        )

    fully_contained = all(
        entity.start_offset <= anchor.start and anchor.end <= entity.end_offset
        for anchor in overlapping
    )
    aligned = (
        overlapping[0].start == entity.start_offset
        and overlapping[-1].end == entity.end_offset
    )
    if fully_contained and aligned:
        return _anchor_bound(entity, overlapping, status="exact", basis="anchor_exact")
    return _anchor_bound(entity, overlapping, status="partial", basis="anchor_partial")


def _anchor_bound(
    entity: PiiEntity,
    overlapping: Sequence[_RawAnchor],
    *,
    status: PiiAnchorBindingStatus,
    basis: PiiEntityIdentityBasis,
) -> _BoundObservation:
    refs: list[PiiEntityAnchorRef] = []
    for anchor in overlapping:
        contained = entity.start_offset <= anchor.start and anchor.end <= entity.end_offset
        anchor_status: PiiAnchorBindingStatus = "exact" if contained else "partial"
        reason: PiiAnchorBindingReason = (
            "anchor_exact_match" if contained else "anchor_partial_overlap"
        )
        refs.append(_anchor_ref(anchor, anchor_status, "entity_span", (reason,)))
        if anchor.canonical_range is not None:
            refs.append(_canonical_display_ref(anchor, anchor_status))
    reason_code: PiiAnchorBindingReason = (
        "anchor_exact_match" if status == "exact" else "anchor_partial_overlap"
    )
    return _BoundObservation(
        entity=entity,
        binding_status=status,
        binding_reasons=(reason_code,),
        identity_basis=basis,
        anchor_ids=tuple(anchor.anchor_id for anchor in overlapping),
        anchor_refs=tuple(refs),
    )


def _evidence_only(
    entity: PiiEntity,
    status: PiiAnchorBindingStatus,
    reasons: tuple[PiiAnchorBindingReason, ...],
) -> _BoundObservation:
    return _BoundObservation(
        entity=entity,
        binding_status=status,
        binding_reasons=reasons,
        identity_basis="evidence_only",
        anchor_ids=(),
        anchor_refs=(),
    )


def _anchor_ref(
    anchor: _RawAnchor,
    status: PiiAnchorBindingStatus,
    role: PiiAnchorBindingRole,
    reasons: tuple[PiiAnchorBindingReason, ...],
) -> PiiEntityAnchorRef:
    return PiiEntityAnchorRef(
        anchor_id=anchor.anchor_id,
        source_name=_RAW_SOURCE,
        source_range=PiiEntitySpan(start=anchor.start, end=anchor.end),
        binding_status=status,
        binding_role=role,
        confidence=1.0 if status == "exact" else 0.5,
        reason_codes=list(reasons),
    )


def _canonical_display_ref(
    anchor: _RawAnchor, status: PiiAnchorBindingStatus
) -> PiiEntityAnchorRef:
    assert anchor.canonical_range is not None
    start, end = anchor.canonical_range
    return PiiEntityAnchorRef(
        anchor_id=anchor.anchor_id,
        source_name=_CANONICAL_SOURCE,
        source_range=PiiEntitySpan(start=start, end=end),
        binding_status=status,
        binding_role="display_span",
        confidence=None,
        reason_codes=[],
    )


def _mutually_overlapping(anchors: Sequence[_RawAnchor]) -> bool:
    """True when candidate anchors overlap, so no single anchor set is implied."""
    ordered = sorted(anchors, key=lambda anchor: (anchor.start, anchor.end))
    return any(right.start < left.end for left, right in pairwise(ordered))


def _merge_observations(
    observations: Sequence[_BoundObservation], *, document_id: str
) -> list[AnchorBoundPiiEntityV1]:
    """Merge observations that share the same entity identity into one anchor-bound entity."""
    groups: dict[tuple[object, ...], list[_BoundObservation]] = {}
    order: list[tuple[object, ...]] = []
    for observation in observations:
        key = _identity_key(observation)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(observation)
    return [_build_entity(groups[key], document_id=document_id) for key in order]


def _identity_key(observation: _BoundObservation) -> tuple[object, ...]:
    entity = observation.entity
    if observation.identity_basis == "anchor_exact":
        return ("anchor_exact", entity.entity_type, observation.anchor_ids)
    if observation.identity_basis == "anchor_partial":
        return (
            "anchor_partial",
            entity.entity_type,
            observation.anchor_ids,
            entity.start_offset,
            entity.end_offset,
        )
    # Evidence-only entities key on document + type + raw span (matches the ADR-0029 stable id), so
    # repeated identical values at different offsets never collapse into one identity.
    return ("evidence_only", entity.entity_type, entity.start_offset, entity.end_offset)


def _build_entity(
    members: Sequence[_BoundObservation], *, document_id: str
) -> AnchorBoundPiiEntityV1:
    ordered = sorted(members, key=lambda observation: observation.entity.id)
    representative = ordered[0]
    entity = representative.entity
    anchor_ids = representative.anchor_ids
    entity_id = _entity_id(
        document_id,
        representative.identity_basis,
        entity.entity_type,
        anchor_ids,
        entity.start_offset,
        entity.end_offset,
    )
    return AnchorBoundPiiEntityV1(
        entity_id=entity_id,
        entity_type=entity.entity_type,
        identity_basis=representative.identity_basis,
        binding_status=representative.binding_status,
        binding_reasons=list(representative.binding_reasons),
        anchor_set=PiiEntityAnchorSet(
            anchor_ids=list(anchor_ids),
            binding_status=representative.binding_status,
            count=len(anchor_ids),
        ),
        anchor_refs=list(representative.anchor_refs),
        source_observations=[_observation(member) for member in ordered],
        provenance=_merge_provenance(ordered),
        confidence=max(member.entity.score for member in ordered),
        value=entity.text,
        raw_text_range=PiiEntitySourceSpan(
            start=entity.start_offset,
            end=entity.end_offset,
            page_number=entity.page_number,
            page_start=entity.page_start_offset,
            page_end=entity.page_end_offset,
        ),
    )


def _observation(member: _BoundObservation) -> PiiSourceObservation:
    entity = member.entity
    return PiiSourceObservation(
        detection_id=entity.id,
        recognizer=entity.recognizer,
        entity_type=entity.entity_type,
        source_name=_RAW_SOURCE,
        detection_source=(
            entity.provenance.detection_source if entity.provenance is not None else "raw_text"
        ),
        detection_role="primary",
        source_range=PiiEntitySourceSpan(
            start=entity.start_offset,
            end=entity.end_offset,
            page_number=entity.page_number,
            page_start=entity.page_start_offset,
            page_end=entity.page_end_offset,
        ),
        confidence=entity.score,
        binding_status=member.binding_status,
        binding_reasons=list(member.binding_reasons),
        provenance=entity.provenance,
    )


def _merge_provenance(members: Sequence[_BoundObservation]) -> PiiEntityProvenance | None:
    provenances = [
        member.entity.provenance
        for member in members
        if member.entity.provenance is not None
    ]
    if not provenances:
        return None
    if len(members) == 1:
        return provenances[0]
    recognizers = sorted(
        {recognizer for provenance in provenances for recognizer in provenance.recognizers}
        | {member.entity.recognizer for member in members}
    )
    superseded = sorted(
        {
            candidate_id
            for provenance in provenances
            for candidate_id in provenance.superseded_candidate_ids
        }
    )
    representative = provenances[0]
    return PiiEntityProvenance(
        detection_source=representative.detection_source,
        source_role=representative.source_role,
        recognizers=recognizers,
        candidate_count=sum(provenance.candidate_count for provenance in provenances),
        merge_reason=next(
            (provenance.merge_reason for provenance in provenances if provenance.merge_reason),
            None,
        ),
        overlap_decision=next(
            (
                provenance.overlap_decision
                for provenance in provenances
                if provenance.overlap_decision
            ),
            None,
        ),
        review_required=any(provenance.review_required for provenance in provenances),
        superseded_candidate_ids=superseded,
    )


def _entity_id(
    document_id: str,
    basis: PiiEntityIdentityBasis,
    entity_type: str,
    anchor_ids: Sequence[str],
    raw_start: int,
    raw_end: int,
) -> str:
    """Deterministic 32-hex entity id. Anchor-derived when bound, else the ADR-0029 evidence id."""
    if basis == "anchor_exact":
        material = f"{document_id}\x00anchor_exact\x00{entity_type}\x00{'|'.join(anchor_ids)}"
    elif basis == "anchor_partial":
        material = (
            f"{document_id}\x00anchor_partial\x00{entity_type}\x00{'|'.join(anchor_ids)}"
            f"\x00{raw_start}\x00{raw_end}"
        )
    else:
        material = f"{document_id}\x00{entity_type}\x00{raw_start}\x00{raw_end}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def _summary(entities: Sequence[AnchorBoundPiiEntityV1]) -> PiiAnchorBindingSummary:
    return PiiAnchorBindingSummary(
        total=len(entities),
        anchor_bound=sum(
            entity.identity_basis in ("anchor_exact", "anchor_partial") for entity in entities
        ),
        evidence_only=sum(entity.identity_basis == "evidence_only" for entity in entities),
        exact=sum(entity.binding_status == "exact" for entity in entities),
        partial=sum(entity.binding_status == "partial" for entity in entities),
        missing=sum(entity.binding_status == "missing" for entity in entities),
        ambiguous=sum(entity.binding_status == "ambiguous" for entity in entities),
        not_applicable=sum(entity.binding_status == "not_applicable" for entity in entities),
    )
