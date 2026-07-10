"""Builder-emitted, construction-time row lineage (see reading_text.py's RowLineageSegment).

All data is synthetic. This suite proves the row-lineage step is genuinely construction-time (a
row's own raw range, attached before rendering, rides through unchanged) and honestly scoped: the
plain-paragraph/body path attaches real lineage, while every reordering/reformatting path (multi-
column reconstruction, tables, party columns) always declines rather than guessing, and repeated-
margin filtering invalidates the whole document's lineage rather than risk mis-mapped offsets.
"""

from __future__ import annotations

from dataclasses import replace

from app.schemas import (
    ReadingTextGeometryProjectionMap,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.reading_text import (
    ReadingCell,
    ReadingRow,
    RowLineageSegment,
    build_reading_text,
)
from app.services.reading_text_row_lineage import build_reading_text_row_lineage_map

_DOC = "a" * 32


def _page(raw: str, page_number: int = 1) -> TextPageResult:
    return TextPageResult(
        page_number=page_number,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw,
        text_char_count=len(raw),
    )


def _row(y: float, *cells: tuple[float, str], page_number: int = 1) -> ReadingRow:
    return ReadingRow(
        page_number=page_number,
        y0=y,
        y1=y + 0.012,
        cells=tuple(
            ReadingCell(text=text, x0=x, x1=min(0.99, x + max(0.04, len(text) * 0.006)))
            for x, text in cells
        ),
    )


def _line_spans(raw: str) -> list[tuple[int, int]]:
    """Half-open (start, end) page offsets for each ``\\n``-delimited line of a single-page raw."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for line in raw.split("\n"):
        spans.append((cursor, cursor + len(line)))
        cursor += len(line) + 1
    return spans


def _with_ranges(rows: list[ReadingRow], raw: str) -> list[ReadingRow]:
    """Attach each row's own raw span, assuming ``raw`` is exactly rows' one-cell-per-line join."""
    spans = _line_spans(raw)
    return [replace(row, source_range=span) for row, span in zip(rows, spans, strict=True)]


def test_plain_flat_lines_each_get_their_own_row_construction_segment() -> None:
    line1 = "Erste eigenstaendige Zeile im Dokument."
    line2 = "Zweite eigenstaendige Zeile."
    line3 = "Dritte kurze Zeile hier."
    raw = f"{line1}\n{line2}\n{line3}"
    rows = _with_ranges(
        [_row(0.03, (0.07, line1)), _row(0.05, (0.07, line2)), _row(0.07, (0.07, line3))], raw
    )

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    # No reordering/merging happens for these three short, unrelated lines, so canonical text is
    # byte-identical to raw text -- a useful property that also makes offset assertions exact.
    assert result.text == raw
    assert len(result.row_lineage) == 3
    for segment, (line, span) in zip(
        result.row_lineage, zip([line1, line2, line3], _line_spans(raw), strict=True), strict=True
    ):
        assert segment.page_number == 1
        assert (segment.page_start, segment.page_end) == span
        assert raw[segment.page_start : segment.page_end] == line
        assert result.text[segment.canonical_start : segment.canonical_end] == line


def test_paragraph_continuation_unions_contiguous_row_ranges() -> None:
    line1 = (
        "Dies ist ein sehr langer Satz ohne Punkt am Ende der ueber zwei Zeilen laeuft und weiter"
    )
    line2 = "geht bis er endlich hier endet."
    assert len(line1) >= 60  # otherwise this row would not be treated as long prose
    raw = f"{line1}\n{line2}"
    rows = _with_ranges([_row(0.03, (0.07, line1)), _row(0.042, (0.07, line2))], raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == f"{line1} {line2}"
    assert len(result.row_lineage) == 1
    segment = result.row_lineage[0]
    assert (segment.page_start, segment.page_end) == (0, len(raw))
    assert (segment.canonical_start, segment.canonical_end) == (0, len(result.text))


def test_paragraph_continuation_with_raw_order_reversed_declines() -> None:
    """An out-of-order raw-vs-visual merge must decline, not claim a swallowing union range.

    Rows merged in *visual* order are not necessarily in *raw* order.
    """
    line1 = (
        "Dies ist ein sehr langer Satz ohne Punkt am Ende der ueber zwei Zeilen laeuft und weiter"
    )
    line2 = "geht bis er endlich hier endet."
    raw = f"{line1}\n{line2}"
    rows = [
        replace(_row(0.03, (0.07, line1)), source_range=(len(line1) + 1, len(raw))),
        replace(_row(0.042, (0.07, line2)), source_range=(0, len(line1))),
    ]

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == f"{line1} {line2}"
    assert result.row_lineage == ()


def test_paragraph_continuation_with_one_row_missing_a_range_declines() -> None:
    line1 = (
        "Dies ist ein sehr langer Satz ohne Punkt am Ende der ueber zwei Zeilen laeuft und weiter"
    )
    line2 = "geht bis er endlich hier endet."
    raw = f"{line1}\n{line2}"
    rows = [
        replace(_row(0.03, (0.07, line1)), source_range=(0, len(line1))),
        _row(0.042, (0.07, line2)),
    ]

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.row_lineage == ()


def test_multi_column_prose_never_attaches_row_lineage_even_with_known_ranges() -> None:
    """Multi-column reconstruction redistributes cells into synthesized rows; even when every input

    row carried a known range, this step declines rather than guess a range for content that no
    longer occupies its original position.
    """
    rows = [
        _row(0.10, (0.07, "1. Allgemeines"), (0.54, "2. Datenschutz")),
        _row(
            0.12,
            (0.07, "Diese Bedingungen gelten fuer alle Leistungen dieses Vertrages und"),
            (0.54, "Personenbezogene Daten werden nur fuer die Abwicklung dieses"),
        ),
        _row(
            0.138,
            (0.07, "werden Bestandteil jeder Bestellung."),
            (0.54, "Auftrags verarbeitet."),
        ),
        _row(
            0.17,
            (0.07, "Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen."),
            (0.54, "Weitere Hinweise werden dem Kunden in Textform bereitgestellt."),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "multi_column_reconstruction" in result.flags
    assert result.row_lineage == ()


def test_generic_table_declines_but_prefix_and_post_table_total_get_lineage() -> None:
    rows = [
        _row(0.10, (0.07, "KOSTEN")),
        _row(0.14, (0.07, "Pos."), (0.16, "Beschreibung"), (0.82, "Betrag EUR")),
        _row(0.17, (0.07, "1"), (0.16, "Arbeitsleistung"), (0.84, "10,00")),
        _row(0.19, (0.16, "mit kurzer Fortsetzung")),
        _row(0.22, (0.07, "2"), (0.16, "Material"), (0.84, "20,00")),
        _row(0.26, (0.62, "Gesamtbetrag:"), (0.84, "30,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "table_row_reconstruction" in result.flags
    # The reconstructed table stays declined. Its untouched prefix and the post-table total row
    # each retain their own builder-attached range; the synthetic "SUMMEN" heading has none.
    assert len(result.row_lineage) == 2
    assert [
        raw[segment.page_start : segment.page_end] for segment in result.row_lineage
    ] == ["KOSTEN", "Gesamtbetrag: 30,00"]
    assert [
        result.text[segment.canonical_start : segment.canonical_end]
        for segment in result.row_lineage
    ] == ["KOSTEN", "Gesamtbetrag: 30,00"]


def test_repeated_page_margin_filtering_discards_all_row_lineage() -> None:
    """Margin filtering runs after row lineage offsets are computed and can shift/remove lines.

    The whole document declines lineage rather than risk stale offsets surviving that transform.
    """
    page_lines = [
        ["REPORT HEADER", "First body line here.", "Page 1/2"],
        ["REPORT HEADER", "Second body line here.", "Page 2/2"],
    ]
    pages = [_page("\n".join(lines), index) for index, lines in enumerate(page_lines, 1)]
    rows = [
        replace(
            _row(0.05 + line_index * 0.10, (0.07, line), page_number=page_number),
            source_range=_line_spans(pages[page_number - 1].text)[line_index],
        )
        for page_number, lines in enumerate(page_lines, 1)
        for line_index, line in enumerate(lines)
    ]
    raw = "\n\n".join(page.text for page in pages)

    result = build_reading_text(raw, pages, None, [], None, positioned_rows=rows)

    assert result is not None
    assert "repeated_page_margins_filtered" in result.flags
    assert result.row_lineage == ()


def test_build_reading_text_row_lineage_map_converts_page_local_to_document_offsets() -> None:
    page_one = _page("Hallo Welt", page_number=1)
    page_two = _page("Zweite Seite", page_number=2)
    reading_text = "Hallo Welt\n\nZweite Seite"
    row_lineage = (
        RowLineageSegment(
            page_number=1, canonical_start=0, canonical_end=10, page_start=0, page_end=10
        ),
        RowLineageSegment(
            page_number=2, canonical_start=12, canonical_end=24, page_start=0, page_end=12
        ),
    )

    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=reading_text,
        pages=[page_one, page_two],
        row_lineage=row_lineage,
    )

    assert row_lineage_map is not None
    assert len(row_lineage_map.segments) == 2
    first, second = row_lineage_map.segments
    assert first.mapping_status == "exact"
    assert first.confidence == 1.0
    assert first.source_range is not None
    assert (first.source_range.start, first.source_range.end) == (0, 10)
    # Page two's raw offsets are on top of page one's raw text plus the "\n\n" join.
    assert second.source_range is not None
    assert (second.source_range.start, second.source_range.end) == (12, 24)
    assert row_lineage_map.summary.total_segments == 2
    assert row_lineage_map.summary.mapped_canonical_char_count == 22
    assert row_lineage_map.summary.coverage_ratio == 22 / len(reading_text)


def test_build_reading_text_row_lineage_map_returns_none_without_any_row_lineage() -> None:
    page = _page("Hallo Welt")
    assert (
        build_reading_text_row_lineage_map(
            document_id=_DOC, reading_text="Hallo Welt", pages=[page], row_lineage=()
        )
        is None
    )
    assert (
        build_reading_text_row_lineage_map(
            document_id=_DOC, reading_text=None, pages=[page], row_lineage=()
        )
        is None
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


def test_package_and_anchor_graph_prefer_row_construction_over_geometry_projection() -> None:
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    pages = [_page(raw)]
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=reading,
        pages=pages,
        row_lineage=(
            RowLineageSegment(
                page_number=1, canonical_start=0, canonical_end=13, page_start=0, page_end=13
            ),
        ),
    )
    assert row_lineage_map is not None
    # A minimal, valid (if empty) geometry projection map, so both mechanisms are simultaneously
    # available and the preference order is actually being exercised, not just defaulted.
    geometry_projection_map = ReadingTextGeometryProjectionMap(
        segments=[],
        summary={
            "lineage_source": "geometry_projection",
            "total_segments": 0,
            "mapped_segments": 0,
            "ambiguous_segments": 0,
            "inserted_segments": 0,
            "canonical_char_count": len(reading),
            "mapped_canonical_char_count": 0,
            "coverage_ratio": 0.0,
        },
    )
    content = TextContent(
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
        reading_text_geometry_projection_map_version="1",
        reading_text_geometry_projection_map=geometry_projection_map,
        reading_text_row_lineage_map_version="1",
        reading_text_row_lineage_map=row_lineage_map,
    )

    package = build_document_text_package(_artifact(content))
    assert package.lineage_summary is not None
    assert package.lineage_summary.lineage_source == "row_construction"
    assert package.lineage_summary.row_construction_available is True

    graph = build_document_text_anchor_graph(package)
    assert graph.lineage_summary is not None
    assert graph.lineage_summary.lineage_source == "row_construction"
    assert graph.summary.canonical_row_construction_count > 0
    assert any("canonical_row_construction" in anchor.flags for anchor in graph.anchors)
    assert not any("canonical_geometry_projection" in anchor.flags for anchor in graph.anchors)
