"""Synthetic unit tests for the PII structural-context validation stage.

All data is synthetic — no private corpus, no OCR runtime. The stage is a pure, deterministic,
strictly subtractive function over (entities, structural spans); these tests pin each rule, the
no-true-positive-loss guardrails, order-independence, and the text-free provenance invariant.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.schemas import PiiEntity
from app.services.pii_input import PiiInputStructuralSpan
from app.services.pii_structural_validation import (
    STRUCTURAL_CELL_CLIP,
    STRUCTURAL_HEADING_REJECTED,
    STRUCTURAL_LABEL_VALUE_TRIMMED,
    validate_structural_context,
)


def _entity(
    raw: str,
    entity_type: str,
    start: int,
    end: int,
    *,
    paged: bool = True,
    score: float = 0.9,
) -> PiiEntity:
    """A valid entity whose text is sliced from ``raw`` so offsets always match text."""
    return PiiEntity(
        id=uuid.uuid4().hex,
        entity_type=entity_type,
        text=raw[start:end],
        start_offset=start,
        end_offset=end,
        page_number=1 if paged else None,
        page_start_offset=start if paged else None,
        page_end_offset=end if paged else None,
        score=score,
        recognizer="test",
    )


def _span(
    kind: str, start: int, end: int, *, container_id: str, role: str = "unknown"
) -> PiiInputStructuralSpan:
    return PiiInputStructuralSpan(
        kind=kind,  # type: ignore[arg-type]
        page_number=1,
        page_start=start,
        page_end=end,
        raw_start=start,
        raw_end=end,
        container_id=container_id,
        role=role,
    )


def _assert_valid(entity: PiiEntity) -> None:
    # A resliced entity must still satisfy every PiiEntity invariant.
    PiiEntity.model_validate(entity.model_dump())


# --- Rule 1: cell / field-value boundary clip ----------------------------------------------------


def test_cell_clip_trims_overflow_into_next_cell() -> None:
    raw = "Cell one text  Cell two text"
    cell1 = _span("table_cell", 0, 13, container_id="table-p1-1")  # "Cell one text"
    entity = _entity(raw, "ADDRESS", 5, 22)  # starts in cell1, bleeds past its end
    result = validate_structural_context([entity], [cell1], enabled=True)

    (kept,) = result.entities
    assert (kept.start_offset, kept.end_offset) == (5, 13)
    assert kept.text == raw[5:13]
    assert kept.id == entity.id
    assert result.reasons_by_entity_id[entity.id] == (STRUCTURAL_CELL_CLIP,)
    assert result.summary.clipped_count == 1
    assert result.summary.by_reason == {STRUCTURAL_CELL_CLIP: 1}
    _assert_valid(kept)


def test_cell_clip_updates_page_offsets_consistently() -> None:
    raw = "Cell one text  Cell two text"
    cell1 = _span("table_cell", 0, 13, container_id="table-p1-1")
    entity = _entity(raw, "ADDRESS", 5, 22)
    (kept,) = validate_structural_context([entity], [cell1], enabled=True).entities
    assert kept.page_start_offset == 5
    assert kept.page_end_offset == 13
    _assert_valid(kept)


def test_cell_clip_leaves_entity_within_cell_untouched() -> None:
    raw = "Cell one text  Cell two text"
    cell1 = _span("table_cell", 0, 13, container_id="table-p1-1")
    entity = _entity(raw, "ADDRESS", 5, 12)  # fully inside cell1
    result = validate_structural_context([entity], [cell1], enabled=True)
    (kept,) = result.entities
    assert (kept.start_offset, kept.end_offset) == (5, 12)
    assert result.summary.by_reason == {}


def test_cell_clip_does_not_touch_entity_starting_in_a_later_cell() -> None:
    raw = "Cell one text  Cell two text"
    cell2 = _span("field_value", 15, 28, container_id="field-p1-1")
    entity = _entity(raw, "ADDRESS", 0, 13)  # entirely before cell2; must not be clipped
    result = validate_structural_context([entity], [cell2], enabled=True)
    (kept,) = result.entities
    assert (kept.start_offset, kept.end_offset) == (0, 13)
    assert result.summary.clipped_count == 0


# --- Rule 3: whole-line label + value trim -------------------------------------------------------


def test_label_value_trim_drops_label_prefix() -> None:
    raw = "Name: Max Mustermann"
    label = _span("field_label", 0, 4, container_id="field-p1-1", role="person_name")
    value = _span("field_value", 6, 20, container_id="field-p1-1", role="person_name")
    entity = _entity(raw, "PERSON", 0, 20)  # captured the whole labelled line
    result = validate_structural_context([entity], [label, value], enabled=True)

    (kept,) = result.entities
    assert (kept.start_offset, kept.end_offset) == (6, 20)
    assert kept.text == "Max Mustermann"
    assert result.reasons_by_entity_id[entity.id] == (STRUCTURAL_LABEL_VALUE_TRIMMED,)
    assert result.summary.trimmed_count == 1
    _assert_valid(kept)


def test_label_value_trim_also_clips_a_tail_past_the_value() -> None:
    raw = "Name: Max Mustermann  extra"
    label = _span("field_label", 0, 4, container_id="field-p1-1")
    value = _span("field_value", 6, 20, container_id="field-p1-1")
    entity = _entity(raw, "PERSON", 0, 27)
    (kept,) = validate_structural_context([entity], [label, value], enabled=True).entities
    assert (kept.start_offset, kept.end_offset) == (6, 20)
    assert kept.text == "Max Mustermann"


def test_label_value_trim_leaves_a_clean_value_only_entity_untouched() -> None:
    raw = "Name: Max Mustermann"
    label = _span("field_label", 0, 4, container_id="field-p1-1")
    value = _span("field_value", 6, 20, container_id="field-p1-1")
    entity = _entity(raw, "PERSON", 6, 20)  # already exactly the value
    result = validate_structural_context([entity], [label, value], enabled=True)
    (kept,) = result.entities
    assert (kept.start_offset, kept.end_offset) == (6, 20)
    assert result.summary.by_reason == {}


# --- Rule 2: heading / section-title rejection ---------------------------------------------------


def test_heading_rejection_drops_prose_entity_in_a_heading() -> None:
    raw = "Leistungen und Positionen"
    heading = _span("heading", 0, 25, container_id="section-p1-1", role="section")
    entity = _entity(raw, "ADDRESS", 0, 25)
    result = validate_structural_context([entity], [heading], enabled=True)

    assert result.entities == []
    assert result.dropped_entity_ids == (entity.id,)
    assert result.summary.dropped_count == 1
    assert result.summary.by_reason == {STRUCTURAL_HEADING_REJECTED: 1}


def test_heading_rejection_never_drops_a_hard_identifier() -> None:
    # A miss on a P3 identifier is a leak: rule 2 must not reject it even inside a heading span.
    raw = "AT611904300234573201"
    heading = _span("heading", 0, 20, container_id="section-p1-1", role="section")
    entity = _entity(raw, "IBAN_CODE", 0, 20)
    result = validate_structural_context([entity], [heading], enabled=True)
    assert [e.id for e in result.entities] == [entity.id]
    assert result.dropped_entity_ids == ()


@pytest.mark.parametrize("entity_type", ["PERSON", "ORGANIZATION", "GIVEN_NAME", "FAMILY_NAME"])
def test_heading_rejection_never_drops_a_name_or_organization(entity_type: str) -> None:
    # A person/company name legitimately IS a heading (letterhead, addressee, signatory). A corpus
    # A/B caught rule 2 dropping real ORGANIZATION true positives here — heading membership is not
    # FP evidence for a name/org, so they must survive.
    raw = "Sachverstaendigenbuero Mustermann GmbH"
    heading = _span("heading", 0, len(raw), container_id="section-p1-1", role="section")
    entity = _entity(raw, entity_type, 0, len(raw))
    result = validate_structural_context([entity], [heading], enabled=True)
    assert [e.id for e in result.entities] == [entity.id]
    assert result.dropped_entity_ids == ()


def test_heading_rejection_requires_containment_not_mere_overlap() -> None:
    raw = "Standort Wien Landstrasse 5"
    heading = _span("heading", 0, 8, container_id="section-p1-1", role="section")
    entity = _entity(raw, "ADDRESS", 5, 27)  # spills past the heading; not contained
    result = validate_structural_context([entity], [heading], enabled=True)
    assert [e.id for e in result.entities] == [entity.id]
    assert result.summary.dropped_count == 0


# --- Rule precedence -----------------------------------------------------------------------------


def test_heading_rejection_precedes_clipping() -> None:
    raw = "Leistungen und Positionen"
    heading = _span("heading", 0, 25, container_id="section-p1-1", role="section")
    cell = _span("table_cell", 0, 10, container_id="table-p1-1")
    entity = _entity(raw, "ADDRESS", 0, 25)  # both contained-in-heading and overflowing a cell
    result = validate_structural_context([entity], [heading, cell], enabled=True)
    assert result.entities == []
    assert result.summary.by_reason == {STRUCTURAL_HEADING_REJECTED: 1}


# --- Determinism / order-independence ------------------------------------------------------------


def test_result_is_independent_of_input_order() -> None:
    raw = "Name: Max Mustermann  Leistungen  City AB  more"
    label = _span("field_label", 0, 4, container_id="field-p1-1")
    value = _span("field_value", 6, 20, container_id="field-p1-1")
    heading = _span("heading", 22, 32, container_id="section-p1-1", role="section")
    cell = _span("table_cell", 34, 42, container_id="table-p1-1")  # "City AB " region
    person = _entity(raw, "PERSON", 0, 20)
    heading_addr = _entity(raw, "ADDRESS", 22, 32)  # line-type contained in a heading -> dropped
    addr = _entity(raw, "ADDRESS", 36, 47)  # starts in cell, overflows
    spans = [label, value, heading, cell]
    entities = [person, heading_addr, addr]

    forward = validate_structural_context(entities, spans, enabled=True)
    reverse = validate_structural_context(
        list(reversed(entities)), list(reversed(spans)), enabled=True
    )

    def _fingerprint(result: object) -> object:
        assert hasattr(result, "entities")
        return (
            sorted((e.id, e.start_offset, e.end_offset, e.text) for e in result.entities),  # type: ignore[attr-defined]
            sorted(result.dropped_entity_ids),  # type: ignore[attr-defined]
            result.summary.by_reason,  # type: ignore[attr-defined]
        )

    assert _fingerprint(forward) == _fingerprint(reverse)
    assert forward.summary.by_reason == {
        STRUCTURAL_LABEL_VALUE_TRIMMED: 1,
        STRUCTURAL_HEADING_REJECTED: 1,
        STRUCTURAL_CELL_CLIP: 1,
    }


# --- No-op guardrails ----------------------------------------------------------------------------


def test_disabled_is_a_no_op() -> None:
    raw = "Leistungen und Positionen"
    heading = _span("heading", 0, 25, container_id="section-p1-1", role="section")
    entity = _entity(raw, "ADDRESS", 0, 25)
    result = validate_structural_context([entity], [heading], enabled=False)
    assert result.entities == [entity]
    assert result.summary.applied is False
    assert result.summary.dropped_count == 0
    assert result.reasons_by_entity_id == {}


def test_enabled_without_structural_spans_changes_nothing() -> None:
    raw = "Max Mustermann"
    entity = _entity(raw, "PERSON", 0, 14)
    result = validate_structural_context([entity], [], enabled=True)
    assert result.entities == [entity]
    assert result.summary.applied is True
    assert result.summary.by_reason == {}


def test_non_overlapping_entity_is_left_untouched() -> None:
    raw = "Heading here    Max Mustermann"
    heading = _span("heading", 0, 12, container_id="section-p1-1", role="section")
    value = _span("field_value", 16, 30, container_id="field-p1-1")
    entity = _entity(raw, "PHONE_NUMBER", 16, 30)  # exactly the value, nothing to do
    result = validate_structural_context([entity], [heading, value], enabled=True)
    assert result.entities == [entity]
    assert result.summary.by_reason == {}


def test_non_paged_entity_is_supported() -> None:
    raw = "Cell one text  Cell two text"
    cell1 = _span("table_cell", 0, 13, container_id="table-p1-1")
    entity = _entity(raw, "ADDRESS", 5, 22, paged=False)
    (kept,) = validate_structural_context([entity], [cell1], enabled=True).entities
    assert (kept.start_offset, kept.end_offset) == (5, 13)
    assert kept.page_number is None
    assert kept.page_start_offset is None
    _assert_valid(kept)


# --- Privacy: provenance carries no entity text --------------------------------------------------


def test_provenance_metadata_has_no_entity_text() -> None:
    marker = "AT611904300234573201"
    raw = f"IBAN {marker}  City AB"
    label = _span("field_label", 0, 4, container_id="field-p1-1")
    value = _span("field_value", 5, 25, container_id="field-p1-1")
    entity = _entity(raw, "PERSON", 0, 25)  # captured label + value marker
    result = validate_structural_context([entity], [label, value], enabled=True)

    serialized = json.dumps(
        {
            "by_reason": result.summary.by_reason,
            "reasons": {eid: list(codes) for eid, codes in result.reasons_by_entity_id.items()},
            "dropped": list(result.dropped_entity_ids),
            "summary": {
                "applied": result.summary.applied,
                "input": result.summary.input_count,
                "output": result.summary.output_count,
                "clipped": result.summary.clipped_count,
                "trimmed": result.summary.trimmed_count,
                "dropped": result.summary.dropped_count,
            },
        }
    )
    assert marker not in serialized
    # The value still lives only on the surviving entity itself (trimmed to the value).
    (kept,) = result.entities
    assert marker in kept.text


@pytest.mark.parametrize("enabled", [True, False])
def test_input_entities_are_never_mutated(enabled: bool) -> None:
    raw = "Name: Max Mustermann"
    label = _span("field_label", 0, 4, container_id="field-p1-1")
    value = _span("field_value", 6, 20, container_id="field-p1-1")
    entity = _entity(raw, "PERSON", 0, 20)
    before = entity.model_dump()
    validate_structural_context([entity], [label, value], enabled=enabled)
    assert entity.model_dump() == before
