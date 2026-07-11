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


# --- Phase 2: builder-emitted lineage extended beyond the plain-paragraph/body path -------------


def test_text_and_row_lineage_come_from_the_same_construction_call() -> None:
    """The builder emits canonical text and its lineage together, from one call -- not a separate
    matcher run afterward over the finished string."""
    rows = [_row(0.10, (0.07, "Wien")), _row(0.14, (0.07, "Graz"))]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Wien\n\nGraz"
    assert len(result.row_lineage) == 2
    for segment in result.row_lineage:
        assert result.text[segment.canonical_start : segment.canonical_end] == raw[
            segment.page_start : segment.page_end
        ]


def test_duplicate_rows_at_different_positions_retain_distinct_row_lineage() -> None:
    """Two rows with identical text are never married by string equality: each keeps its own
    distinct raw range, exactly the case a value/token-search fallback cannot resolve without
    guessing (it would decline both as ambiguous instead)."""
    rows = [
        _row(0.10, (0.07, "Sicherheitsdienst Wien KG")),
        _row(0.14, (0.07, "Sicherheitsdienst Wien KG")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert len(result.row_lineage) == 2
    first, second = sorted(result.row_lineage, key=lambda segment: segment.page_start)
    assert first.page_start < second.page_start
    assert first.canonical_start < second.canonical_start
    # Both resolve to the same text but distinct, non-overlapping raw AND canonical identity.
    assert raw[first.page_start : first.page_end] == raw[second.page_start : second.page_end]
    assert first.page_end <= second.page_start
    assert first.canonical_end <= second.canonical_start


def test_party_columns_reorder_while_preserving_source_identity() -> None:
    """Party-column grouping reorders rows into left/right sequences; a single-cell row wholly on
    one side keeps its own known range even though its position in the rendered text moves --
    proving reordering preserves source identity rather than losing it."""
    rows = [
        _row(0.100, (0.07, "AUFTRAGNEHMER"), (0.55, "AUFTRAGGEBER")),
        _row(0.115, (0.07, "Sanierungsbau Perchtoldsdorf GmbH")),
        _row(0.130, (0.55, "Franz Hubermayr")),
        _row(0.145, (0.07, "Lindenstrasse 42")),
        _row(0.160, (0.55, "Rosengasse 7")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "two_column_grouping" in result.flags
    # Canonical order groups by column (left block, then right block) -- diverging from raw
    # top-to-bottom order, which interleaves the two parties' rows.
    assert result.text == (
        "AUFTRAGNEHMER\n"
        "Sanierungsbau Perchtoldsdorf GmbH\n"
        "Lindenstrasse 42\n\n"
        "AUFTRAGGEBER\n"
        "Franz Hubermayr\n"
        "Rosengasse 7"
    )
    by_raw = {raw[segment.page_start : segment.page_end]: segment for segment in result.row_lineage}
    # The shared two-party heading row's cells split across both sides and correctly decline.
    assert "AUFTRAGNEHMER" not in by_raw
    assert "AUFTRAGGEBER" not in by_raw
    assert set(by_raw) == {
        "Sanierungsbau Perchtoldsdorf GmbH",
        "Lindenstrasse 42",
        "Franz Hubermayr",
        "Rosengasse 7",
    }
    for text, segment in by_raw.items():
        assert result.text[segment.canonical_start : segment.canonical_end] == text
        assert segment.status == "exact"
    # "Lindenstrasse 42" is raw-later than "Franz Hubermayr" but canonical-earlier -- the reorder
    # is real, and each line's own identity followed it rather than being guessed by position.
    assert by_raw["Lindenstrasse 42"].page_start > by_raw["Franz Hubermayr"].page_start
    assert by_raw["Lindenstrasse 42"].canonical_start < by_raw["Franz Hubermayr"].canonical_start


def test_metadata_row_gets_lineage_and_synthetic_heading_is_inserted() -> None:
    """An untouched single metadata row keeps its own range; the synthetic "ANGEBOT" heading this
    function inserts is recognized as an explicit "inserted" segment with no source range, never a
    silent gap and never guessed content."""
    rows = [_row(0.10, (0.07, "Bauvorhaben: Generalsanierung Einfamilienhaus"))]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)
    assert result is not None
    assert result.text == "ANGEBOT\nBauvorhaben: Generalsanierung Einfamilienhaus"
    assert len(result.row_lineage) == 1
    metadata_segment = result.row_lineage[0]
    assert metadata_segment.status == "exact"
    assert raw[metadata_segment.page_start : metadata_segment.page_end] == (
        "Bauvorhaben: Generalsanierung Einfamilienhaus"
    )

    lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert lineage_map is not None
    statuses = {segment.mapping_status for segment in lineage_map.segments}
    assert statuses == {"exact", "inserted"}
    inserted = next(s for s in lineage_map.segments if s.mapping_status == "inserted")
    assert inserted.source_range is None
    assert inserted.segment_role == "heading"
    assert result.text[inserted.canonical_start : inserted.canonical_end] == "ANGEBOT"


def test_metadata_fused_row_split_declines_explicitly() -> None:
    """A single row fusing two "Label: value" fields splits into two output lines; neither can be
    attributed to a specific sub-row raw boundary without guessing, so both explicitly decline."""
    rows = [_row(0.10, (0.07, "Angebot Nr.: KV-2026-0417 Datum: 01.07.2026"))]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "ANGEBOT\nAngebot Nr.: KV-2026-0417\nDatum: 01.07.2026"
    assert result.row_lineage == ()


def test_in_row_label_value_split_declines_explicitly() -> None:
    """A single row fusing multiple label/value cell pairs splits into several output lines
    (``_paired_cell_lines``); this in-row split explicitly declines lineage for all of them
    rather than guess which characters belong to which resulting line."""
    rows = [
        _row(
            0.10,
            (0.07, "Name:"),
            (0.20, "Max Mustermann"),
            (0.55, "Ort:"),
            (0.65, "Wien"),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "label_value_pairing" in result.flags
    assert result.text == "Name: Max Mustermann\nOrt: Wien"
    assert result.row_lineage == ()


def test_generic_table_without_header_keywords_gets_row_lineage() -> None:
    """OCR/Text L13's geometric table detector (no header-keyword requirement) also gets
    row-granularity lineage now: every rendered "col | col" row keeps its own row's range, reported
    "normalized" since the rendered text (with " | " separators) changed length."""
    rows = [
        _row(0.10, (0.07, "A1"), (0.30, "B1"), (0.62, "12,50"), (0.84, "25,00")),
        _row(0.14, (0.07, "A2"), (0.30, "B2"), (0.62, "13,50"), (0.84, "26,00")),
        _row(0.18, (0.07, "A3"), (0.30, "B3"), (0.62, "14,50"), (0.84, "27,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "generic_table_reconstruction" in result.flags
    assert len(result.row_lineage) == 3
    for segment, row in zip(
        sorted(result.row_lineage, key=lambda item: item.page_start), rows, strict=True
    ):
        assert segment.status == "normalized"
        assert (segment.page_start, segment.page_end) == row.source_range
        rendered = result.text[segment.canonical_start : segment.canonical_end]
        assert rendered == " | ".join(cell.text for cell in row.cells)


def test_keyword_header_table_rows_get_lineage_alongside_prefix_and_post_table_total() -> None:
    """OCR/Text Phase 2: a keyword-header table's own rows now carry row-granularity lineage,
    honestly distinguishing an untouched line ("exact"), a reformatted "col | col" line whose
    length changed ("normalized"), and a multiline continuation that unions two rows' ranges
    ("merged") -- alongside the prefix and post-table total lines that already had lineage. The
    synthetic "SUMMEN" heading still has none: it was never in the raw text.
    """
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
    assert len(result.row_lineage) == 5

    by_raw = {
        raw[segment.page_start : segment.page_end]: segment for segment in result.row_lineage
    }
    assert set(by_raw) == {
        "KOSTEN",
        "Pos. Beschreibung Betrag EUR",
        "1 Arbeitsleistung 10,00\nmit kurzer Fortsetzung",
        "2 Material 20,00",
        "Gesamtbetrag: 30,00",
    }

    # An untouched single line stays "exact": the canonical text is byte-identical to its raw span.
    kosten_segment = by_raw["KOSTEN"]
    assert kosten_segment.status == "exact"
    assert result.text[kosten_segment.canonical_start : kosten_segment.canonical_end] == "KOSTEN"
    assert by_raw["Gesamtbetrag: 30,00"].status == "exact"

    # A row reformatted into "col | col | col" table syntax changed length, so it is honestly
    # "normalized" rather than falsely claimed "exact".
    header_segment = by_raw["Pos. Beschreibung Betrag EUR"]
    assert header_segment.status == "normalized"
    assert (
        result.text[header_segment.canonical_start : header_segment.canonical_end]
        == "Pos. | Beschreibung | Betrag EUR"
    )
    data_row_segment = by_raw["2 Material 20,00"]
    assert data_row_segment.status == "normalized"
    assert (
        result.text[data_row_segment.canonical_start : data_row_segment.canonical_end]
        == "2 | Material | 20,00"
    )

    # A multiline continuation unions two distinct rows' ranges, so it is honestly "merged" -- the
    # raw span covers both source lines even though the rendered line reorders their content.
    continuation_segment = by_raw["1 Arbeitsleistung 10,00\nmit kurzer Fortsetzung"]
    assert continuation_segment.status == "merged"
    assert (
        result.text[continuation_segment.canonical_start : continuation_segment.canonical_end]
        == "1 | Arbeitsleistung mit kurzer Fortsetzung | 10,00"
    )

    # The synthetic "SUMMEN" heading this builder inserts was never in the raw text at all.
    assert "SUMMEN" not in by_raw
    assert "SUMMEN" not in [
        result.text[segment.canonical_start : segment.canonical_end]
        for segment in result.row_lineage
    ]


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
