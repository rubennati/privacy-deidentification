"""Unit tests for OCR/Text L14 quality evidence and lineage coverage.

All data here is synthetic. These tests exercise the deterministic ``build_quality_evidence``
builder directly with in-memory pages, reading text, maps, and geometry — no private corpus, no OCR
runtime, and no raw document text in any assertion.
"""

from __future__ import annotations

import pytest

from app.schemas import (
    QualityEvidence,
    ReadingTextMapSegment,
    StructuredContent,
    StructuredContentSummary,
    StructuredField,
    StructuredPageContent,
    StructuredSpan,
    TextGeometry,
    TextGeometryPage,
    TextLineGeometry,
    TextPageResult,
)
from app.services.ocr_quality import build_quality_evidence
from app.services.reading_text import ReadingTextResult


def _page(
    text: str,
    *,
    page_number: int = 1,
    source: str = "pdf_text_layer",
    ocr_used: bool = False,
    ocr_confidence: float | None = None,
) -> TextPageResult:
    return TextPageResult(
        page_number=page_number,
        source=source,  # type: ignore[arg-type]
        has_text_layer=source == "pdf_text_layer",
        ocr_used=ocr_used,
        text=text,
        text_char_count=len(text),
        ocr_confidence=ocr_confidence,
    )


def _reading(text: str, *flags: str, status: str = "heuristic") -> ReadingTextResult:
    return ReadingTextResult(text=text, status=status, flags=tuple(flags))  # type: ignore[arg-type]


def _segment(
    reading_start: int,
    reading_end: int,
    raw_start: int,
    raw_end: int,
    status: str = "exact",
) -> ReadingTextMapSegment:
    return ReadingTextMapSegment(
        reading_start=reading_start,
        reading_end=reading_end,
        raw_start=raw_start,
        raw_end=raw_end,
        page_number=1,
        mapping_status=status,  # type: ignore[arg-type]
    )


def _line(
    index: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    source: str = "pdf_text_layer",
    confidence: float | None = None,
) -> TextLineGeometry:
    return TextLineGeometry(
        line_index=index,
        canonical_start=index - 1,
        canonical_end=index,
        page_start=index - 1,
        page_end=index,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        source=source,  # type: ignore[arg-type]
        confidence=confidence,
    )


def _geometry(
    lines: list[TextLineGeometry],
    *,
    width: float = 600.0,
    height: float = 800.0,
    status: str = "complete",
    source: str = "pdf_text_layer",
    coverage: float = 1.0,
    flags: list[str] | None = None,
) -> TextGeometry:
    page = TextGeometryPage(
        page_number=1,
        page_width=width,
        page_height=height,
        coordinate_unit="pdf_points",
        source=source,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        lines=lines,
    )
    return TextGeometry(pages=[page], coverage=coverage, flags=flags or [])


def _structured_content() -> StructuredContent:
    field = StructuredField(
        field_id="field-p1-1",
        page_number=1,
        label="Name",
        label_span=StructuredSpan(canonical_start=0, canonical_end=4, page_start=0, page_end=4),
        value_span=StructuredSpan(canonical_start=6, canonical_end=10, page_start=6, page_end=10),
        confidence=0.9,
        source="canonical_text",
    )
    page = StructuredPageContent(
        page_number=1, fields=[field], source="canonical_text", confidence=0.9
    )
    return StructuredContent(
        pages=[page],
        summary=StructuredContentSummary(
            page_count=1, table_count=0, field_count=1, section_count=0
        ),
        flags=["span_backed", "pii_input_unchanged"],
    )


def _items_by_type(evidence: QualityEvidence) -> dict[str, list]:
    result: dict[str, list] = {}
    for item in evidence.items:
        result.setdefault(item.type, []).append(item)
    return result


# --- Quality evidence ------------------------------------------------------------------------


def test_quality_evidence_created_for_normal_artifact() -> None:
    text = "Digital text"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[_segment(0, len(text), 0, len(text))],
        text_geometry=_geometry([_line(1, 40, 400, 560, 420)]),
        structured_content=None,
    )

    by_type = _items_by_type(evidence)
    assert by_type["source_text"][0].status == "confident"
    assert by_type["pdf_text_layer"][0].status == "confident"
    assert by_type["reading_order"][0].status == "confident"
    assert evidence.summary.overall_status == "confident"
    # Summary counts are consistent with the items (validated by the schema too).
    assert sum(evidence.summary.counts_by_status.values()) == len(evidence.items)
    assert sum(evidence.summary.counts_by_type.values()) == len(evidence.items)


