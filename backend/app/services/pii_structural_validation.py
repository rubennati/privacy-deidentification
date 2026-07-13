"""PII structural-context validation — subtractive FP suppression using ``structured_content``.

This is a post-detection, **strictly subtractive** stage (candidate-validation family): given the
detected/validated PII entities and the offset-only structural spans exposed by the intake adapter
(:mod:`app.services.pii_input`), it trims or rejects candidates whose boundaries contradict a known
structural role — a span that bleeds across a table-cell boundary, an entity that swallowed a
label prefix, or a candidate that is really a section heading. It **never** expands, moves, invents,
or re-labels a detection, and it never changes the detection input.

Design invariants (see ``docs/engine/pii-structural-context-validation.md``):

- **Deterministic and order-independent.** Every entity is evaluated independently against the
  immutable structural spans; a fixed rule precedence resolves multiple applicable rules per entity;
  ties between candidate spans break on a total offset/id ordering. Output does not depend on the
  order of ``entities`` or ``spans``.
- **Subtractive/clip only.** A rule may shrink a span to a boundary it already overlaps or reject it
  outright — never produce a wider, moved, or empty span.
- **Structural, never corpus-fitted.** Rules encode structural truths (an entity does not span two
  cells; a heading is not an address), not benchmark numbers.
- **Alignment on raw offsets.** Structural spans and entities share the raw-text coordinate system;
  matching uses the global raw offsets (``PiiInputStructuralSpan.raw_*`` ↔
  ``PiiEntity.start_offset``/``end_offset``), which is unambiguous document-wide and robust for
  non-paged (DOCX) documents where ``page_number`` differs.
- **Reason-coded, text-free provenance.** The result carries reason codes and counts only; the
  entity's value stays in ``PiiEntity.text`` and is never duplicated into this stage's metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas import PiiEntity
from app.services.pii_input import PiiInputStructuralSpan

# Stable, machine-readable reason codes. A code is never removed or repurposed.
STRUCTURAL_CELL_CLIP = "structural_cell_clip"
STRUCTURAL_LABEL_VALUE_TRIMMED = "structural_label_value_trimmed"
STRUCTURAL_HEADING_REJECTED = "structural_heading_rejected"

# Value-bearing structural regions an entity must not overflow (rule 1).
_VALUE_KINDS = frozenset({"table_cell", "field_value"})

# Only "line/place" content types are plausible heading false positives — a labelled-line or
# location recognizer misfiring on a section title ("Leistungen und Positionen" -> ADDRESS). Names
# and organizations are deliberately EXCLUDED: on real documents a person or company name
# legitimately *is* a heading (letterhead, addressee block, signatory) — a corpus A/B showed rule 2
# dropping real ORGANIZATION true positives that sit in section headings (no-TP-loss violation), so
# heading membership is not FP evidence for a name/org (their precision is a separate NER concern).
# Hard structured identifiers (IBAN, national IDs, cards, plates) are likewise never rejected — a
# miss there is a leak (quality gate: P3 recall >= 0.98). This is a structural judgement, not a
# corpus-fitted list.
_HEADING_REJECTABLE_TYPES = frozenset(
    {
        "ADDRESS",
        "CONTACT_LINE",
        "CUSTOMER_LINE",
        "LOCATION",
        "BIRTH_PLACE",
    }
)


@dataclass(frozen=True)
class StructuralValidationSummary:
    """Metrics-only outcome of the structural-context stage. Reason codes and counts only."""

    applied: bool
    input_count: int
    output_count: int
    clipped_count: int
    trimmed_count: int
    dropped_count: int
    by_reason: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuralValidationResult:
    """Result of one structural-context pass: the surviving entities plus text-free provenance.

    ``entities`` is the new list (clipped/trimmed applied in place of the original, dropped
    removed), order-preserving relative to the input. ``reasons_by_entity_id`` maps each *surviving*
    entity
    that a rule modified to the reason codes applied to it; ``dropped_entity_ids`` lists rejected
    entities. Both let the caller attach structural provenance without re-deriving it.
    """

    entities: list[PiiEntity]
    summary: StructuralValidationSummary
    reasons_by_entity_id: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dropped_entity_ids: tuple[str, ...] = ()


def validate_structural_context(
    entities: Sequence[PiiEntity],
    spans: Sequence[PiiInputStructuralSpan],
    *,
    enabled: bool,
) -> StructuralValidationResult:
    """Apply the deterministic subtractive structural rules and return the surviving entities.

    When ``enabled`` is false the stage is a no-op: the entities are returned unchanged with an
    ``applied=False`` summary. When enabled with no structural spans it is also a no-op, but
    ``applied`` reflects that the stage ran.
    """
    input_entities = list(entities)
    if not enabled:
        return StructuralValidationResult(
            entities=input_entities,
            summary=StructuralValidationSummary(
                applied=False,
                input_count=len(input_entities),
                output_count=len(input_entities),
                clipped_count=0,
                trimmed_count=0,
                dropped_count=0,
            ),
        )

    value_spans = tuple(span for span in spans if span.kind in _VALUE_KINDS)
    heading_spans = tuple(span for span in spans if span.kind == "heading")
    label_value_pairs = _label_value_pairs(spans)

    survivors: list[PiiEntity] = []
    reasons_by_id: dict[str, tuple[str, ...]] = {}
    dropped_ids: list[str] = []
    counts = {
        STRUCTURAL_CELL_CLIP: 0,
        STRUCTURAL_LABEL_VALUE_TRIMMED: 0,
        STRUCTURAL_HEADING_REJECTED: 0,
    }

    for entity in input_entities:
        # Rule precedence per entity (first match wins): heading rejection, then label/value trim,
        # then cell/field-value clip. One structural action per entity keeps the pass unambiguous.
        if _is_heading_false_positive(entity, heading_spans):
            dropped_ids.append(entity.id)
            counts[STRUCTURAL_HEADING_REJECTED] += 1
            continue

        trimmed = _label_value_trim(entity, label_value_pairs)
        if trimmed is not None:
            survivors.append(trimmed)
            reasons_by_id[entity.id] = (STRUCTURAL_LABEL_VALUE_TRIMMED,)
            counts[STRUCTURAL_LABEL_VALUE_TRIMMED] += 1
            continue

        clipped = _cell_boundary_clip(entity, value_spans)
        if clipped is not None:
            survivors.append(clipped)
            reasons_by_id[entity.id] = (STRUCTURAL_CELL_CLIP,)
            counts[STRUCTURAL_CELL_CLIP] += 1
            continue

        survivors.append(entity)

    summary = StructuralValidationSummary(
        applied=True,
        input_count=len(input_entities),
        output_count=len(survivors),
        clipped_count=counts[STRUCTURAL_CELL_CLIP],
        trimmed_count=counts[STRUCTURAL_LABEL_VALUE_TRIMMED],
        dropped_count=counts[STRUCTURAL_HEADING_REJECTED],
        by_reason={reason: count for reason, count in counts.items() if count},
    )
    return StructuralValidationResult(
        entities=survivors,
        summary=summary,
        reasons_by_entity_id=reasons_by_id,
        dropped_entity_ids=tuple(dropped_ids),
    )


def _is_heading_false_positive(
    entity: PiiEntity, headings: Sequence[PiiInputStructuralSpan]
) -> bool:
    """Rule 2: a rejectable-type entity fully contained in a heading span is not an entity."""
    if entity.entity_type not in _HEADING_REJECTABLE_TYPES:
        return False
    return any(
        heading.raw_start <= entity.start_offset and entity.end_offset <= heading.raw_end
        for heading in headings
    )


def _label_value_trim(
    entity: PiiEntity, pairs: Sequence[tuple[PiiInputStructuralSpan, PiiInputStructuralSpan]]
) -> PiiEntity | None:
    """Rule 3: an entity that overlaps a field label and reaches into its value is trimmed to the
    value, dropping the label prefix (and any tail past the value)."""
    best: tuple[int, int, str] | None = None  # (value_start, value_end, container_id)
    for label, value in pairs:
        overlaps_label = entity.start_offset < label.raw_end and entity.end_offset > label.raw_start
        reaches_value = entity.end_offset > value.raw_start
        if not (overlaps_label and reaches_value):
            continue
        key = (value.raw_start, value.raw_end, value.container_id)
        if best is None or key < best:
            best = key
    if best is None:
        return None
    value_start, value_end, _ = best
    new_start = max(entity.start_offset, value_start)
    new_end = min(entity.end_offset, value_end)
    if new_end <= new_start or (new_start == entity.start_offset and new_end == entity.end_offset):
        return None
    return _reslice(entity, new_start, new_end)


def _cell_boundary_clip(
    entity: PiiEntity, value_spans: Sequence[PiiInputStructuralSpan]
) -> PiiEntity | None:
    """Rule 1: an entity that starts inside a cell/field-value but overflows its end is clipped to
    that boundary (the entity does not span two cells)."""
    best_end: int | None = None
    for span in value_spans:
        starts_inside = span.raw_start <= entity.start_offset < span.raw_end
        overflows_end = entity.end_offset > span.raw_end
        if not (starts_inside and overflows_end):
            continue
        # Clip as little as possible: the furthest boundary the start still sits within.
        if best_end is None or span.raw_end > best_end:
            best_end = span.raw_end
    if best_end is None or best_end <= entity.start_offset:
        return None
    return _reslice(entity, entity.start_offset, best_end)


def _label_value_pairs(
    spans: Sequence[PiiInputStructuralSpan],
) -> tuple[tuple[PiiInputStructuralSpan, PiiInputStructuralSpan], ...]:
    labels = {span.container_id: span for span in spans if span.kind == "field_label"}
    values = {span.container_id: span for span in spans if span.kind == "field_value"}
    return tuple(
        (labels[container_id], values[container_id])
        for container_id in sorted(labels.keys() & values.keys())
    )


def _reslice(entity: PiiEntity, new_start: int, new_end: int) -> PiiEntity:
    """Return a copy of ``entity`` narrowed to the raw span ``[new_start, new_end)``.

    Only ever a sub-span of the original (``start <= new_start < new_end <= end``), so the new text
    is a slice of the existing entity text and page offsets shift by the same deltas. Any prior
    reading-text projection is cleared — this stage runs before projection, but a narrowed span
    would invalidate stale projection offsets, so they are reset defensively.
    """
    left = new_start - entity.start_offset
    right = new_end - entity.start_offset
    new_text = entity.text[left:right]
    updates: dict[str, object] = {
        "text": new_text,
        "start_offset": new_start,
        "end_offset": new_end,
        "reading_start_offset": None,
        "reading_end_offset": None,
        "projection_status": None,
        "projection_method": None,
    }
    if entity.page_start_offset is not None and entity.page_end_offset is not None:
        updates["page_start_offset"] = entity.page_start_offset + left
        updates["page_end_offset"] = entity.page_start_offset + right
    return entity.model_copy(update=updates)
