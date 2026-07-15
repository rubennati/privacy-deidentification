"""Construction-time canonical-text lineage v2 (anchor-first text package v2).

All data is synthetic. This suite proves the guarantees the branch exists for:

- the real canonical builder emits lineage while rendering (including through a real pypdf PDF);
- source identity is captured from the extraction process itself, so repeated values and repeated
  suffixes keep distinct identities without any uniqueness requirement;
- reordering (party columns), in-row splits (label/value pairs, fused metadata cells), table
  reconstruction, multi-column redistribution, wrap merges, and inserted headings are represented
  honestly (byte-verified ``exact``/``normalized``/``merged``/``split``/``inserted``);
- envelope claims that would swallow interleaved content are dropped symmetrically by the
  document-level overlap sweep instead of surviving as lies;
- minimal inputs (no geometry, no positioned rows) still get construction lineage through the
  raw-order fallback, while legacy artifacts keep the explicit post-hoc fallbacks;
- construction-time and fallback lineage can never be confused downstream;
- raw text -> package -> anchor graph -> PII binding -> entity contract works end to end on a span
  only cell-level construction lineage can resolve;
- lineage metadata carries offsets/statuses/reason codes only — never copied document text.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from tests.artifact_helpers import save_pii_artifact, save_text_artifact

from app.config import Settings
from app.schemas import (
    PiiArtifact,
    PiiContent,
    PiiEntity,
    PiiValidationSummary,
    ReadingTextMapSegment,
    ReadingTextRowLineageMap,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.reading_text import (
    ReadingCell,
    ReadingRow,
    build_reading_text,
    collect_pdf_reading_rows,
)
from app.services.reading_text_projection import project_pii_entities_to_reading_text
from app.services.reading_text_row_lineage import build_reading_text_row_lineage_map

_DOC = "a" * 32


# --- shared synthetic fixtures ---------------------------------------------------------------


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
    spans: list[tuple[int, int]] = []
    cursor = 0
    for line in raw.split("\n"):
        spans.append((cursor, cursor + len(line)))
        cursor += len(line) + 1
    return spans


def _with_cell_ranges(rows: list[ReadingRow], raw: str) -> list[ReadingRow]:
    """Attach per-cell and per-row ranges, assuming ``raw`` is rows' single-space-joined lines."""
    result: list[ReadingRow] = []
    for row, (line_start, line_end) in zip(rows, _line_spans(raw), strict=True):
        cursor = line_start
        ranged_cells: list[ReadingCell] = []
        for index, cell in enumerate(row.cells):
            if index:
                cursor += 1
            ranged_cells.append(replace(cell, source_range=(cursor, cursor + len(cell.text))))
            cursor += len(cell.text)
        assert cursor == line_end, "fixture raw text must be the single-space join of the cells"
        result.append(
            replace(row, cells=tuple(ranged_cells), source_range=(line_start, line_end))
        )
    return result


def _segments_by_raw(result_text: str, raw: str, row_lineage) -> dict[str, object]:
    return {raw[segment.page_start : segment.page_end]: segment for segment in row_lineage}


