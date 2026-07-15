"""Deterministic PII overlap / conflict resolution (PII L12).

After detection and candidate validation, a document can carry duplicate, nested, or overlapping
entity spans: the same span found by two recognizers, a longer span containing a shorter one, or a
different type claiming overlapping text. This module resolves those conflicts deterministically and
records the outcome as provenance, so the final set is clean without silently discarding competing
evidence.

Policy (conservative, deterministic, and fully synthetic-testable):

- **Exact duplicate** (identical start/end/type): merge into one survivor; combine recognizer names
  and record the merged candidates' ids. Reason ``exact_duplicate`` (also ``recognizer_duplicate``
  when the recognizers differ), decision ``merged_provenance``.
- **Same type, overlapping**: greedily select the strongest span, suppress only candidates fully
  contained by that winner, then continue with the remaining candidates. Partial or transitive
  overlap alone can never suppress independently covered spans.
  Reason ``nested_entity`` when the winner contains a competitor, else ``same_type_overlap``;
  decision ``longer_span_selected`` or ``stronger_confidence_selected``.
- **Different type, overlapping**: never dropped. Both entities are preserved and flagged for review
  (``conflicting_entity_type`` + ``ambiguous_overlap_review_required``), so a human resolves the
  conflict instead of the engine guessing a cross-type precedence.

Entity offsets, text, and scores are never modified; only which entities survive and their
``provenance`` change. The resolver is a pure function of its input order-independent set.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas import (
    PiiEntity,
    PiiEntityProvenance,
    PiiOverlapReason,
    PiiOverlapResolutionSummary,
)


def resolve_pii_overlaps(
    entities: Sequence[PiiEntity],
) -> tuple[list[PiiEntity], PiiOverlapResolutionSummary]:
    """Resolve overlaps deterministically and attach provenance to every surviving entity."""
    reasons: dict[str, int] = {}
    provenance = {entity.id: _baseline_provenance(entity) for entity in entities}

    survivors = _merge_exact_duplicates(list(entities), provenance, reasons)
    merged_count = len(entities) - len(survivors)

    survivors = _resolve_same_type_overlaps(survivors, provenance, reasons)
    survivors = _resolve_cross_type_precedence(survivors, provenance, reasons)
    dropped_count = len(entities) - merged_count - len(survivors)

    review_required = _flag_cross_type_overlaps(survivors, provenance, reasons)

    resolved = [
        entity.model_copy(update={"provenance": provenance[entity.id]}) for entity in survivors
    ]
    resolved = _sorted(resolved)
    summary = PiiOverlapResolutionSummary(
        applied=True,
        input_candidate_count=len(entities),
        output_entity_count=len(resolved),
        merged_count=merged_count,
        dropped_count=dropped_count,
        review_required_count=review_required,
        by_reason=dict(sorted(reasons.items())),
    )
    return resolved, summary


def _baseline_provenance(entity: PiiEntity) -> PiiEntityProvenance:
    return PiiEntityProvenance(
        detection_source="raw_text",
        source_role="primary",
        recognizers=[entity.recognizer],
        candidate_count=1,
    )


def _merge_exact_duplicates(
    entities: list[PiiEntity],
    provenance: dict[str, PiiEntityProvenance],
    reasons: dict[str, int],
) -> list[PiiEntity]:
    """Collapse identical (start, end, type) spans into one survivor, merging their provenance."""
    groups: dict[tuple[int, int, str], list[PiiEntity]] = {}
    order: list[tuple[int, int, str]] = []
    for entity in entities:
        key = (entity.start_offset, entity.end_offset, entity.entity_type)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entity)

    survivors: list[PiiEntity] = []
    for key in order:
        members = groups[key]
        winner = _strongest(members)
        survivors.append(winner)
        if len(members) == 1:
            continue
        losers = [entity for entity in members if entity.id != winner.id]
        recognizers = sorted({member.recognizer for member in members})
        distinct_recognizers = len(recognizers) > 1
        primary_reason: PiiOverlapReason = (
            "recognizer_duplicate" if distinct_recognizers else "exact_duplicate"
        )
        provenance[winner.id] = provenance[winner.id].model_copy(
            update={
                "recognizers": recognizers,
                "candidate_count": len(members),
                "merge_reason": primary_reason,
                "overlap_decision": "merged_provenance",
                "superseded_candidate_ids": sorted(loser.id for loser in losers),
            }
        )
        _count(reasons, "exact_duplicate")
        if distinct_recognizers:
            _count(reasons, "recognizer_duplicate")
        _count(reasons, "merged_provenance")
    return survivors


def _resolve_same_type_overlaps(
    entities: list[PiiEntity],
    provenance: dict[str, PiiEntityProvenance],
    reasons: dict[str, int],
) -> list[PiiEntity]:
    """Suppress only contained competitors of each winner, preserving independent coverage."""
    survivors: list[PiiEntity] = []
    for cluster in _clusters(entities, same_type_only=True):
        remaining = list(cluster)
        while remaining:
            winner = _strongest(remaining)
            # A partial overlap may cover characters outside the winner. Suppressing it would
            # shrink known PII coverage, so only fully contained candidates are superseded.
            losers = [
                entity
                for entity in remaining
                if entity.id != winner.id and _contains(winner, entity)
            ]
            survivors.append(winner)
            remaining = [
                entity
                for entity in remaining
                if entity.id != winner.id and entity not in losers
            ]
            if not losers:
                continue
            nested = any(_contains(winner, loser) for loser in losers)
            decision: PiiOverlapReason = "longer_span_selected"
            if all(_length(loser) == _length(winner) for loser in losers):
                decision = "stronger_confidence_selected"
            merge_reason: PiiOverlapReason = "nested_entity" if nested else "same_type_overlap"
            existing = provenance[winner.id]
            provenance[winner.id] = existing.model_copy(
                update={
                    "candidate_count": existing.candidate_count + len(losers),
                    "merge_reason": existing.merge_reason or merge_reason,
                    "overlap_decision": decision,
                    "superseded_candidate_ids": sorted(
                        {*existing.superseded_candidate_ids, *(loser.id for loser in losers)}
                    ),
                }
            )
            _count(reasons, merge_reason)
            _count(reasons, decision)
            for _ in losers:
                _count(reasons, "dropped_lower_confidence_duplicate")
    return survivors


# Deterministic cross-type precedence: a key type suppresses a fully-contained value type. Kept
# minimal and structural — a URL matched on an email's domain (``max@example.at`` → ``example.at``)
# is spurious, so EMAIL_ADDRESS wins. Only a *contained* subordinate is dropped; a genuinely
# separate overlapping entity is still preserved and flagged by ``_flag_cross_type_overlaps``.
_CROSS_TYPE_PRECEDENCE: dict[str, frozenset[str]] = {
    "EMAIL_ADDRESS": frozenset({"URL"}),
    # A birth date detected in context is the same span the generic NER emits as DATE_TIME; the
    # specific birth role wins so the value is not double-counted.
    "BIRTH_DATE": frozenset({"DATE_TIME"}),
}


def _resolve_cross_type_precedence(
    entities: list[PiiEntity],
    provenance: dict[str, PiiEntityProvenance],
    reasons: dict[str, int],
) -> list[PiiEntity]:
    """Drop a lower-precedence entity fully contained in a higher-precedence one (table-driven)."""
    dropped: set[str] = set()
    ordered = _sorted(entities)
    for winner in ordered:
        subordinate_types = _CROSS_TYPE_PRECEDENCE.get(winner.entity_type)
        if not subordinate_types:
            continue
        for loser in ordered:
            if loser.id == winner.id or loser.id in dropped:
                continue
            if loser.entity_type in subordinate_types and _covers(winner, loser):
                dropped.add(loser.id)
                existing = provenance[winner.id]
                provenance[winner.id] = existing.model_copy(
                    update={
                        "candidate_count": existing.candidate_count + 1,
                        "overlap_decision": existing.overlap_decision or "cross_type_precedence",
                        "superseded_candidate_ids": sorted(
                            {*existing.superseded_candidate_ids, loser.id}
                        ),
                    }
                )
                _count(reasons, "cross_type_precedence")
                _count(reasons, "dropped_cross_type_subordinate")
    return [entity for entity in entities if entity.id not in dropped]


def _covers(outer: PiiEntity, inner: PiiEntity) -> bool:
    """``inner`` sits fully within ``outer`` (equal spans included)."""
    return outer.start_offset <= inner.start_offset and inner.end_offset <= outer.end_offset


def _flag_cross_type_overlaps(
    entities: list[PiiEntity],
    provenance: dict[str, PiiEntityProvenance],
    reasons: dict[str, int],
) -> int:
    """Flag (never drop) different-type overlaps for human review; return distinct flagged count."""
    flagged: set[str] = set()
    for cluster in _clusters(entities, same_type_only=False):
        types = {entity.entity_type for entity in cluster}
        if len(cluster) < 2 or len(types) < 2:
            continue
        for entity in cluster:
            if any(
                other.id != entity.id and _overlaps(entity, other) for other in cluster
            ):
                flagged.add(entity.id)
    for entity_id in flagged:
        provenance[entity_id] = provenance[entity_id].model_copy(
            update={"overlap_decision": "conflicting_entity_type", "review_required": True}
        )
    if flagged:
        for _ in flagged:
            _count(reasons, "conflicting_entity_type")
            _count(reasons, "ambiguous_overlap_review_required")
    return len(flagged)


def _clusters(entities: list[PiiEntity], *, same_type_only: bool) -> list[list[PiiEntity]]:
    """Connected components of overlapping entities, sorted deterministically.

    When ``same_type_only`` is set, only same-type overlaps connect two entities; otherwise any
    overlap connects them. Sorting the input first makes the component walk order-independent.
    """
    ordered = _sorted(entities)
    parent = {entity.id: entity.id for entity in ordered}

    def find(entity_id: str) -> str:
        while parent[entity_id] != entity_id:
            parent[entity_id] = parent[parent[entity_id]]
            entity_id = parent[entity_id]
        return entity_id

    def union(left: str, right: str) -> None:
        parent[find(left)] = find(right)

    for index, entity in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if other.start_offset >= entity.end_offset:
                break  # ordered by start; no later entity can overlap this one
            if not _overlaps(entity, other):
                continue
            if same_type_only and entity.entity_type != other.entity_type:
                continue
            union(entity.id, other.id)

    grouped: dict[str, list[PiiEntity]] = {}
    for entity in ordered:
        grouped.setdefault(find(entity.id), []).append(entity)
    return [grouped[root] for root in dict.fromkeys(find(entity.id) for entity in ordered)]


def _strongest(entities: list[PiiEntity]) -> PiiEntity:
    """Deterministic winner: longest span, then highest score, then earliest, recognizer, id."""
    return min(
        entities,
        key=lambda entity: (
            -_length(entity),
            -entity.score,
            entity.start_offset,
            entity.recognizer,
            entity.id,
        ),
    )


def _sorted(entities: list[PiiEntity]) -> list[PiiEntity]:
    return sorted(
        entities,
        key=lambda entity: (
            entity.start_offset,
            entity.end_offset,
            entity.entity_type,
            entity.recognizer,
            entity.text,
            -entity.score,
        ),
    )


def _overlaps(left: PiiEntity, right: PiiEntity) -> bool:
    return left.start_offset < right.end_offset and right.start_offset < left.end_offset


def _contains(outer: PiiEntity, inner: PiiEntity) -> bool:
    return (
        outer.start_offset <= inner.start_offset
        and inner.end_offset <= outer.end_offset
        and _length(outer) > _length(inner)
    )


def _length(entity: PiiEntity) -> int:
    return entity.end_offset - entity.start_offset


def _count(reasons: dict[str, int], reason: str) -> None:
    reasons[reason] = reasons.get(reason, 0) + 1
