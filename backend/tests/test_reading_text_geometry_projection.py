"""Geometry-backed reading projection (post-render; NOT construction-time lineage).

All data is synthetic. This suite proves the corrected identity discipline of
``reading_text_geometry_projection.py`` — a hardening pass after a contradiction audit found that an
earlier version of this mechanism could silently bind duplicate full-line values to *inverted*
canonical occurrences (both confidently labeled ``exact``, ``confidence=1.0``) depending only on the
order geometry lines happened to be processed in. Determinism is not proof of identity.

This module runs strictly **after** Canonical Reading Text already exists (it receives the finished
string as a plain argument) and re-derives canonical<->raw correspondence via exact, boundary-
respecting substring search over that finished string — it is a post-render projection, not
lineage emitted by the reading-text builder itself. It is preferred over the older post-hoc
unique-token ``reading_text_map`` when it can resolve a line unambiguously, but neither mechanism is
authoritative construction identity. Genuine builder-emitted construction-time lineage (a real
``anchor-first-text-package-v2``) remains unimplemented; that is a separate, later piece of work.

Coverage (mapped to the mandatory test list from the hardening task):

- A/B: a duplicate full-line value never receives a silently-inverted or guessed ``exact`` binding,
  regardless of geometry processing order — both occurrences are declined and marked ``ambiguous``.
- C: duplicate synthetic label lines are declined the same way.
- D: the same full value on two different pages is declined (no page-order-based identity guess).
- E: two genuinely distinct lines sharing a repeated sub-token ("GmbH") still resolve safely.
- F: distinct, reordered full-line values still resolve safely.
- G: no synthetic value ever appears in segment/summary/reason-code metadata.
- H: when the projection cannot resolve a line, the package/graph fallback status stays explicit.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.schemas import (
    PiiEntity,
    ReadingTextGeometryProjectionMap,
    TextArtifact,
    TextContent,
    TextGeometry,
    TextGeometryPage,
    TextLineGeometry,
    TextPageResult,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors
from app.services.reading_text_geometry_projection import (
    build_reading_text_geometry_projection_map,
)
from app.services.reading_text_projection import build_reading_text_map

_DOC = "a" * 32


def _line_spans(raw: str) -> list[tuple[int, int]]:
    """Half-open (start, end) page offsets for each non-empty line of a single-page raw text."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in raw.split("\n"):
        if line:
            spans.append((offset, offset + len(line)))
        offset += len(line) + 1
    return spans


def _geometry(raw: str, *, line_order: list[int] | None = None) -> TextGeometry:
    """Line geometry for a single page. ``line_order`` permutes which raw span each geometry line
    index is assigned to, to test that processing order never determines identity outcomes."""
    spans = _line_spans(raw)
    ordered_spans = [spans[i] for i in line_order] if line_order is not None else spans
    lines = [
        TextLineGeometry(
            line_index=index,
            canonical_start=start,
            canonical_end=end,
            page_start=start,
            page_end=end,
            x0=0.0,
            y0=float(index),
            x1=1.0,
            y1=float(index) + 0.5,
            source="pdf_text_layer",
        )
        for index, (start, end) in enumerate(ordered_spans, start=1)
    ]
    return TextGeometry(
        pages=[
            TextGeometryPage(
                page_number=1,
                page_width=10.0,
                page_height=float(len(lines)) + 2.0,
                coordinate_unit="pdf_points",
                source="pdf_text_layer",
                status="complete",
                lines=lines,
            )
        ],
        coverage=1.0,
    )


def _two_page_geometry(page_line_spans: dict[int, list[tuple[int, int]]]) -> TextGeometry:
    """Line geometry spanning multiple pages, each with its own page-local spans."""
    pages = []
    for page_number, spans in page_line_spans.items():
        lines = [
            TextLineGeometry(
                line_index=index,
                canonical_start=start,
                canonical_end=end,
                page_start=start,
                page_end=end,
                x0=0.0,
                y0=float(index),
                x1=1.0,
                y1=float(index) + 0.5,
                source="pdf_text_layer",
            )
            for index, (start, end) in enumerate(spans, start=1)
        ]
        pages.append(
            TextGeometryPage(
                page_number=page_number,
                page_width=10.0,
                page_height=float(len(lines)) + 2.0,
                coordinate_unit="pdf_points",
                source="pdf_text_layer",
                status="complete",
                lines=lines,
            )
        )
    return TextGeometry(pages=pages, coverage=1.0)


def _project(
    raw: str, reading: str, *, line_order: list[int] | None = None
) -> ReadingTextGeometryProjectionMap | None:
    pages = [_page(raw)]
    return build_reading_text_geometry_projection_map(
        document_id=_DOC,
        reading_text=reading,
        raw_text=raw,
        pages=pages,
        text_geometry=_geometry(raw, line_order=line_order),
    )