def test_empty_raw_text_produces_unavailable_evidence() -> None:
    evidence = build_quality_evidence(
        source="paddleocr",
        text="",
        pages=[_page("", source="paddleocr", ocr_used=True)],
        reading=None,
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )

    by_type = _items_by_type(evidence)
    assert by_type["source_text"][0].status == "unavailable"
    assert by_type["source_text"][0].reason_code == "raw_text_missing"
    assert by_type["reading_order"][0].status == "unavailable"
    assert by_type["skipped_reconstruction"][0].status == "unavailable"
    assert evidence.summary.overall_status == "unavailable"
    assert evidence.summary.overall_score is None
    assert "raw_text_missing" in evidence.summary.blockers


def test_reading_text_map_coverage_is_computed() -> None:
    reading = "AAAA BBBB"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=reading,
        pages=[_page(reading)],
        reading=_reading(reading, "geometry_ordering"),
        reading_text_map=[_segment(0, 4, 0, 4)],
        text_geometry=None,
        structured_content=None,
    )

    lineage = evidence.summary.lineage_summary
    assert lineage.reading_text_length == len(reading)
    assert lineage.mapped_reading_text_chars == 4
    assert lineage.unmapped_reading_text_chars == len(reading) - 4
    assert lineage.mapping_coverage_ratio == round(4 / len(reading), 6)
    map_item = _items_by_type(evidence)["reading_text_map"][0]
    assert map_item.details["mapped_chars"] == 4
    assert map_item.details["coverage_percent"] == round(4 / len(reading) * 100)


def test_page_zone_classification_with_synthetic_geometry() -> None:
    geometry = _geometry(
        [
            _line(1, 40, 10, 560, 30),  # top band -> header
            _line(2, 40, 400, 560, 420),  # middle -> body
            _line(3, 40, 780, 560, 796),  # bottom band -> footer
            _line(4, 420, 400, 560, 420),  # right side -> right_margin
            _line(5, 10, 400, 60, 420),  # narrow far-left -> left_margin
        ]
    )
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="body",
        pages=[_page("body")],
        reading=_reading("body", "geometry_ordering"),
        reading_text_map=[],
        text_geometry=geometry,
        structured_content=None,
    )

    zone = _items_by_type(evidence)["page_zone"][0]
    assert zone.details == {
        "header_lines": 1,
        "footer_lines": 1,
        "left_margin_lines": 1,
        "right_margin_lines": 1,
        "body_lines": 1,
    }
    assert zone.page_zone == "body"  # tie broken toward body, the neutral default
    assert zone.bbox is not None and zone.bbox.coordinate_unit == "normalized"


def test_header_footer_body_zones_are_conservative() -> None:
    # A single mid-page line must classify as body, never header/footer, and dominate the page.
    geometry = _geometry([_line(1, 40, 390, 560, 410)])
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="body",
        pages=[_page("body")],
        reading=_reading("body", "geometry_ordering"),
        reading_text_map=[],
        text_geometry=geometry,
        structured_content=None,
    )

    zone = _items_by_type(evidence)["page_zone"][0]
    assert zone.page_zone == "body"
    assert zone.details["header_lines"] == 0
    assert zone.details["footer_lines"] == 0
    assert zone.details["body_lines"] == 1


def test_table_reconstruction_flag_produces_table_evidence() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="table",
        pages=[_page("table")],
        reading=_reading("table", "geometry_ordering", "table_row_reconstruction"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )

    table = _items_by_type(evidence)["table_reconstruction"][0]
    assert table.status == "confident"
    assert table.reason_code == "table_structure_reconstructed"
    assert "table_row_reconstruction" in table.flags


def test_form_reconstruction_flag_produces_form_evidence() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="form",
        pages=[_page("form")],
        reading=_reading("form", "geometry_ordering", "label_value_pairing"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )

    form = _items_by_type(evidence)["form_reconstruction"][0]
    assert form.status == "confident"
    assert "label_value_pairing" in form.flags


def test_multi_column_flag_produces_reconstruction_evidence() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="cols",
        pages=[_page("cols")],
        reading=_reading("cols", "geometry_ordering", "multi_column_reconstruction"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )

    item = _items_by_type(evidence)["multi_column_reconstruction"][0]
    assert item.status == "confident"
    assert evidence.summary.reconstruction_summary["multi_column_reconstruction"] == 1