def _pdf_runs_bytes(runs: list[tuple[float, float, str]]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        "".join(f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET\n" for x, y, text in runs).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --- 1. The real builder emits lineage, from a real PDF, without uniqueness ----------------------


def test_real_pdf_repeated_values_keep_distinct_construction_identity() -> None:
    """The same value twice on one page — the exact case every post-hoc text match must decline —
    gets two distinct raw identities from the extraction process itself, and both survive into the
    builder's emitted lineage with distinct canonical ranges."""
    runs = [
        (10, 300, "Sicherheitsdienst Muster GmbH"),
        (10, 280, "Rechnungsanschrift folgt hier"),
        (10, 260, "Sicherheitsdienst Muster GmbH"),
    ]
    reader = PdfReader(BytesIO(_pdf_runs_bytes(runs)))
    pdf_page = reader.pages[0]
    raw = pdf_page.extract_text() or ""
    assert raw.count("Sicherheitsdienst Muster GmbH") == 2

    rows = collect_pdf_reading_rows(pdf_page, 1, raw)

    assert [row.source_range for row in rows] == _line_spans(raw)
    # Cell-level identity was captured too, not just row-level.
    assert all(
        cell.source_range is not None for row in rows for cell in row.cells
    )

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)
    assert result is not None
    duplicate_segments = sorted(
        (
            segment
            for segment in result.row_lineage
            if raw[segment.page_start : segment.page_end] == "Sicherheitsdienst Muster GmbH"
        ),
        key=lambda segment: segment.page_start,
    )
    assert len(duplicate_segments) == 2
    first, second = duplicate_segments
    assert first.page_end <= second.page_start
    assert first.canonical_end <= second.canonical_start
    for segment in duplicate_segments:
        assert segment.status == "exact"
        assert (
            result.text[segment.canonical_start : segment.canonical_end]
            == "Sicherheitsdienst Muster GmbH"
        )


def test_extraction_offset_mismatch_falls_back_to_unique_matching() -> None:
    """When the stored raw text is not this extraction's byte-exact concatenation, every extraction
    offset is discarded; the explicit unique-matching fallback then resolves only unambiguous rows
    and declines duplicates rather than guessing by position."""
    runs = [
        (10, 300, "Alpha Beispielzeile"),
        (10, 280, "Beta einmalige Zeile"),
        (10, 260, "Alpha Beispielzeile"),
    ]
    reader = PdfReader(BytesIO(_pdf_runs_bytes(runs)))
    pdf_page = reader.pages[0]
    real_raw = pdf_page.extract_text() or ""
    stored_raw = real_raw + "\nNachtraeglich andere Zeile"

    rows = collect_pdf_reading_rows(pdf_page, 1, stored_raw)

    by_text = {row.cells[0].text: row for row in rows if len(row.cells) == 1}
    unique_row = by_text["Beta einmalige Zeile"]
    assert unique_row.source_range is not None
    assert (
        stored_raw[unique_row.source_range[0] : unique_row.source_range[1]]
        == "Beta einmalige Zeile"
    )
    duplicate_rows = [row for row in rows if row.cells[0].text == "Alpha Beispielzeile"]
    assert len(duplicate_rows) == 2
    assert all(row.source_range is None for row in duplicate_rows)
    # Fallback matching is row-granularity only: it never invents cell identity.
    assert all(cell.source_range is None for row in rows for cell in row.cells)


def test_repeated_suffix_tokens_stay_distinguishable_through_anchors() -> None:
    """Two different companies sharing the repeated ``GmbH`` suffix each keep their own canonical
    range: construction identity resolves the repeated token per line, where a global text search
    could not tell the two ``GmbH`` occurrences apart."""
    line_one = "Muster Handels GmbH"
    line_two = "Beispiel Bau GmbH"
    raw = f"{line_one}\n{line_two}"
    rows = _with_cell_ranges([_row(0.10, (0.07, line_one)), _row(0.14, (0.07, line_two))], raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)
    assert result is not None
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    graph = build_document_text_anchor_graph(
        build_document_text_package(
            _text_artifact(_text_content(raw, result.text, row_lineage_map=row_lineage_map))
        )
    )

    gmbh_anchors = [
        anchor
        for anchor in graph.anchors
        if any(
            source_range.source_name == "technical_raw_text"
            and raw[source_range.start : source_range.end] == "GmbH"
            for source_range in anchor.source_ranges
        )
    ]
    assert len(gmbh_anchors) == 2
    canonical_ranges = []
    for anchor in gmbh_anchors:
        assert "canonical_row_construction" in anchor.flags
        canonical = next(
            source_range
            for source_range in anchor.source_ranges
            if source_range.source_name == "canonical_reading_text"
        )
        assert result.text[canonical.start : canonical.end] == "GmbH"
        canonical_ranges.append((canonical.start, canonical.end))
    assert canonical_ranges[0] != canonical_ranges[1]


# --- 2. In-row splits, party columns, metadata, honesty of statuses ------------------------------


def test_in_row_label_value_split_attributes_each_line_its_own_cells() -> None:
    """A row fusing several label/value cell pairs splits into lines that each keep exactly their
    own cells' identity — byte-verified ``exact`` when the rendered line reproduces its raw span."""
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
    rows = _with_cell_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Name: Max Mustermann\nOrt: Wien"
    assert len(result.row_lineage) == 2
    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert set(by_raw) == {"Name: Max Mustermann", "Ort: Wien"}
    for text, segment in by_raw.items():
        assert segment.status == "exact"
        assert result.text[segment.canonical_start : segment.canonical_end] == text


def test_in_row_split_with_changed_bytes_is_reported_split_not_exact() -> None:
    """When rendering changes a split line's bytes (double raw spacing collapsed by the join), the
    segment stays attributed but is honestly ``split`` — never a false byte-identity claim."""
    raw = "Name:  Max Mustermann Ort:  Wien"
    row = ReadingRow(
        page_number=1,
        y0=0.10,
        y1=0.112,
        cells=(
            ReadingCell(text="Name:", x0=0.07, x1=0.12, source_range=(0, 5)),
            ReadingCell(text="Max Mustermann", x0=0.20, x1=0.30, source_range=(7, 21)),
            ReadingCell(text="Ort:", x0=0.55, x1=0.60, source_range=(22, 26)),
            ReadingCell(text="Wien", x0=0.65, x1=0.70, source_range=(28, 32)),
        ),
        source_range=(0, len(raw)),
    )

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=[row])

    assert result is not None
    assert result.text == "Name: Max Mustermann\nOrt: Wien"
    assert [segment.status for segment in result.row_lineage] == ["split", "split"]
    first, second = result.row_lineage
    assert raw[first.page_start : first.page_end] == "Name:  Max Mustermann"
    assert raw[second.page_start : second.page_end] == "Ort:  Wien"

    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    assert all(
        segment.mapping_status == "split" and "in_row_split" in segment.reason_codes
        for segment in row_lineage_map.segments
    )
    assert row_lineage_map.summary.split_segment_count == 2