def _page(raw: str, page_number: int = 1) -> TextPageResult:
    return TextPageResult(
        page_number=page_number,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw,
        text_char_count=len(raw),
    )


def _content(
    raw: str, reading: str, *, with_projection: bool = True, line_order: list[int] | None = None
) -> TextContent:
    pages = [_page(raw)]
    projection = _project(raw, reading, line_order=line_order) if with_projection else None
    return TextContent(
        document_id=_DOC,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        source="pdf_text_layer",
        text=raw,
        text_char_count=len(raw),
        pages=pages,
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version="1",
        reading_text=reading,
        reading_text_status="heuristic",
        reading_text_map_version="1",
        reading_text_map=build_reading_text_map(raw, reading, pages),
        reading_text_geometry_projection_map_version="1" if projection is not None else None,
        reading_text_geometry_projection_map=projection,
    )


def _artifact(content: TextContent) -> TextArtifact:
    return TextArtifact(
        id="e" * 32,
        document_id=_DOC,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        created_at="2026-07-10T09:00:00.000000Z",
        content=content,
    )


def _entity(raw: str, entity_type: str, value: str, occurrence: int = 0) -> PiiEntity:
    start = -1
    for _ in range(occurrence + 1):
        start = raw.index(value, start + 1)
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=value,
        start_offset=start,
        end_offset=start + len(value),
        score=0.9,
        recognizer="Synthetic",
    )


# --- Mechanics: segments carry raw ranges, ids are deterministic, gaps are marked inserted --------


def test_projection_emits_segments_with_raw_ranges_and_deterministic_ids() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    first = _project(raw, reading)
    second = _project(raw, reading)
    assert first is not None and second is not None
    assert first.lineage_source == "geometry_projection"
    mapped = [segment for segment in first.segments if segment.mapping_status == "exact"]
    assert len(mapped) == 2
    for segment in mapped:
        assert segment.source_range is not None
        assert segment.confidence == 1.0
        assert reading[segment.canonical_start : segment.canonical_end] == raw[
            segment.source_range.start : segment.source_range.end
        ]
    assert [segment.segment_id for segment in first.segments] == [
        segment.segment_id for segment in second.segments
    ]


def test_projection_marks_true_gaps_as_inserted_not_ambiguous() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    projection = _project(raw, raw)
    assert projection is not None
    inserted = [s for s in projection.segments if s.mapping_status == "inserted"]
    assert inserted, "line separators must be classified as inserted (no raw correspondence at all)"
    for segment in inserted:
        assert segment.source_range is None
        assert segment.segment_role == "derived"
    assert projection.summary.inserted_segments == len(inserted)
    assert projection.summary.ambiguous_segments == 0


def test_projection_returns_none_without_geometry_or_reading_text() -> None:
    raw = "Anna Beispiel\n"
    pages = [_page(raw)]
    assert (
        build_reading_text_geometry_projection_map(
            document_id=_DOC, reading_text=raw, raw_text=raw, pages=pages, text_geometry=None
        )
        is None
    )
    assert (
        build_reading_text_geometry_projection_map(
            document_id=_DOC,
            reading_text=None,
            raw_text=raw,
            pages=pages,
            text_geometry=_geometry(raw),
        )
        is None
    )


def test_projection_declines_reformatted_lines_instead_of_guessing() -> None:
    raw = "1\tService\t100,00\nAnna Beispiel\n"
    reading = "1 | Service | 100,00\nAnna Beispiel\n"
    projection = _project(raw, reading)
    assert projection is not None
    attributed = [
        raw[s.source_range.start : s.source_range.end]
        for s in projection.segments
        if s.source_range is not None
    ]
    assert "Anna Beispiel" in attributed
    assert not any("Service" in value for value in attributed)


# --- A/B. Duplicate full-line value: never a silently-inverted or guessed exact binding -----------


def test_duplicate_full_line_is_declined_not_guessed() -> None:
    """Two source lines share the exact same complete value (header + footer company name)."""
    raw = "Muster Handels GmbH\noffice@muster.at\nMuster Handels GmbH\n"
    reading = raw
    projection = _project(raw, reading)
    assert projection is not None
    exact = [s for s in projection.segments if s.mapping_status == "exact"]
    ambiguous = [s for s in projection.segments if s.mapping_status == "ambiguous"]
    # The unique email still resolves; the duplicate company line never does.
    assert len(exact) == 1
    assert raw[exact[0].source_range.start : exact[0].source_range.end] == "office@muster.at"
    assert len(ambiguous) == 2
    for segment in ambiguous:
        assert segment.source_range is None
        assert segment.confidence is None
        assert "duplicate_source_value" in segment.reason_codes
        assert "multiple_canonical_candidates" in segment.reason_codes
        assert "identity_ambiguous" in segment.reason_codes
        assert "relative_order_not_identity_proof" in segment.reason_codes


