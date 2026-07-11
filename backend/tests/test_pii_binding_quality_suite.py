"""pii-binding-quality-suite: synthetic hard-case regression tests + a coverage-ratio gate.

Phase 2 of the text-anchor architecture feasibility audit's recommended sequence (after Phase 1,
reading-text row construction lineage). All data is synthetic; no private corpus fixtures. The goal
is a documented, regression-safe corpus of binding/coverage hard cases -- mixed-uniqueness entities
and header/footer repeats are already covered by ``test_anchor_bound_pii_e2e_conformance.py``; this
file adds the remaining named cases: adjacent same-line date/phone tokenizer fusion, a
punctuation/character-swallowing recognizer span, table-column canonical-range cross-contamination,
and a DOCX/no-geometry document -- plus a coverage-ratio gate over the whole corpus.

Every case asserts *invariants* ("never silently dropped", "never wrongly exact", coverage floors),
not exact segment layouts -- fixtures are not tuned to today's heuristics, and no recognizer/
detection behavior is changed by this suite.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from app.schemas import (
    DocumentTextAnchorGraphSummary,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorGraphValidation,
    DocumentTextAnchorRange,
    DocumentTextAnchorSource,
    DocumentTextAnchorV1,
    PiiEntity,
    PiiEntityProvenance,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


_DOCUMENT_ID = _hex("quality-suite-document")
_ORIGINAL_ID = _hex("quality-suite-original")
_AUDIT_ID = _hex("quality-suite-audit")
_TEXT_ID = _hex("quality-suite-text")


def _entity(
    entity_type: str,
    text: str,
    start: int,
    *,
    score: float = 0.9,
    recognizer: str = "TestRecognizer",
    provenance: PiiEntityProvenance | None = None,
) -> PiiEntity:
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=start + len(text),
        score=score,
        recognizer=recognizer,
        provenance=provenance,
    )


def _segment(
    reading_start: int, reading_end: int, raw_start: int, raw_end: int
) -> ReadingTextMapSegment:
    return ReadingTextMapSegment(
        reading_start=reading_start,
        reading_end=reading_end,
        raw_start=raw_start,
        raw_end=raw_end,
        mapping_status="exact",
    )


def _graph_from_raw(
    raw: str,
    *,
    reading: str | None = None,
    reading_map: list[ReadingTextMapSegment] | None = None,
    layout: str | None = None,
) -> DocumentTextAnchorGraphV1:
    """Build a real anchor graph through the full package/anchor pipeline for the given raw text.

    ``pages=[]``/no ``text_geometry`` (the same shape a DOCX extraction produces) unless the caller
    supplies canonical/layout views explicitly -- see ``test_docx_document_...`` below, which relies
    on exactly this default to prove the binding layer is geometry-agnostic.
    """
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version=("1" if reading is not None else None),
        reading_text=reading,
        reading_text_status=("heuristic" if reading is not None else None),
        reading_text_map_version=("1" if reading is not None else None),
        reading_text_map=reading_map or [],
        layout_text_result=layout,
    )
    artifact = TextArtifact(
        id=_TEXT_ID,
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        created_at="2026-07-10T10:00:00.000000Z",
        content=content,
    )
    return build_document_text_anchor_graph(build_document_text_package(artifact))


def _bind(entities: list[PiiEntity], graph: DocumentTextAnchorGraphV1):
    return bind_pii_entities_to_anchors(entities, graph, document_id=_DOCUMENT_ID)


def _manual_graph_with_ids(
    raw_char_count: int, spans: list[tuple[int, int]], *, id_seed: str
) -> DocumentTextAnchorGraphV1:
    """A hand-built raw-only anchor graph, like ``_manual_raw_graph`` in the anchor-binding tests.

    Every anchor's id is minted from ``id_seed`` rather than its span alone -- letting a test build
    two graphs over the *identical* raw spans whose anchor ids differ, simulating what a real
    graph-builder version change would do to a re-run over unchanged raw text.
    """
    anchors = [
        DocumentTextAnchorV1(
            anchor_id=_hex(f"{id_seed}-anchor-{index}-{start}-{end}"),
            anchor_kind="word",
            anchor_status="single_source",
            source_ranges=[
                DocumentTextAnchorRange(
                    source_name="technical_raw_text",
                    start=start,
                    end=end,
                    range_role="primary",
                    mapping_status="exact",
                    confidence=1.0,
                )
            ],
            normalized_shape="alpha",
            token_class="alpha",
            confidence=1.0,
            flags=["raw_primary"],
            warnings=[],
        )
        for index, (start, end) in enumerate(spans)
    ]
    warnings = ["missing_canonical_reading_text", "missing_layout_text"]
    summary = DocumentTextAnchorGraphSummary(
        total_anchors=len(anchors),
        anchors_with_raw_range=len(anchors),
        anchors_with_canonical_range=0,
        anchors_with_layout_range=0,
        raw_anchor_count=len(anchors),
        canonical_anchor_count=0,
        layout_anchor_count=0,
        anchors_with_raw_and_canonical=0,
        anchors_with_raw_only=len(anchors),
        anchors_with_canonical_only=0,
        anchors_with_layout=0,
        exact_count=0,
        projected_count=0,
        partial_count=0,
        missing_count=0,
        ambiguous_count=0,
        single_source_count=len(anchors),
        ambiguous_anchor_count=0,
        single_source_anchor_count=len(anchors),
        unmapped_raw_token_count=0,
        unmapped_canonical_token_count=0,
        canonical_unmapped_count=0,
        layout_unmapped_count=len(anchors),
        repeated_token_ambiguity_count=0,
        evidence_only_possible_count=0,
        raw_to_canonical_coverage_ratio=0.0,
        raw_to_layout_coverage_ratio=0.0,
    )
    validation = DocumentTextAnchorGraphValidation(
        status="degraded",
        warning_count=len(warnings),
        blocker_count=0,
        invalid_range_count=0,
        overlapping_anchor_range_count=0,
        warnings=warnings,  # type: ignore[arg-type]
        blockers=[],
    )
    sources = [
        DocumentTextAnchorSource(
            source_name="technical_raw_text",
            available=True,
            text_char_count=raw_char_count,
            range_count=len(anchors),
            mapped_anchor_count=len(anchors),
        ),
        DocumentTextAnchorSource(source_name="canonical_reading_text", available=False),
        DocumentTextAnchorSource(source_name="layout_text", available=False),
    ]
    return DocumentTextAnchorGraphV1(
        document_id=_DOCUMENT_ID,
        text_artifact_id=_TEXT_ID,
        source_artifact_id=_TEXT_ID,
        package_id=_TEXT_ID,
        package_contract_version="1.0",
        created_at="2026-07-10T10:00:00.000000Z",
        sources=sources,
        anchors=anchors,
        summary=summary,
        validation=validation,
        warnings=warnings,  # type: ignore[arg-type]
    )


# --- Hard case 1: adjacent same-line date + phone tokenizer fusion ------------------------------


def test_adjacent_date_and_phone_with_no_separator_are_fused_but_never_lost_or_merged() -> None:
    """The tokenizer's phone pattern can span a date and a directly adjacent phone number.

    When nothing but whitespace separates them (``\\+?\\d[\\d \\t()./\\-]{5,}\\d``), they fuse into
    one raw anchor -- a real, regression-locked limitation, not a hypothetical. Binding must still
    degrade honestly (`partial`, never a false `exact`) and must never drop or merge the two
    entities' identities into one.
    """
    raw = "14.03.1978 0664 1234567"
    graph = _graph_from_raw(raw)
    date_entity = _entity("DATE", "14.03.1978", 0)
    phone_entity = _entity("PHONE", "0664 1234567", 11)

    bound, summary = _bind([date_entity, phone_entity], graph)

    assert len(bound) == 2
    assert {entity.value for entity in bound} == {"14.03.1978", "0664 1234567"}
    assert bound[0].entity_id != bound[1].entity_id
    for entity in bound:
        assert entity.binding_status == "partial"
        assert entity.identity_basis == "anchor_partial"
        assert "anchor_partial_overlap" in entity.binding_reasons
    assert summary.anchor_bound_ratio == 1.0
    assert summary.exact_bound_ratio == 0.0


def test_adjacent_date_and_phone_separated_by_a_label_word_bind_exactly() -> None:
    """Positive control: the same two values, with an ordinary label between them, are not fused --

    the fusion above is specifically about direct adjacency, not phones/dates in general.
    """
    raw = "Geburtsdatum: 14.03.1978 Tel: 0664 1234567"
    graph = _graph_from_raw(raw)
    date_entity = _entity("DATE", "14.03.1978", raw.index("14.03.1978"))
    phone_entity = _entity("PHONE", "0664 1234567", raw.index("0664 1234567"))

    bound, summary = _bind([date_entity, phone_entity], graph)

    assert len(bound) == 2
    for entity in bound:
        assert entity.binding_status == "exact"
        assert entity.identity_basis == "anchor_exact"
    assert summary.exact_bound_ratio == 1.0


# --- Hard case 2: punctuation/character-swallowing recognizer span (partial binding) ------------


def test_recognizer_span_missing_a_leading_plus_sign_binds_partially_never_silently_exact() -> None:
    """A recognizer/validator quirk can trim a leading character (here, a phone number's "+") from

    its detected span while the tokenizer's own phone token still includes it. Binding must reflect
    that honestly as `partial`, never claim `exact` for a span narrower than its anchor.
    """
    raw = "Tel: +43 664 1234567"
    graph = _graph_from_raw(raw)
    full_start = raw.index("+43")
    entity = _entity("PHONE", "43 664 1234567", full_start + 1)

    bound, _summary = _bind([entity], graph)
    [bound_entity] = bound

    assert bound_entity.binding_status == "partial"
    assert bound_entity.identity_basis == "anchor_partial"
    assert "anchor_partial_overlap" in bound_entity.binding_reasons


# --- Hard case 3: table columns -- canonical range must never cross-contaminate -----------------


def test_table_column_reordering_never_cross_contaminates_entity_canonical_ranges() -> None:
    """Two table-cell values swap order between raw (row-major) and reading (column-reordered) text.

    Each entity must resolve its own, correct canonical range -- never the other cell's -- proving
    binding is by anchor identity, not by proximity or processing order.
    """
    raw = "Alpha\tBeta"
    reading = "Beta\nAlpha"
    reading_map = sorted(
        [
            _segment(
                reading.index("Alpha"),
                reading.index("Alpha") + len("Alpha"),
                raw.index("Alpha"),
                raw.index("Alpha") + len("Alpha"),
            ),
            _segment(
                reading.index("Beta"),
                reading.index("Beta") + len("Beta"),
                raw.index("Beta"),
                raw.index("Beta") + len("Beta"),
            ),
        ],
        key=lambda segment: segment.reading_start,
    )
    graph = _graph_from_raw(raw, reading=reading, reading_map=reading_map)
    alpha_entity = _entity("COMPANY", "Alpha", raw.index("Alpha"))
    beta_entity = _entity("COMPANY", "Beta", raw.index("Beta"))

    bound, summary = _bind([alpha_entity, beta_entity], graph)

    by_value = {entity.value: entity for entity in bound}
    alpha_canonical = next(
        ref for ref in by_value["Alpha"].anchor_refs if ref.source_name == "canonical_reading_text"
    )
    beta_canonical = next(
        ref for ref in by_value["Beta"].anchor_refs if ref.source_name == "canonical_reading_text"
    )
    assert (alpha_canonical.source_range.start, alpha_canonical.source_range.end) == (
        reading.index("Alpha"),
        reading.index("Alpha") + len("Alpha"),
    )
    assert (beta_canonical.source_range.start, beta_canonical.source_range.end) == (
        reading.index("Beta"),
        reading.index("Beta") + len("Beta"),
    )
    assert summary.exact_bound_ratio == 1.0


# --- Hard case 4: DOCX / no-geometry document ----------------------------------------------------


def test_docx_document_without_page_geometry_binds_normally() -> None:
    """DOCX/pageless documents build ``TextContent`` with ``pages=[]`` and no ``text_geometry``.

    Anchor binding is purely raw-offset-based and must work identically to a paginated document --
    a regression lock, since a future geometry-dependent shortcut in this module would silently
    break DOCX/no-geometry documents.
    """
    raw = (
        "Vertrag ueber die Erbringung von Dienstleistungen\n\n"
        "Zwischen Anna Musterfrau und der Beispiel GmbH wird folgender Vertrag geschlossen."
    )
    graph = _graph_from_raw(raw)
    entity = _entity("PERSON", "Anna Musterfrau", raw.index("Anna Musterfrau"))

    bound, _summary = _bind([entity], graph)
    [bound_entity] = bound

    assert bound_entity.binding_status == "exact"
    assert bound_entity.identity_basis == "anchor_exact"


# --- Hard case 5: trailing punctuation within a detected span -----------------------------------


def test_trailing_punctuation_within_span_does_not_downgrade_a_complete_binding() -> None:
    """A detector span that runs one character past a value into trailing punctuation (no
    separating space) must stay ``exact`` and keep its canonical range -- mirroring the existing
    trailing-whitespace guarantee. The anchor graph gives every non-whitespace character its own
    anchor (the tokenizer's symbol fallback), so a detection that fully contains that trailing
    punctuation anchor is still a complete binding, never a partial one."""
    raw = "Wien, Oesterreich liegt in Europa."
    reading = raw
    reading_map = [_segment(0, len(reading), 0, len(raw))]
    graph = _graph_from_raw(raw, reading=reading, reading_map=reading_map)
    end = raw.index(",") + 1  # span includes the trailing comma, no separating space
    entity = _entity("LOCATION", raw[:end], 0)

    bound, _summary = _bind([entity], graph)
    [bound_entity] = bound

    assert bound_entity.binding_status == "exact"
    assert bound_entity.identity_basis == "anchor_exact"
    assert "canonical_range_missing" not in bound_entity.binding_reasons
    # One display ref per contributing anchor (the word "Wien" and the trailing comma symbol); their
    # combined envelope -- the same min/max the entity contract computes -- must reach the comma,
    # not stop short of it the way a partial/downgraded binding would.
    canonical_refs = [
        ref for ref in bound_entity.anchor_refs if ref.source_name == "canonical_reading_text"
    ]
    assert canonical_refs
    starts = [ref.source_range.start for ref in canonical_refs if ref.source_range is not None]
    ends = [ref.source_range.end for ref in canonical_refs if ref.source_range is not None]
    assert (min(starts), max(ends)) == (0, end)


# --- Hard case 6: genuinely ambiguous overlapping candidate anchors ------------------------------


def test_mutually_overlapping_candidate_anchors_bind_ambiguous_never_guessed() -> None:
    """Two candidate anchors whose raw ranges overlap each other give no single anchor set a
    detection could unambiguously belong to. Binding must surface this honestly as ``ambiguous``,
    evidence-only identity -- never silently picking one candidate (e.g. by anchor/processing
    order) the way a weaker heuristic might."""
    raw_char_count = 15
    graph = _manual_graph_with_ids(raw_char_count, [(0, 10), (5, 15)], id_seed="overlap")
    entity = _entity("MISC", "x" * raw_char_count, 0)

    bound, summary = _bind([entity], graph)
    [bound_entity] = bound

    assert bound_entity.binding_status == "ambiguous"
    assert bound_entity.identity_basis == "evidence_only"
    assert "anchor_ambiguous" in bound_entity.binding_reasons
    assert "evidence_only_identity" in bound_entity.binding_reasons
    assert bound_entity.anchor_set.anchor_ids == []
    assert summary.exact_bound_ratio == 0.0


# --- Coverage-ratio gate --------------------------------------------------------------------------


def test_hard_case_corpus_coverage_ratios_meet_documented_floors() -> None:
    """Metrics gate over the hard-case corpus: each fixture class must meet a documented minimum

    ``anchor_bound_ratio`` floor. Floors lock in today's honest coverage (including the fused-token
    case's degraded-but-never-lost 1.0 anchor_bound_ratio at 0.0 exact_bound_ratio) rather than
    claim perfection; a future regression that drops below these floors fails this test instead of
    silently degrading binding coverage in production.
    """
    fused_raw = "14.03.1978 0664 1234567"
    labeled_raw = "Geburtsdatum: 14.03.1978 Tel: 0664 1234567"
    truncated_raw = "Tel: +43 664 1234567"
    docx_raw = "Zwischen Anna Musterfrau und der Beispiel GmbH wird folgender Vertrag geschlossen."
    punctuation_raw = "Wien, Oesterreich liegt in Europa."

    cases = [
        (
            "adjacent_fusion",
            [_entity("DATE", "14.03.1978", 0), _entity("PHONE", "0664 1234567", 11)],
            _graph_from_raw(fused_raw),
            1.0,
        ),
        (
            "labeled_no_fusion",
            [
                _entity("DATE", "14.03.1978", labeled_raw.index("14.03.1978")),
                _entity("PHONE", "0664 1234567", labeled_raw.index("0664 1234567")),
            ],
            _graph_from_raw(labeled_raw),
            1.0,
        ),
        (
            "truncated_leading_plus",
            [_entity("PHONE", "43 664 1234567", truncated_raw.index("+43") + 1)],
            _graph_from_raw(truncated_raw),
            1.0,
        ),
        (
            "docx_no_geometry",
            [_entity("PERSON", "Anna Musterfrau", docx_raw.index("Anna Musterfrau"))],
            _graph_from_raw(docx_raw),
            1.0,
        ),
        (
            "trailing_punctuation",
            [_entity("LOCATION", punctuation_raw[: punctuation_raw.index(",") + 1], 0)],
            _graph_from_raw(
                punctuation_raw,
                reading=punctuation_raw,
                reading_map=[_segment(0, len(punctuation_raw), 0, len(punctuation_raw))],
            ),
            1.0,
        ),
    ]
    for label, entities, graph, floor in cases:
        _bound, summary = _bind(entities, graph)
        assert summary.anchor_bound_ratio >= floor, label


# --- Builder-version identity drift ---------------------------------------------------------------
#
# The feasibility audit's documented constraint: "anchor ids are stable per (text artifact bytes x
# graph builder version)", which is harmless *only* because nothing durable references an anchor id
# today. The entity-contract's anchor-derived `entity_id` is computed fresh on every request from
# a freshly-built anchor graph -- it is never written to disk. Durable review decisions
# (`pii_review_service.py`) key on `PiiEntity.id` (the raw detection occurrence id from
# `pii_result`) and are additionally scoped to the `pii_result` artifact id, never any anchor id.


def test_anchor_derived_entity_id_drifts_with_the_graph_but_occurrence_identity_does_not() -> None:
    """Simulate a graph-builder version change (same raw text, different minted anchor ids) and

    prove the two identities behave exactly as the audit's constraint requires: the anchor-derived
    `entity_id` is free to change (it is never persisted), while the underlying PII occurrence id
    that durable review decisions actually key on is completely unaffected -- so a builder-version
    bump can never silently invalidate a stored review decision.
    """
    raw = "Wien"
    entity = _entity("LOCATION", "Wien", 0)
    graph_v1 = _manual_graph_with_ids(len(raw), [(0, 4)], id_seed="builder-v1")
    graph_v2 = _manual_graph_with_ids(len(raw), [(0, 4)], id_seed="builder-v2")

    bound_v1, _summary_v1 = _bind([entity], graph_v1)
    bound_v2, _summary_v2 = _bind([entity], graph_v2)
    [entity_v1] = bound_v1
    [entity_v2] = bound_v2

    # The anchor-derived contract identity is allowed to drift with the builder...
    assert entity_v1.binding_status == entity_v2.binding_status == "exact"
    assert entity_v1.anchor_set.anchor_ids != entity_v2.anchor_set.anchor_ids
    assert entity_v1.entity_id != entity_v2.entity_id
    # ...but the detection occurrence id review decisions actually reference never changes, because
    # it is not derived from the anchor graph at all -- it is the same `PiiEntity.id` passed in.
    detection_id_v1 = entity_v1.source_observations[0].detection_id
    detection_id_v2 = entity_v2.source_observations[0].detection_id
    assert detection_id_v1 == entity.id
    assert detection_id_v2 == entity.id
    assert detection_id_v1 == detection_id_v2


def test_no_durable_pii_module_references_an_anchor_id() -> None:
    """Guard the audit's stated safety condition itself: if a future change starts persisting an

    anchor id in the review-decision or feedback JSONL schemas, this must be a conscious, reviewed
    decision (and must pin a builder version alongside it) -- not something that slips in silently.
    """
    import inspect

    from app.services import feedback_service, pii_review_service

    for module in (pii_review_service, feedback_service):
        source = inspect.getsource(module)
        assert "anchor_id" not in source, module.__name__
        assert "entity_id" not in source, module.__name__