def test_party_heading_cells_split_across_columns_keep_cell_identity() -> None:
    """The shared two-party heading row's cells land in different columns; each rendered heading
    line now keeps exactly its own cell's identity through the reorder."""
    rows = [
        _row(0.100, (0.07, "AUFTRAGNEHMER"), (0.55, "AUFTRAGGEBER")),
        _row(0.115, (0.07, "Sanierungsbau Perchtoldsdorf GmbH")),
        _row(0.130, (0.55, "Franz Hubermayr")),
        _row(0.145, (0.07, "Lindenstrasse 42")),
        _row(0.160, (0.55, "Rosengasse 7")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_cell_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "two_column_grouping" in result.flags
    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert set(by_raw) == {
        "AUFTRAGNEHMER",
        "AUFTRAGGEBER",
        "Sanierungsbau Perchtoldsdorf GmbH",
        "Lindenstrasse 42",
        "Franz Hubermayr",
        "Rosengasse 7",
    }
    for text, segment in by_raw.items():
        assert result.text[segment.canonical_start : segment.canonical_end] == text
        assert segment.status == "exact"
    # The headings really are the split-across-sides row, resolved per cell, not per row.
    assert by_raw["AUFTRAGNEHMER"].page_end <= by_raw["AUFTRAGGEBER"].page_start


def test_metadata_two_cell_fused_row_splits_along_cell_boundaries() -> None:
    """A metadata row whose two fields are separate cells splits into two attributed lines; the
    synthetic ANGEBOT heading stays an explicit inserted segment."""
    rows = [
        _row(0.10, (0.07, "Angebot Nr.: KV-2026-0417"), (0.55, "Datum: 01.07.2026")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_cell_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "ANGEBOT\nAngebot Nr.: KV-2026-0417\nDatum: 01.07.2026"
    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert set(by_raw) == {"Angebot Nr.: KV-2026-0417", "Datum: 01.07.2026"}
    for text, segment in by_raw.items():
        assert segment.status == "exact"
        assert result.text[segment.canonical_start : segment.canonical_end] == text

    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    inserted = [
        segment for segment in row_lineage_map.segments if segment.mapping_status == "inserted"
    ]
    assert len(inserted) == 1
    assert result.text[inserted[0].canonical_start : inserted[0].canonical_end] == "ANGEBOT"
    assert inserted[0].source_range is None


def test_bullet_substitution_is_byte_verified_not_length_guessed() -> None:
    """A bullet row renders at identical length but different bytes ("• " -> "- "); byte
    verification reports it ``normalized``, never a false ``exact``."""
    line = "• Erster Punkt der Liste"
    raw = line
    rows = _with_cell_ranges([_row(0.10, (0.07, line))], raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "- Erster Punkt der Liste"
    assert len(result.text) == len(raw)
    assert len(result.row_lineage) == 1
    assert result.row_lineage[0].status == "normalized"


# --- 3. Multi-column redistribution and the overlap sweep ----------------------------------------

_COLUMN_ROWS = [
    (0.10, "1. Allgemeines", "2. Datenschutz"),
    (
        0.12,
        "Diese Bedingungen gelten fuer alle Leistungen dieses Vertrages und",
        "Personenbezogene Daten werden nur fuer die Abwicklung dieses",
    ),
    (0.138, "werden Bestandteil jeder Bestellung.", "Auftrags verarbeitet."),
    (
        0.17,
        "Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen.",
        "Weitere Hinweise werden dem Kunden in Textform bereitgestellt.",
    ),
]


def test_multi_column_interleaved_raw_keeps_cells_and_drops_swallowing_merges() -> None:
    """With row-major (interleaved) raw text, a wrapped-paragraph merge inside one column would
    claim an envelope containing the other column's raw text; the overlap sweep drops exactly
    those merges while every precisely-attributed line keeps its identity through the reorder."""
    rows = [
        _row(y, (0.07, left), (0.54, right)) for y, left, right in _COLUMN_ROWS
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    rows = _with_cell_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "multi_column_reconstruction" in result.flags
    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert set(by_raw) == {
        "1. Allgemeines",
        "2. Datenschutz",
        "Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen.",
        "Weitere Hinweise werden dem Kunden in Textform bereitgestellt.",
    }
    for text, segment in by_raw.items():
        assert segment.status == "exact"
        assert result.text[segment.canonical_start : segment.canonical_end] == text
    # The reorder is real: "2. Datenschutz" precedes the left column's closing sentence in raw,
    # but follows it in canonical reading order (left column renders first).
    left_sentence = by_raw["Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen."]
    right_heading = by_raw["2. Datenschutz"]
    assert right_heading.page_start < left_sentence.page_start
    assert right_heading.canonical_start > left_sentence.canonical_start


def test_multi_column_sequential_raw_keeps_wrap_merges() -> None:
    """With column-major raw text (each column contiguous in raw), the same wrapped-paragraph
    merges are legitimate contiguous envelopes and survive as honest ``merged`` segments."""
    left_lines = [left for _y, left, _right in _COLUMN_ROWS]
    right_lines = [right for _y, _left, right in _COLUMN_ROWS]
    raw = "\n".join([*left_lines, *right_lines])
    spans = _line_spans(raw)
    rows = []
    for index, (y, left, right) in enumerate(_COLUMN_ROWS):
        left_span = spans[index]
        right_span = spans[len(_COLUMN_ROWS) + index]
        rows.append(
            ReadingRow(
                page_number=1,
                y0=y,
                y1=y + 0.012,
                cells=(
                    ReadingCell(text=left, x0=0.07, x1=0.45, source_range=left_span),
                    ReadingCell(text=right, x0=0.54, x1=0.92, source_range=right_span),
                ),
            )
        )

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "multi_column_reconstruction" in result.flags
    merged = [segment for segment in result.row_lineage if segment.status == "merged"]
    assert len(merged) == 2
    merged_raw = {raw[segment.page_start : segment.page_end] for segment in merged}
    assert merged_raw == {
        "Diese Bedingungen gelten fuer alle Leistungen dieses Vertrages und\n"
        "werden Bestandteil jeder Bestellung.",
        "Personenbezogene Daten werden nur fuer die Abwicklung dieses\n"
        "Auftrags verarbeitet.",
    }
    # Headings and closing sentences keep their exact identity beside the merges.
    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert by_raw["1. Allgemeines"].status == "exact"
    assert by_raw["2. Datenschutz"].status == "exact"


# --- 4. Raw-order fallback lineage (minimal inputs) ----------------------------------------------


def test_raw_fallback_lines_get_construction_lineage_including_duplicates() -> None:
    """A minimal input (no geometry, no positioned rows, no layout blocks) renders through the
    raw-order fallback — where the builder walks the raw string itself, so every line, including
    repeated ones, gets construction lineage from plain cursor arithmetic."""
    raw = (
        "Kundendienst Meldung\n"
        "\n"
        "Zweite  Zeile mit Doppelabstand\n"
        "Kundendienst Meldung\n"
        "Spalte A\tSpalte B\tSpalte C"
    )
    result = build_reading_text(raw, [_page(raw)], None, [], None)

    assert result is not None
    assert result.status == "fallback"
    assert len(result.row_lineage) == 4

    duplicates = [
        segment
        for segment in result.row_lineage
        if raw[segment.page_start : segment.page_end] == "Kundendienst Meldung"
    ]
    assert len(duplicates) == 2
    assert duplicates[0].status == "exact"
    assert duplicates[1].status == "exact"
    assert duplicates[0].page_start != duplicates[1].page_start
    assert duplicates[0].canonical_start != duplicates[1].canonical_start

    by_raw = _segments_by_raw(result.text, raw, result.row_lineage)
    assert by_raw["Zweite  Zeile mit Doppelabstand"].status == "normalized"
    tab_segment = by_raw["Spalte A\tSpalte B\tSpalte C"]
    assert tab_segment.status == "normalized"
    assert (
        result.text[tab_segment.canonical_start : tab_segment.canonical_end]
        == "Spalte A | Spalte B | Spalte C"
    )

    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    package = build_document_text_package(
        _text_artifact(_text_content(raw, result.text, row_lineage_map=row_lineage_map))
    )
    assert package.lineage_summary is not None
    assert package.lineage_summary.lineage_source == "row_construction"


# --- 5. Construction vs. fallback lineage stay distinguishable -----------------------------------


def _text_content(
    raw: str,
    reading: str,
    *,
    row_lineage_map: ReadingTextRowLineageMap | None = None,
    reading_text_map: list[ReadingTextMapSegment] | None = None,
) -> TextContent:
    return TextContent(
        document_id=_DOC,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        source="pdf_text_layer",
        text=raw,
        text_char_count=len(raw),
        pages=[_page(raw)],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version="1",
        reading_text=reading,
        reading_text_status="heuristic",
        reading_text_map_version="1" if reading_text_map else None,
        reading_text_map=reading_text_map or [],
        reading_text_row_lineage_map_version=(
            row_lineage_map.map_version if row_lineage_map is not None else None
        ),
        reading_text_row_lineage_map=row_lineage_map,
    )


def _text_artifact(content: TextContent, artifact_id: str = "e" * 32) -> TextArtifact:
    return TextArtifact(
        id=artifact_id,
        document_id=content.document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        created_at="2026-07-11T09:00:00.000000Z",
        content=content,
    )


def test_construction_and_fallback_lineage_cannot_be_confused() -> None:
    """One document, both mechanisms: the line covered by builder-emitted lineage is flagged
    ``canonical_row_construction``; the line only a post-hoc unique-token match can resolve is
    flagged ``canonical_map_lineage`` — per anchor, never blended."""
    line_one = "Konstruktionszeile eins"
    line_two = "Fallbackzeile zwei"
    raw = f"{line_one}\n{line_two}"
    reading = raw
    rows = _with_cell_ranges([_row(0.10, (0.07, line_one))], line_one)
    construction_result = build_reading_text(
        line_one, [_page(line_one)], None, [], None, positioned_rows=rows
    )
    assert construction_result is not None
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=reading,
        pages=[_page(raw)],
        row_lineage=construction_result.row_lineage,
    )
    assert row_lineage_map is not None
    fallback_map = [
        ReadingTextMapSegment(
            reading_start=len(line_one) + 1,
            reading_end=len(raw),
            raw_start=len(line_one) + 1,
            raw_end=len(raw),
            page_number=1,
            mapping_status="exact",
        )
    ]
    graph = build_document_text_anchor_graph(
        build_document_text_package(
            _text_artifact(
                _text_content(
                    raw,
                    reading,
                    row_lineage_map=row_lineage_map,
                    reading_text_map=fallback_map,
                )
            )
        )
    )

    def _flags_for(value: str) -> list[str]:
        for anchor in graph.anchors:
            for source_range in anchor.source_ranges:
                if (
                    source_range.source_name == "technical_raw_text"
                    and raw[source_range.start : source_range.end] == value
                ):
                    return list(anchor.flags)
        raise AssertionError(f"no raw anchor found for {value!r}")

    construction_flags = _flags_for("Konstruktionszeile")
    fallback_flags = _flags_for("Fallbackzeile")
    assert "canonical_row_construction" in construction_flags
    assert "canonical_map_lineage" not in construction_flags
    assert "canonical_map_lineage" in fallback_flags
    assert "canonical_row_construction" not in fallback_flags
    assert graph.summary.canonical_row_construction_count >= 1
    assert graph.summary.canonical_fallback_count >= 1


def test_legacy_artifact_without_construction_lineage_uses_explicit_fallback() -> None:
    """A legacy artifact (no row-lineage map at all) keeps working through the explicitly named
    post-hoc fallback — and the package says so instead of implying construction identity."""
    raw = "Bestandszeile aus Altbestand"
    reading = raw
    legacy_map = [
        ReadingTextMapSegment(
            reading_start=0,
            reading_end=len(raw),
            raw_start=0,
            raw_end=len(raw),
            page_number=1,
            mapping_status="exact",
        )
    ]
    package = build_document_text_package(
        _text_artifact(_text_content(raw, reading, reading_text_map=legacy_map))
    )
    assert package.lineage_summary is not None
    assert package.lineage_summary.lineage_source == "fallback_text_match"
    assert package.lineage_summary.row_construction_available is False

    graph = build_document_text_anchor_graph(package)
    assert graph.summary.canonical_row_construction_count == 0
    assert graph.summary.canonical_fallback_count >= 1


def test_legacy_version_one_row_lineage_map_still_validates() -> None:
    """Artifacts persisted with map_version "1" (row granularity, no split status) must stay
    readable unchanged."""
    legacy_payload = {
        "map_version": "1",
        "lineage_source": "row_construction",
        "segments": [
            {
                "segment_id": "f" * 32,
                "canonical_start": 0,
                "canonical_end": 10,
                "source_range": {
                    "source_name": "technical_raw_text",
                    "start": 0,
                    "end": 10,
                    "source_role": "body",
                },
                "segment_role": "body",
                "mapping_status": "exact",
                "confidence": 1.0,
                "reason_codes": ["row_construction"],
                "page_number": 1,
            }
        ],
        "summary": {
            "lineage_source": "row_construction",
            "total_segments": 1,
            "canonical_char_count": 10,
            "mapped_canonical_char_count": 10,
            "coverage_ratio": 1.0,
        },
    }
    legacy_map = ReadingTextRowLineageMap.model_validate(legacy_payload)
    assert legacy_map.map_version == "1"
    assert legacy_map.summary.split_segment_count == 0


# --- 6. End to end: package -> anchors -> PII binding -> entity contract -------------------------


def test_split_line_multi_token_value_reaches_entity_contract(
    client: TestClient, settings: Settings
) -> None:
    """A multi-token PII value inside an in-row label/value split — a span only cell-level
    construction lineage can resolve (no reading_text_map, no geometry projection) — keeps its
    full canonical representation through package, anchor graph, binding, and the entity
    contract."""
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
    rows = _with_cell_ranges(rows, raw)
    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)
    assert result is not None
    reading = result.text
    assert reading == "Name: Max Mustermann\nOrt: Wien"

    document_id = _upload_document(client)
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=document_id,
        reading_text=reading,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    text_id = uuid4().hex
    save_text_artifact(
        settings,
        TextArtifact(
            id=text_id,
            document_id=document_id,
            input_artifact_id="c" * 32,
            input_audit_artifact_id="d" * 32,
            created_at="2026-07-11T09:00:00.000000Z",
            content=TextContent(
                document_id=document_id,
                input_artifact_id="c" * 32,
                input_audit_artifact_id="d" * 32,
                source="pdf_text_layer",
                text=raw,
                text_char_count=len(raw),
                pages=[_page(raw)],
                tool_versions={"test": "1"},
                flags=[],
                reading_text_version="1",
                reading_text=reading,
                reading_text_status="heuristic",
                reading_text_row_lineage_map_version=row_lineage_map.map_version,
                reading_text_row_lineage_map=row_lineage_map,
                # Deliberately no reading_text_map and no geometry projection: only construction
                # lineage can resolve this span.
            ),
        ),
    )
    value = "Max Mustermann"
    start = raw.index(value)
    entity = PiiEntity(
        id=uuid4().hex,
        entity_type="PERSON",
        text=value,
        start_offset=start,
        end_offset=start + len(value),
        score=0.9,
        recognizer="SyntheticRecognizer",
    )
    # Project reading offsets the way a real PII run does before persisting.
    entity = project_pii_entities_to_reading_text(
        [entity], [], reading_text=reading, raw_text=raw
    )[0]
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=uuid4().hex,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-11T10:00:00.000000Z",
            content=PiiContent(
                document_id=document_id,
                input_text_artifact_id=text_id,
                profile="custom",
                language="de",
                score_threshold=0.5,
                text_char_count=len(raw),
                reading_text_char_count=len(reading),
                configured_entity_types=["PERSON"],
                entities=[entity],
                entity_counts={"PERSON": 1},
                tool_versions={},
                flags=[],
                validation=PiiValidationSummary(enabled=True, kept=1, dropped=0, score_down=0),
            ),
        ),
    )

    pii = client.get(f"/api/documents/{document_id}/pii").json()
    response = client.get(
        f"/api/documents/{document_id}/pii/entity-contract",
        params={"pii_artifact_id": pii["id"], "text_artifact_id": text_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["anchor_graph_available"] is True
    matches = [item for item in body["entities"] if item["value"] == value]
    assert len(matches) == 1
    contract_entity = matches[0]
    assert contract_entity["binding_status"] == "exact"
    assert contract_entity["identity_basis"] == "anchor_exact"
    canonical_range = contract_entity["display"]["canonical_highlight_range"]
    assert canonical_range is not None
    assert reading[canonical_range["start"] : canonical_range["end"]] == value


def _upload_document(client: TestClient) -> str:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    response = client.post(
        "/api/uploads",
        files={"file": ("source.pdf", buffer.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


# --- 7. Privacy: lineage metadata never copies document text -------------------------------------


def test_lineage_metadata_contains_no_copied_document_text() -> None:
    """Every value in the lineage map, package lineage summary, and anchor graph is an offset,
    count, status, flag, or reason code — never the synthetic sensitive document content."""
    sensitive_values = (
        "Maximiliane Musterfrau-Berger",
        "AT61 1904 3002 3457 3201",
        "geheim@beispiel-firma.at",
    )
    lines = [f"Kontakt: {sensitive_values[0]}", sensitive_values[1], sensitive_values[2]]
    rows = [_row(0.10 + 0.03 * index, (0.07, line)) for index, line in enumerate(lines)]
    raw = "\n".join(lines)
    rows = _with_cell_ranges(rows, raw)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)
    assert result is not None
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=_DOC,
        reading_text=result.text,
        pages=[_page(raw)],
        row_lineage=result.row_lineage,
    )
    assert row_lineage_map is not None
    assert len(row_lineage_map.segments) >= 3

    package = build_document_text_package(
        _text_artifact(_text_content(raw, result.text, row_lineage_map=row_lineage_map))
    )
    graph = build_document_text_anchor_graph(package)

    map_json = row_lineage_map.model_dump_json()
    assert package.lineage_summary is not None
    lineage_summary_json = package.lineage_summary.model_dump_json()
    graph_json = graph.model_dump_json()
    for payload in (map_json, lineage_summary_json, graph_json):
        for value in sensitive_values:
            assert value not in payload
            for token in value.split():
                assert token not in payload
