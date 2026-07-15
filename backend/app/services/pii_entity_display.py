"""Shared anchor-bound display/mapping-status helpers (ADR-0029, ADR-0031 Phase C).

Extracted from ``pii_entity_contract.py`` so a second consumer (``pii_review_result.py``, Review
Result v1) can classify the same canonical-mapping quality and identity-gap reason codes without
duplicating the logic or importing the entity-contract module itself (which depends on
``pii_review_service.py`` — importing it back from a review-result builder would be circular).

This module owns no state and mutates nothing: it is a pure function library over
:class:`AnchorBoundPiiEntityV1`/:class:`PiiEntity` inputs already produced by
``pii_anchor_binding.py``. Behavior is unchanged from its original private, in-module form.
"""

from __future__ import annotations

from app.schemas import (
    AnchorBoundPiiEntityV1,
    DocumentTextAnchorSourceName,
    PiiEntity,
    PiiEntityDisplaySpan,
    PiiEntityMappingStatus,
    PiiEntityReviewReasonCode,
)

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


def classify_mapping_status(
    entity: PiiEntity,
    canonical_available: bool,
    reading_text: str | None,
) -> PiiEntityMappingStatus:
    """Classify how the entity's raw span projects onto the canonical reading text (display view).

    Uses the entity's own per-entity projection only (``reading_text_projection``): ``exact`` for a
    byte-exact offset-map projection, ``projected`` for a unique text-match, otherwise the unmapped
    states ``partial``/``ambiguous``/``missing`` — never dropped. ``not_applicable`` when the run
    produced no canonical text at all. The anchor graph is deliberately NOT consulted here anymore:
    its bridged canonical range was line/block-granular and over-marked whole paragraphs (see the
    scan experiment 2026-07-15). Detection still runs on the faithful raw text, so a ``missing``
    display mapping never means a missed detection — only a mark shown in the technical view.
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


def canonical_display_range(
    entity: PiiEntity,
    mapping_status: PiiEntityMappingStatus,
) -> PiiEntityDisplaySpan | None:
    """The reading-view highlight range: the entity's own precise reading offset, or ``None``.

    A mark is either exactly right (the per-entity offset projection resolved) or absent (then it
    shows in the technical raw view plus the "only visible technically" notice). The anchor-derived
    envelope is no longer used — it spanned whole lines/blocks and could bind to the wrong block.
    """
    if mapping_status not in ("exact", "projected"):
        return None
    if entity.reading_start_offset is None or entity.reading_end_offset is None:
        return None
    return PiiEntityDisplaySpan(
        start=entity.reading_start_offset,
        end=entity.reading_end_offset,
        projection_method=entity.projection_method,
    )


def anchor_display_range(
    bound: AnchorBoundPiiEntityV1, source_name: DocumentTextAnchorSourceName
) -> tuple[PiiEntityDisplaySpan, bool] | None:
    """The entity's bridged display range for ``source_name``, plus whether every contributing
    anchor ref was itself byte-exact (``ref.mapping_status`` is ``exact``/``None``, never
    ``normalized``/``merged``). ``None`` is treated as exact for refs built before this field
    existed and for the raw/entity-span roles, which never carry a display projection here."""
    display_refs = [
        (ref.source_range, ref.mapping_status)
        for ref in bound.anchor_refs
        if ref.source_name == source_name
        and ref.source_range is not None
        and ref.binding_role == "display_span"
    ]
    if bound.binding_status != "exact" or not display_refs:
        return None
    # pii_anchor_binding only ever emits these display refs when the entity's own boundary anchors
    # resolved (bridgeable), so a non-empty list here is already a safe envelope even when an
    # interior anchor was skipped (e.g. individually ambiguous elsewhere in the document) — no
    # separate full-coverage check is needed.
    ordered = sorted(display_refs, key=lambda item: (item[0].start, item[0].end))
    all_exact = all(status in (None, "exact") for _range, status in display_refs)
    span = PiiEntityDisplaySpan(
        start=ordered[0][0].start,
        end=ordered[-1][0].end,
        projection_method="offset_map",
    )
    return span, all_exact


def identity_reason_codes(
    binding_status: str,
    mapping_status: PiiEntityMappingStatus,
) -> list[PiiEntityReviewReasonCode]:
    """The reasons this entity needs human review, from anchor-binding and display-mapping gaps
    alone (never overlap/provenance reasons — those stay entity-contract-specific). Deterministic
    order; ``exact``/``not_applicable`` add nothing."""
    codes: list[PiiEntityReviewReasonCode] = []
    binding_reason = _BINDING_REVIEW_REASON.get(binding_status)
    if binding_reason is not None:
        codes.append(binding_reason)
    mapping_reason = _MAPPING_REASON.get(mapping_status)
    if mapping_reason is not None:
        codes.append(mapping_reason)
    return codes