def test_duplicate_full_line_result_is_invariant_to_geometry_processing_order() -> None:
    """The contradiction-audit case: same raw/canonical text, only geometry iteration order
    differs (as if the builder visited the footer line before the header line). The outcome must
    not flip into two mutually-inverted ``exact`` identities — it must stay identically ambiguous.
    """
    raw = "Muster Handels GmbH\noffice@muster.at\nMuster Handels GmbH\n"
    reading = raw

    order_a = _project(raw, reading, line_order=[0, 1, 2])  # header, email, footer
    order_b = _project(raw, reading, line_order=[2, 1, 0])  # footer, email, header
    assert order_a is not None and order_b is not None

    def _statuses(projection: ReadingTextGeometryProjectionMap) -> list[tuple[int, int, str]]:
        return [
            (s.canonical_start, s.canonical_end, s.mapping_status) for s in projection.segments
        ]

    assert _statuses(order_a) == _statuses(order_b)
    # Neither run ever claims an ``exact`` identity for either duplicate occurrence.
    for projection in (order_a, order_b):
        exact_ranges = {
            (s.canonical_start, s.canonical_end)
            for s in projection.segments
            if s.mapping_status == "exact"
        }
        assert (0, 19) not in exact_ranges
        assert (37, 56) not in exact_ranges
        assert projection.summary.ambiguous_segments == 2


# --- C. Duplicate synthetic label lines are declined the same way ---------------------------------


def test_duplicate_label_lines_are_declined() -> None:
    raw = "Adresse\noffice@muster.at\nAdresse\n"
    reading = raw
    projection = _project(raw, reading)
    assert projection is not None
    ambiguous_ranges = {
        (s.canonical_start, s.canonical_end)
        for s in projection.segments
        if s.mapping_status == "ambiguous"
    }
    assert (0, 7) in ambiguous_ranges
    assert (25, 32) in ambiguous_ranges
    exact = [s for s in projection.segments if s.mapping_status == "exact"]
    assert len(exact) == 1
    assert raw[exact[0].source_range.start : exact[0].source_range.end] == "office@muster.at"


# --- D. Same complete value on two different pages is declined, not assumed by page order ---------


def test_same_value_on_different_pages_is_declined() -> None:
    raw_page1 = "1010 Wien\n"
    raw_page2 = "1010 Wien\n"
    pages = [_page(raw_page1, page_number=1), _page(raw_page2, page_number=2)]
    reading = "1010 Wien\n\n1010 Wien\n"
    geometry = _two_page_geometry({1: [(0, 9)], 2: [(0, 9)]})
    projection = build_reading_text_geometry_projection_map(
        document_id=_DOC,
        reading_text=reading,
        raw_text=raw_page1,
        pages=pages,
        text_geometry=geometry,
    )
    assert projection is not None
    assert projection.summary.mapped_segments == 0
    assert projection.summary.ambiguous_segments == 2
    for segment in projection.segments:
        if segment.mapping_status == "ambiguous":
            assert segment.source_range is None
            assert "duplicate_source_value" in segment.reason_codes


# --- E. Distinct lines sharing a repeated sub-token still resolve safely --------------------------


def test_distinct_lines_with_repeated_suffix_still_resolve() -> None:
    raw = "Muster Handels GmbH\nBeispiel Bau GmbH\noffice@muster.at\n"
    reading = "office@muster.at\nMuster Handels GmbH\nBeispiel Bau GmbH\n"
    projection = _project(raw, reading)
    assert projection is not None
    exact = [s for s in projection.segments if s.mapping_status == "exact"]
    assert len(exact) == 3
    assert projection.summary.ambiguous_segments == 0
    mapped = {
        raw[s.source_range.start : s.source_range.end]: (s.canonical_start, s.canonical_end)
        for s in exact
    }
    assert reading[slice(*mapped["Muster Handels GmbH"])] == "Muster Handels GmbH"
    assert reading[slice(*mapped["Beispiel Bau GmbH"])] == "Beispiel Bau GmbH"
    assert mapped["Muster Handels GmbH"] != mapped["Beispiel Bau GmbH"]


# --- F. Distinct, reordered full-line values still resolve safely ---------------------------------


def test_distinct_reordered_lines_still_resolve() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = "office@muster.at\nAnna Beispiel\n"
    projection = _project(raw, reading)
    assert projection is not None
    exact = {
        raw[s.source_range.start : s.source_range.end]: (s.canonical_start, s.canonical_end)
        for s in projection.segments
        if s.mapping_status == "exact"
    }
    assert reading[slice(*exact["Anna Beispiel"])] == "Anna Beispiel"
    assert reading[slice(*exact["office@muster.at"])] == "office@muster.at"