def test_fallback_path_produces_fallback_evidence() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="fallback",
        pages=[_page("fallback")],
        reading=_reading("fallback", "raw_order_fallback", status="fallback"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )

    by_type = _items_by_type(evidence)
    assert by_type["fallback"][0].status == "fallback"
    assert by_type["reading_order"][0].status == "fallback"
    assert by_type["skipped_reconstruction"][0].reason_code == (
        "reconstruction_skipped_low_confidence"
    )
    assert evidence.summary.overall_status == "fallback"
    assert evidence.summary.fallback_summary == {"raw_order_fallback": 1}


def test_structured_content_is_summarized() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="Name: value",
        pages=[_page("Name: value")],
        reading=_reading("Name: value", "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=_structured_content(),
    )

    item = _items_by_type(evidence)["structured_content"][0]
    assert item.status == "confident"
    assert item.details == {
        "page_count": 1,
        "table_count": 0,
        "field_count": 1,
        "section_count": 0,
    }
    assert evidence.summary.lineage_summary.structured_content_reference_count == 1


def test_structured_content_absent_is_marked_unavailable() -> None:
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="x",
        pages=[_page("x")],
        reading=_reading("x", "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    item = _items_by_type(evidence)["structured_content"][0]
    assert item.status == "unavailable"
    assert evidence.summary.lineage_summary.structured_content_reference_count is None


def test_confidence_values_are_bounded() -> None:
    evidence = build_quality_evidence(
        source="pdf_mixed",
        text="Digital text",
        pages=[
            _page("Digital text"),
            _page("Scan", page_number=2, source="paddleocr", ocr_used=True, ocr_confidence=0.9),
        ],
        reading=_reading("Digital text\n\nScan", "geometry_ordering", "partial_geometry"),
        reading_text_map=[_segment(0, 12, 0, 12)],
        text_geometry=_geometry(
            [_line(1, 40, 400, 560, 420, source="paddleocr", confidence=0.9)],
            status="partial",
            coverage=0.5,
        ),
        structured_content=None,
    )

    for item in evidence.items:
        assert item.confidence is None or 0.0 <= item.confidence <= 1.0
    score = evidence.summary.overall_score
    assert score is None or 0.0 <= score <= 1.0


def test_reason_codes_are_stable() -> None:
    text = "Digital text"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[_segment(0, len(text), 0, len(text))],
        text_geometry=_geometry([_line(1, 40, 400, 560, 420)]),
        structured_content=None,
    )

    reasons = {item.reason_code for item in evidence.items}
    assert {
        "raw_text_available",
        "pdf_text_layer_used",
        "reading_order_from_geometry",
        "page_geometry_complete",
        "reading_text_map_high_coverage",
        "source_geometry_complete",
        "projection_substrate_available",
    } <= reasons


def test_quality_builder_is_deterministic() -> None:
    kwargs = dict(
        source="pdf_text_layer",
        text="Digital text",
        pages=[_page("Digital text")],
        reading=_reading("Digital text", "geometry_ordering"),
        reading_text_map=[_segment(0, 12, 0, 12)],
        text_geometry=_geometry([_line(1, 40, 400, 560, 420)]),
        structured_content=_structured_content(),
    )
    first = build_quality_evidence(**kwargs)  # type: ignore[arg-type]
    second = build_quality_evidence(**kwargs)  # type: ignore[arg-type]
    assert first.model_dump() == second.model_dump()


def test_builder_does_not_mutate_inputs() -> None:
    reading = _reading("Digital text", "geometry_ordering")
    pages = [_page("Digital text")]
    build_quality_evidence(
        source="pdf_text_layer",
        text="Digital text",
        pages=pages,
        reading=reading,
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    assert reading.flags == ("geometry_ordering",)
    assert len(pages) == 1


def test_no_raw_text_in_quality_metadata() -> None:
    # Synthetic sensitive-looking content must not appear anywhere in the evidence metadata.
    sensitive = "Franz Hubermayr AT61 3200 0000 1234 5678"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=sensitive,
        pages=[_page(sensitive)],
        reading=_reading(sensitive, "geometry_ordering", "label_value_pairing"),
        reading_text_map=[_segment(0, 5, 0, 5)],
        text_geometry=_geometry([_line(1, 40, 400, 560, 420)]),
        structured_content=_structured_content(),
    )
    dumped = evidence.model_dump_json()
    for token in ("Franz", "Hubermayr", "AT61", "3200", "5678"):
        assert token not in dumped


