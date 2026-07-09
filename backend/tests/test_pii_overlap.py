"""Unit tests for deterministic PII overlap / conflict resolution (PII L12).

All entities are synthetic. The resolver takes globally-offset PiiEntity spans and returns a clean,
deterministically-ordered set with provenance. It never edits an entity's text/offsets/score.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from app.schemas import PiiEntity
from app.services.pii_overlap import resolve_pii_overlaps


def _entity(
    entity_type: str,
    start: int,
    end: int,
    *,
    score: float = 0.8,
    recognizer: str = "R1",
    entity_id: str | None = None,
) -> PiiEntity:
    return PiiEntity(
        id=entity_id or uuid4().hex,
        entity_type=entity_type,
        text="x" * (end - start),
        start_offset=start,
        end_offset=end,
        score=score,
        recognizer=recognizer,
    )


def _ids(entities: Sequence[PiiEntity]) -> list[str]:
    return [entity.id for entity in entities]


# --- Exact duplicates ----------------------------------------------------------------------------


def test_exact_duplicate_same_recognizer_merges_to_one() -> None:
    keep = _entity("PERSON", 0, 14, score=0.9, entity_id="a" * 32)
    dup = _entity("PERSON", 0, 14, score=0.7, entity_id="b" * 32)

    resolved, summary = resolve_pii_overlaps([keep, dup])

    assert len(resolved) == 1
    assert resolved[0].id == keep.id  # higher score wins deterministically
    assert summary.merged_count == 1
    assert summary.dropped_count == 0
    assert summary.by_reason["exact_duplicate"] == 1
    provenance = resolved[0].provenance
    assert provenance is not None
    assert provenance.candidate_count == 2
    assert provenance.merge_reason == "exact_duplicate"
    assert provenance.overlap_decision == "merged_provenance"
    assert provenance.superseded_candidate_ids == [dup.id]


def test_exact_duplicate_from_different_recognizers_merges_provenance() -> None:
    first = _entity("EMAIL_ADDRESS", 5, 19, recognizer="RegexA", entity_id="c" * 32)
    second = _entity("EMAIL_ADDRESS", 5, 19, recognizer="RegexB", entity_id="d" * 32)

    resolved, summary = resolve_pii_overlaps([first, second])

    assert len(resolved) == 1
    provenance = resolved[0].provenance
    assert provenance is not None
    assert provenance.recognizers == ["RegexA", "RegexB"]
    assert provenance.merge_reason == "recognizer_duplicate"
    assert summary.by_reason["recognizer_duplicate"] == 1
    assert summary.by_reason["merged_provenance"] == 1


# --- Same-type overlap ---------------------------------------------------------------------------


def test_nested_same_type_keeps_longer_span() -> None:
    outer = _entity("PERSON", 0, 14, score=0.7, entity_id="1" * 32)
    inner = _entity("PERSON", 0, 10, score=0.95, entity_id="2" * 32)

    resolved, summary = resolve_pii_overlaps([inner, outer])

    assert _ids(resolved) == [outer.id]  # longer span wins even with a lower score
    assert summary.dropped_count == 1
    provenance = resolved[0].provenance
    assert provenance is not None
    assert provenance.merge_reason == "nested_entity"
    assert provenance.overlap_decision == "longer_span_selected"
    assert inner.id in provenance.superseded_candidate_ids


def test_partial_same_type_overlap_equal_length_prefers_higher_confidence() -> None:
    weaker = _entity("PERSON", 0, 10, score=0.6, entity_id="3" * 32)
    stronger = _entity("PERSON", 5, 15, score=0.9, entity_id="4" * 32)

    resolved, summary = resolve_pii_overlaps([weaker, stronger])

    assert _ids(resolved) == [stronger.id]
    assert summary.dropped_count == 1
    provenance = resolved[0].provenance
    assert provenance is not None
    assert provenance.overlap_decision == "stronger_confidence_selected"
    assert provenance.merge_reason == "same_type_overlap"


def test_same_type_overlap_chain_resolves_to_single_winner() -> None:
    a = _entity("ORGANIZATION", 0, 12, score=0.5, entity_id="5" * 32)
    b = _entity("ORGANIZATION", 6, 30, score=0.8, entity_id="6" * 32)  # longest span
    c = _entity("ORGANIZATION", 20, 28, score=0.9, entity_id="7" * 32)

    resolved, summary = resolve_pii_overlaps([a, b, c])

    assert _ids(resolved) == [b.id]
    assert summary.dropped_count == 2


# --- Cross-type overlap is preserved and flagged, never dropped ----------------------------------


def test_different_type_overlap_is_preserved_and_flagged_for_review() -> None:
    person = _entity("PERSON", 0, 14, entity_id="8" * 32)
    location = _entity("LOCATION", 5, 20, entity_id="9" * 32)

    resolved, summary = resolve_pii_overlaps([person, location])

    assert set(_ids(resolved)) == {person.id, location.id}  # neither dropped
    assert summary.dropped_count == 0
    assert summary.merged_count == 0
    assert summary.review_required_count == 2
    for entity in resolved:
        assert entity.provenance is not None
        assert entity.provenance.review_required is True
        assert entity.provenance.overlap_decision == "conflicting_entity_type"
    assert summary.by_reason["ambiguous_overlap_review_required"] == 2


# --- Determinism + non-destructiveness -----------------------------------------------------------


def test_output_is_deterministically_sorted_regardless_of_input_order() -> None:
    first = _entity("PERSON", 0, 14, entity_id="a1" + "0" * 30)
    middle = _entity("LOCATION", 18, 22, entity_id="a2" + "0" * 30)
    last = _entity("PERSON", 27, 43, entity_id="a3" + "0" * 30)

    forward, _ = resolve_pii_overlaps([first, middle, last])
    shuffled, _ = resolve_pii_overlaps([last, first, middle])

    assert _ids(forward) == [first.id, middle.id, last.id]
    assert _ids(shuffled) == _ids(forward)


def test_non_overlapping_entities_pass_through_with_baseline_provenance() -> None:
    person = _entity("PERSON", 0, 14)
    email = _entity("EMAIL_ADDRESS", 20, 34)

    resolved, summary = resolve_pii_overlaps([person, email])

    assert summary.merged_count == 0
    assert summary.dropped_count == 0
    assert summary.review_required_count == 0
    for entity in resolved:
        assert entity.provenance is not None
        assert entity.provenance.detection_source == "raw_text"
        assert entity.provenance.source_role == "primary"
        assert entity.provenance.candidate_count == 1
        assert entity.provenance.overlap_decision is None


def test_resolution_never_changes_entity_values() -> None:
    outer = _entity("PERSON", 0, 14, entity_id="b1" + "0" * 30)
    inner = _entity("PERSON", 3, 9, entity_id="b2" + "0" * 30)

    resolved, _ = resolve_pii_overlaps([outer, inner])

    assert len(resolved) == 1
    survivor = resolved[0]
    assert (survivor.start_offset, survivor.end_offset, survivor.text) == (
        outer.start_offset,
        outer.end_offset,
        outer.text,
    )


def test_summary_counts_are_internally_consistent() -> None:
    entities = [
        _entity("PERSON", 0, 14, entity_id="c1" + "0" * 30),
        _entity("PERSON", 0, 14, score=0.6, entity_id="c2" + "0" * 30),  # exact duplicate
        _entity("PERSON", 30, 40, entity_id="c3" + "0" * 30),
        _entity("PERSON", 34, 44, entity_id="c4" + "0" * 30),  # same-type overlap
        _entity("LOCATION", 60, 70, entity_id="c5" + "0" * 30),
    ]

    resolved, summary = resolve_pii_overlaps(entities)

    assert summary.input_candidate_count == len(entities)
    assert (
        summary.input_candidate_count
        == summary.output_entity_count + summary.merged_count + summary.dropped_count
    )
    assert len(resolved) == summary.output_entity_count
