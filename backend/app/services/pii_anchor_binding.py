"""Anchor-bound PII entity normalization (ADR-0031 Phase C).

Turns offset-based PII detections (detection *evidence*) plus the OCR/Text-owned Text Anchor Graph
v1 (ADR-0031 Phase B) into stable, review-ready **anchor-bound PII entities**. A detection is an
observation on a text view; the durable domain entity is built from text anchors + that evidence.

Binding strategy (deterministic, text-free):

- Detection ranges are the entity's authoritative technical-raw offsets — raw stays the primary and
  only active detection input. Each detection span is matched to the raw ranges of anchors.
- Detection range fully containing whole anchors → ``exact`` (trailing/leading non-semantic slack —
  whitespace the tokenizer never anchors — never counts against this); cutting across an anchor →
  ``partial``; no overlap → ``missing``; incompatible (mutually overlapping) candidate anchors →
  ``ambiguous``. When no anchor graph is available for the run, every entity is ``not_applicable``
  (evidence-only).
- An exact entity's canonical/layout display range is emitted whenever its own first and last raw
  anchors (boundary evidence) both resolve to that view — an interior anchor lacking one (e.g. a
  repeated word that is independently ambiguous on its own) does not block the entity-level range;
  it stays flagged via ``repeated_token_ambiguity`` instead of silently destroying the projection.
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
    DocumentTextAnchorStatus,
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
_LAYOUT_SOURCE: DocumentTextAnchorSourceName = "layout_text"
_REASON_ORDER: tuple[PiiAnchorBindingReason, ...] = (
    "anchor_exact_match",
    "anchor_partial_overlap",
    "anchor_missing",
    "anchor_ambiguous",
    "canonical_range_missing",
    "layout_range_missing",
    "evidence_only_identity",
    "source_range_missing",
    "text_anchor_graph_missing",
    "text_anchor_graph_degraded",
    "repeated_token_ambiguity",
    "reading_text_mapping_missing",
    "layout_mapping_unavailable",
    "source_not_available",
    "invalid_entity_range",
    "detection_evidence_only",
    "binding_not_required",
)


@dataclass(frozen=True)
class _RawAnchor:
    """One raw text-anchor reduced to what binding needs: its id, raw range, and canonical range.

    ``canonical_mapping_status``/``layout_mapping_status`` carry the underlying
    ``DocumentTextAnchorRange.mapping_status`` for the respective view range (``exact`` for a
    byte-identical row, ``normalized``/``merged`` for a reformatted/unioned one) so a display range
    built from this anchor can honestly say whether it is byte-exact -- never silently upgraded.
    """

    anchor_id: str
    start: int
    end: int
    canonical_range: tuple[int, int] | None
    canonical_mapping_status: DocumentTextAnchorStatus | None
    layout_range: tuple[int, int] | None
    layout_mapping_status: DocumentTextAnchorStatus | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _AnchorContext:
    """Text-free graph facts needed to bind detections and explain display-range gaps."""

    graph_available: bool
    graph_degraded: bool
    raw_available: bool
    raw_char_count: int
    canonical_available: bool
    layout_available: bool
    raw_anchors: tuple[_RawAnchor, ...]


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
    context = _anchor_context(graph)
    observations = [
        _bind_observation(
            entity,
            context,
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


def _anchor_context(graph: DocumentTextAnchorGraphV1 | None) -> _AnchorContext:
    """Extract source availability and raw anchors sorted by raw offset."""
    if graph is None:
        return _AnchorContext(
            graph_available=False,
            graph_degraded=False,
            raw_available=False,
            raw_char_count=0,
            canonical_available=False,
            layout_available=False,
            raw_anchors=(),
        )
    sources = {source.source_name: source for source in graph.sources}
    raw_source = sources.get(_RAW_SOURCE)
    canonical_source = sources.get(_CANONICAL_SOURCE)
    layout_source = sources.get(_LAYOUT_SOURCE)
    raw_available = raw_source is not None and raw_source.available
    raw_char_count = (raw_source.text_char_count or 0) if raw_source is not None else 0
    canonical_available = canonical_source is not None and canonical_source.available
    layout_available = layout_source is not None and layout_source.available

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
        layout = next(
            (r for r in anchor.source_ranges if r.source_name == _LAYOUT_SOURCE), None
        )
        anchors.append(
            _RawAnchor(
                anchor_id=anchor.anchor_id,
                start=raw_range.start,
                end=raw_range.end,
                canonical_range=(
                    (canonical.start, canonical.end) if canonical is not None else None
                ),
                canonical_mapping_status=(
                    canonical.mapping_status if canonical is not None else None
                ),
                layout_range=((layout.start, layout.end) if layout is not None else None),
                layout_mapping_status=(layout.mapping_status if layout is not None else None),
                warnings=tuple(anchor.warnings),
            )
        )
    anchors.sort(key=lambda anchor: (anchor.start, anchor.end, anchor.anchor_id))
    return _AnchorContext(
        graph_available=True,
        graph_degraded=graph.validation.status != "valid",
        raw_available=raw_available,
        raw_char_count=raw_char_count,
        canonical_available=canonical_available,
        layout_available=layout_available,
        raw_anchors=tuple(anchors),
    )


def _bind_observation(
    entity: PiiEntity,
    context: _AnchorContext,
) -> _BoundObservation:
    if not context.graph_available:
        return _evidence_only(
            entity,
            "not_applicable",
            ("text_anchor_graph_missing", "evidence_only_identity"),
        )
    if not context.raw_available:
        return _evidence_only(
            entity,
            "missing",
            ("source_not_available", "source_range_missing", "evidence_only_identity"),
        )
    if entity.end_offset > context.raw_char_count:
        # The stored entity offsets no longer fit the graph's raw text: keep it as evidence, never
        # bind it to a wrong anchor.
        return _evidence_only(
            entity,
            "missing",
            ("source_range_missing", "invalid_entity_range", "evidence_only_identity"),
        )

    overlapping = [
        anchor
        for anchor in context.raw_anchors
        if anchor.start < entity.end_offset and entity.start_offset < anchor.end
    ]
    if not overlapping:
        return _evidence_only(
            entity,
            "missing",
            _ordered_reasons(
                (
                    "anchor_missing",
                    "evidence_only_identity",
                    *_graph_reasons(context),
                    *_range_reasons(context, canonical_bridgeable=False, layout_bridgeable=False),
                )
            ),
        )
    if _mutually_overlapping(overlapping):
        reasons: tuple[PiiAnchorBindingReason, ...] = _ordered_reasons(
            (
                "anchor_ambiguous",
                *_repeated_token_reasons(overlapping),
                "evidence_only_identity",
                *_graph_reasons(context),
                *_range_reasons(context, canonical_bridgeable=False, layout_bridgeable=False),
            )
        )
        refs = tuple(
            _anchor_ref(anchor, "ambiguous", "inferred_span", ("anchor_ambiguous",))
            for anchor in overlapping
        )
        return _BoundObservation(
            entity=entity,
            binding_status="ambiguous",
            binding_reasons=reasons,
            identity_basis="evidence_only",
            anchor_ids=(),
            anchor_refs=refs,
        )

    # A detection's declared span may run past its last (or before its first) whole-token anchor
    # into pure non-semantic slack. The tokenizer that builds the anchor graph gives every
    # non-whitespace character its own anchor (falling back to a single-character "symbol" anchor),
    # so any raw offset range between ``overlapping`` anchors that carries no anchor of its own is
    # guaranteed to be whitespace-only -- there is nothing else it could be. That means
    # ``fully_contained`` (every overlapping anchor sits completely inside the detection's range) is
    # sufficient on its own to call the binding exact: requiring the edges to match exactly on top
    # of that would only reject trailing/leading whitespace, never a genuine partial token cut
    # (``fully_contained`` already catches that, since the cut anchor's end exceeds the range).
    fully_contained = all(
        entity.start_offset <= anchor.start and anchor.end <= entity.end_offset
        for anchor in overlapping
    )
    if fully_contained:
        return _anchor_bound(
            entity, overlapping, context=context, status="exact", basis="anchor_exact"
        )
    return _anchor_bound(
        entity, overlapping, context=context, status="partial", basis="anchor_partial"
    )


def _anchor_bound(
    entity: PiiEntity,
    overlapping: Sequence[_RawAnchor],
    *,
    context: _AnchorContext,
    status: PiiAnchorBindingStatus,
    basis: PiiEntityIdentityBasis,
) -> _BoundObservation:
    refs: list[PiiEntityAnchorRef] = []
    emit_display_refs = status == "exact"
    # A multi-token entity's own boundary anchors (first/last in raw order) resolving to canonical
    # ranges is enough to safely bridge the entity's canonical/layout display range end to end, even
    # when an anchor *between* them individually lacks one -- e.g. a word that also occurs elsewhere
    # in the document makes that single anchor's own identity ambiguous in isolation. The interior
    # anchor's ambiguity is never hidden or resolved by this: it stays "ambiguous" in the anchor
    # graph and keeps flagging ``repeated_token_ambiguity`` below. Only the entity-level display
    # envelope uses the stronger boundary evidence a standalone anchor lookup doesn't have access
    # to. Requiring every constituent anchor to independently resolve is unnecessary here.
    canonical_bridgeable = (
        emit_display_refs
        and bool(overlapping)
        and overlapping[0].canonical_range is not None
        and overlapping[-1].canonical_range is not None
    )
    layout_bridgeable = (
        emit_display_refs
        and bool(overlapping)
        and overlapping[0].layout_range is not None
        and overlapping[-1].layout_range is not None
    )
    for anchor in overlapping:
        contained = entity.start_offset <= anchor.start and anchor.end <= entity.end_offset
        anchor_status: PiiAnchorBindingStatus = "exact" if contained else "partial"
        reason: PiiAnchorBindingReason = (
            "anchor_exact_match" if contained else "anchor_partial_overlap"
        )
        refs.append(_anchor_ref(anchor, anchor_status, "entity_span", (reason,)))
        if canonical_bridgeable and anchor.canonical_range is not None:
            refs.append(_display_ref(anchor, _CANONICAL_SOURCE, anchor_status))
        if layout_bridgeable and anchor.layout_range is not None:
            refs.append(_display_ref(anchor, _LAYOUT_SOURCE, anchor_status))
    reason_code: PiiAnchorBindingReason = (
        "anchor_exact_match" if status == "exact" else "anchor_partial_overlap"
    )
    reasons = _ordered_reasons(
        (
            reason_code,
            *_graph_reasons(context),
            *_repeated_token_reasons(overlapping),
            *_range_reasons(
                context,
                canonical_bridgeable=canonical_bridgeable,
                layout_bridgeable=layout_bridgeable,
            ),
        )
    )
    return _BoundObservation(
        entity=entity,
        binding_status=status,
        binding_reasons=reasons,
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


def _display_ref(
    anchor: _RawAnchor, source_name: DocumentTextAnchorSourceName, status: PiiAnchorBindingStatus
) -> PiiEntityAnchorRef:
    source_range = (
        anchor.canonical_range if source_name == _CANONICAL_SOURCE else anchor.layout_range
    )
    assert source_range is not None
    mapping_status = (
        anchor.canonical_mapping_status
        if source_name == _CANONICAL_SOURCE
        else anchor.layout_mapping_status
    )
    start, end = source_range
    return PiiEntityAnchorRef(
        anchor_id=anchor.anchor_id,
        source_name=source_name,
        source_range=PiiEntitySpan(start=start, end=end),
        binding_status=status,
        binding_role="display_span",
        confidence=None,
        reason_codes=[],
        mapping_status=mapping_status,
    )


def _graph_reasons(context: _AnchorContext) -> tuple[PiiAnchorBindingReason, ...]:
    if context.graph_degraded:
        return ("text_anchor_graph_degraded",)
    return ()


def _repeated_token_reasons(
    anchors: Sequence[_RawAnchor],
) -> tuple[PiiAnchorBindingReason, ...]:
    if any("ambiguous_repeated_token" in anchor.warnings for anchor in anchors):
        return ("repeated_token_ambiguity",)
    return ()


def _range_reasons(
    context: _AnchorContext, *, canonical_bridgeable: bool, layout_bridgeable: bool
) -> tuple[PiiAnchorBindingReason, ...]:
    reasons: list[PiiAnchorBindingReason] = []
    if not canonical_bridgeable:
        reasons.append("canonical_range_missing")
        if context.canonical_available:
            reasons.append("reading_text_mapping_missing")
        else:
            reasons.append("source_not_available")

    if not layout_bridgeable:
        reasons.append("layout_range_missing")
        if context.layout_available:
            reasons.append("layout_mapping_unavailable")
        else:
            reasons.append("source_not_available")
    return tuple(reasons)


def _ordered_reasons(
    reasons: Sequence[PiiAnchorBindingReason],
) -> tuple[PiiAnchorBindingReason, ...]:
    present = set(reasons)
    return tuple(reason for reason in _REASON_ORDER if reason in present)


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
    canonical_count = sum(_has_display_ref(entity, _CANONICAL_SOURCE) for entity in entities)
    layout_count = sum(_has_display_ref(entity, _LAYOUT_SOURCE) for entity in entities)
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
        entities_with_canonical_range=canonical_count,
        entities_with_layout_range=layout_count,
        missing_canonical_range_count=total - canonical_count,
        missing_layout_range_count=total - layout_count,
        binding_reason_counts=_binding_reason_counts(entities),
        warning_codes=_warning_codes(entities),
        anchor_bound_ratio=_ratio(anchor_bound, total),
        exact_bound_ratio=_ratio(exact, total),
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _has_display_ref(
    entity: AnchorBoundPiiEntityV1, source_name: DocumentTextAnchorSourceName
) -> bool:
    return any(
        ref.source_name == source_name
        and ref.source_range is not None
        and ref.binding_role == "display_span"
        for ref in entity.anchor_refs
    )


def _binding_reason_counts(entities: Sequence[AnchorBoundPiiEntityV1]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        for reason in entity.binding_reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _warning_codes(entities: Sequence[AnchorBoundPiiEntityV1]) -> list[str]:
    warnings: set[str] = set()
    for entity in entities:
        warnings.update(
            reason for reason in entity.binding_reasons if reason != "anchor_exact_match"
        )
    return sorted(warnings)