def test_docx_marks_geometry_and_ocr_not_applicable() -> None:
    evidence = build_quality_evidence(
        source="docx_text",
        text="Some docx text",
        pages=[],
        reading=_reading("Some docx text", "raw_order_fallback", status="fallback"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    by_type = _items_by_type(evidence)
    assert by_type["pdf_text_layer"][0].status == "not_applicable"
    assert by_type["ocr_engine"][0].status == "not_applicable"
    assert by_type["page_geometry"][0].status == "not_applicable"
    assert by_type["positioned_rows"][0].status == "not_applicable"


# --- Lineage coverage ------------------------------------------------------------------------


def test_exact_mapped_reading_ranges() -> None:
    text = "Digital text"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[_segment(0, len(text), 0, len(text))],
        text_geometry=None,
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    assert lineage.exact_span_count == 1
    assert lineage.partial_span_count == 0
    assert lineage.unmapped_span_count == 0
    assert lineage.mapping_coverage_ratio == 1.0


def test_partially_mapped_ranges() -> None:
    reading = "AAAA BBBB CCCC"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=reading,
        pages=[_page(reading)],
        reading=_reading(reading, "geometry_ordering"),
        # Map only the first token exactly and the middle token as normalized.
        reading_text_map=[_segment(0, 4, 0, 4), _segment(5, 9, 5, 9, status="normalized")],
        text_geometry=None,
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    assert lineage.exact_span_count == 1
    assert lineage.partial_span_count == 1
    # "CCCC" at the end is a single uncovered non-whitespace run.
    assert lineage.unmapped_span_count == 1


def test_unmapped_derived_ranges_are_not_source_mapped() -> None:
    # A synthetic/derived heading the builder never mapped must count as unmapped, not exact.
    reading = "ANGEBOT\nDigital text"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text="Digital text",
        pages=[_page("Digital text")],
        reading=_reading(reading, "geometry_ordering", "document_sections"),
        reading_text_map=[_segment(8, 20, 0, 12)],
        text_geometry=None,
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    assert lineage.mapped_reading_text_chars == 12
    assert lineage.unmapped_reading_text_chars == len(reading) - 12
    # The generated "ANGEBOT" heading is one uncovered run and is never treated as source-mapped.
    assert lineage.unmapped_span_count == 1
    assert lineage.exact_span_count == 1


def test_source_geometry_coverage_is_surfaced() -> None:
    evidence = build_quality_evidence(
        source="pdf_mixed",
        text="Digital text",
        pages=[_page("Digital text")],
        reading=_reading("Digital text", "geometry_ordering", "partial_geometry"),
        reading_text_map=[_segment(0, 12, 0, 12)],
        text_geometry=_geometry(
            [_line(1, 40, 400, 560, 420)], status="partial", coverage=0.5
        ),
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    assert lineage.source_geometry_coverage_ratio == 0.5
    coverage_item = _items_by_type(evidence)["lineage_coverage"][0]
    assert coverage_item.status == "partial"
    assert coverage_item.details["source_geometry_coverage_percent"] == 50


def test_no_geometry_reports_no_source_coverage() -> None:
    evidence = build_quality_evidence(
        source="docx_text",
        text="Some docx text",
        pages=[],
        reading=_reading("Some docx text", "raw_order_fallback", status="fallback"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    assert lineage.source_geometry_coverage_ratio is None
    assert _items_by_type(evidence)["lineage_coverage"][0].status == "unavailable"


@pytest.mark.parametrize("status", ["exact", "normalized", "partial"])
def test_mapping_status_classification(status: str) -> None:
    reading = "Digital text"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=reading,
        pages=[_page(reading)],
        reading=_reading(reading, "geometry_ordering"),
        reading_text_map=[_segment(0, len(reading), 0, len(reading), status=status)],
        text_geometry=None,
        structured_content=None,
    )
    lineage = evidence.summary.lineage_summary
    if status == "exact":
        assert lineage.exact_span_count == 1 and lineage.partial_span_count == 0
    else:
        assert lineage.exact_span_count == 0 and lineage.partial_span_count == 1