# --- Package + anchor graph integration: prefer projection, label it, never claim construction ----


def test_package_lineage_summary_names_geometry_projection_not_construction() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    package = build_document_text_package(_artifact(_content(raw, reading)))
    assert package.lineage_summary is not None
    assert package.lineage_summary.lineage_source == "geometry_projection"
    assert package.lineage_summary.geometry_projection_available is True

    fallback_package = build_document_text_package(
        _artifact(_content(raw, reading, with_projection=False))
    )
    assert fallback_package.lineage_summary is not None
    assert fallback_package.lineage_summary.lineage_source == "fallback_text_match"
    assert fallback_package.lineage_summary.geometry_projection_available is False


def test_anchor_graph_reports_geometry_projection_source_explicitly() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    graph = build_document_text_anchor_graph(
        build_document_text_package(_artifact(_content(raw, reading)))
    )
    assert graph.lineage_summary is not None
    assert graph.lineage_summary.lineage_source == "geometry_projection"
    assert graph.summary.canonical_geometry_projection_count > 0
    assert any("canonical_geometry_projection" in anchor.flags for anchor in graph.anchors)


def test_duplicate_value_ambiguity_survives_into_anchor_binding() -> None:
    """H (fallback explicitness): a duplicate value the projection declines must still surface as
    an explicit, reason-coded gap at the anchor/binding layer — never a silent or guessed identity.

    Uses a genuinely *reordered* raw/reading pair (not byte-identical): when raw text equals
    canonical text verbatim, the pre-existing post-hoc unique-token map's whole-document identity
    shortcut is legitimately correct (nothing was rendered differently, so every raw offset
    trivially equals its own canonical offset) — that is not the ambiguous case this test targets.
    Reordering the (unique) email relative to the two duplicate company lines keeps raw != reading
    so the shortcut cannot fire, while the duplicate value itself remains genuinely unresolvable by
    either mechanism.
    """
    raw = "Muster Handels GmbH\noffice@muster.at\nMuster Handels GmbH\n"
    reading = "Muster Handels GmbH\nMuster Handels GmbH\noffice@muster.at\n"
    content = _content(raw, reading)
    graph = build_document_text_anchor_graph(build_document_text_package(_artifact(content)))
    entities = [
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=0),
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=1),
    ]
    bound, summary = bind_pii_entities_to_anchors(entities, graph, document_id=_DOC)
    assert summary.entities_with_canonical_range == 0
    for entity in bound:
        assert "canonical_range_missing" in entity.binding_reasons
        assert "repeated_token_ambiguity" in entity.binding_reasons


def test_distinct_repeated_suffix_entities_still_bind_with_canonical_range() -> None:
    """E, through the full package -> graph -> binding chain."""
    raw = "Muster Handels GmbH\nBeispiel Bau GmbH\noffice@muster.at\n"
    reading = "office@muster.at\nMuster Handels GmbH\nBeispiel Bau GmbH\n"
    content = _content(raw, reading)
    graph = build_document_text_anchor_graph(build_document_text_package(_artifact(content)))
    entities = [
        _entity(raw, "ORG", "Muster Handels GmbH"),
        _entity(raw, "ORG", "Beispiel Bau GmbH"),
    ]
    bound, summary = bind_pii_entities_to_anchors(entities, graph, document_id=_DOC)
    assert summary.entities_with_canonical_range == 2
    assert summary.missing_canonical_range_count == 0
    for entity in bound:
        assert entity.binding_status == "exact"
        assert "canonical_range_missing" not in entity.binding_reasons
        assert "repeated_token_ambiguity" not in entity.binding_reasons


# --- G. Privacy: no synthetic value leaks into projection/anchor/entity metadata ------------------


def test_geometry_projection_metadata_is_text_free() -> None:
    raw = "Muster Handels GmbH\noffice@muster.at\nMuster Handels GmbH\n"
    reading = raw
    content = _content(raw, reading)
    package = build_document_text_package(_artifact(content))
    graph = build_document_text_anchor_graph(package)
    entities = [
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=0),
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=1),
    ]
    bound, binding_summary = bind_pii_entities_to_anchors(entities, graph, document_id=_DOC)

    secrets = ("Muster Handels GmbH", "office@muster.at")
    assert content.reading_text_geometry_projection_map is not None
    projection_dump = json.dumps(content.reading_text_geometry_projection_map.model_dump())
    graph_dump = json.dumps(graph.model_dump())
    summary_dump = json.dumps(binding_summary.model_dump())
    for secret in secrets:
        assert secret not in projection_dump
        assert secret not in graph_dump
        assert secret not in summary_dump
    for entity in bound:
        dump = entity.model_dump()
        dump.pop("value")
        entity_dump = json.dumps(dump, default=str)
        for secret in secrets:
            assert secret not in entity_dump
