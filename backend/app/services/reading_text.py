"""Deterministic OCR/Text L10.5 canonical reading-text construction.

``reading_text`` is the product's cleaned, block-aware text for human reading and a future
PII/placeholder workflow. It is additive: the legacy technical extraction in ``TextContent.text``
remains unchanged, offset-bearing, and the active PII input.

The builder prefers positioned rows collected from the same pypdf/PaddleOCR geometry used by the
L10 foundation, then persisted L10 line geometry, L9 layout blocks, layout text, and finally raw
page text. Bounded document heuristics group simple paired party columns, offer metadata, line-item
tables, totals, and split prose. When those signals are absent or ambiguous it preserves source
order instead of inventing structure.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from statistics import median
from typing import Any, Literal

from pypdf import PageObject

from app.schemas import LayoutBlock, TextGeometry, TextGeometryPage, TextPageResult
from app.services.layout_text import _PdfTextState, _transform_point
from app.services.text_geometry import collapse_line, segment_page_lines

_SPACE_RUN_RE = re.compile(r"[ \t]+")
_TABLE_HEADER_LEADERS = ("pos", "position", "vorlage", "gewerk", "bezeichnung")
_TABLE_HEADER_MARKERS = (
    "pos",
    "position",
    "vorlage",
    "gewerk",
    "beschreibung",
    "bezeichnung",
    "leistung",
    "menge",
    "einheit",
    "einzelpreis",
    "gesamtpreis",
    "gesamt",
    "betrag",
    "forderung",
    "ergebnis",
    "differenz",
    "diff.",
    "neuwert",
    "zeitwert",
    "abloese",
    "ablöse",
    "steuer",
    "ersteller",
)
_PARTY_HEADING_MARKERS = (
    "AUFTRAGNEHMER",
    "AUFTRAGGEBER",
    "RECHNUNGSSTELLER",
    "RECHNUNGSEMPFÄNGER",
    "KUNDE",
    "LIEFERANT",
    "RECHNUNG AN",
    "RECHNUNGSDETAILS",
)
_METADATA_PREFIXES = (
    "angebot nr.",
    "angebot nr:",
    "angebotsnummer",
    "datum:",
    "bauvorhaben:",
    "projekt:",
    "rechnungsnummer",
)
# Markers distinctive enough, on their own, to justify carving a standalone metadata section out
# of a document that has no party heading. "datum:"/"rechnungsnummer" are excluded here: they are
# common single-fact labels that also appear in flat, non-quote documents (e.g. an ID/data sheet),
# so one incidental match must not sweep the rest of the body into an undifferentiated block.
_STANDALONE_METADATA_PREFIXES = (
    "angebot nr.",
    "angebot nr:",
    "angebotsnummer",
    "bauvorhaben:",
    "projekt:",
)
_TOTAL_PREFIXES = (
    "zwischensumme",
    "nettosumme",
    "nettobetrag",
    "ust ",
    "mwst ",
    "20% mwst",
    "+ 20% mwst",
    "gesamt",
    "gesamtbetrag",
    "gesamtsumme",
    "bruttosumme",
    "schadenzeitwert",
)
_PARAGRAPH_PREFIXES = ("zahlungsbedingungen:", "zahlbar ", "dieses angebot")
_PAIRED_LABEL_RE = re.compile(
    r"(?=\s+(?:Datum|Bauvorhaben|Projekt|Angebot\s+Nr\.|Angebotsnummer|Rechnungsnummer)\s*:)",
    re.IGNORECASE,
)
_LABEL_VALUE_RE = re.compile(r"^[^:]{1,40}:\s*\S")
_STANDALONE_FIELD_LABEL_RE = re.compile(
    r"^[^\W\d_][\wÄÖÜäöüß .()/&-]{0,48}:\s*$", re.UNICODE
)
_SHORT_FIELD_VALUE_RE = re.compile(
    r"^(?:[\wÄÖÜäöüß./@+()&-]{1,40}|"
    r"\d{1,2}[.]\d{1,2}[.]\d{2,4}|"
    r"[A-Z]{1,6}[-/ ]?\d[\wÄÖÜäöüß./ -]{0,34})$",
    re.UNICODE,
)
_PAGE_NUMBER_SUFFIX_RE = re.compile(
    r"(?:^|\s+)(?:seite|page)\s*:?[ ]*\d+(?:\s*(?:von|of|/)\s*\d+)?\s*$",
    re.IGNORECASE,
)
_SEPARATOR_LINE_RE = re.compile(r"^[_\-=\u2013\u2014]{8,}$")
_INLINE_SEPARATOR_RE = re.compile(r"[_=]{8,}")
_MARGIN_LINE_COUNT = 3
# A transient text fragment that starts with closing punctuation (its own fragment because the
# source PDF/OCR run boundary happened to land there) must attach to the previous fragment without
# a leading space; any remaining text after the punctuation still gets a normal word-boundary space.
_LEADING_CLOSE_PUNCT_RE = re.compile(r"^([.,;:!?)\]}]+)(\s*)(.*)$", re.DOTALL)
_OPEN_PUNCT_TOKENS = frozenset({"(", "[", "{"})
_BULLET_PREFIX_RE = re.compile(r"^[\u2022\u25e6\u2023\u25cf]\s*")
# Same conservative line-wrap hyphen repair already used for the separate readable_text view.
_DEHYPHENATE_RE = re.compile(r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff]{2,}-$")
_WORD_START_RE = re.compile(r"^[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff]")
# The trailing negative lookahead keeps a DD.MM.YYYY date (e.g. "13.06.2025") from being misread
# as a decimal amount: without it, "13.06" alone would match and count towards the amount total.
_DECIMAL_AMOUNT_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b(?!\.\d{4})")
_HEADER_LABEL_RE = re.compile(
    r"\b("
    r"gesamtpreis|einzelpreis|beschreibung|bezeichnung|position|betrag\s+eur|"
    r"betrag|forderung|ergebnis|differenz|diff\.|neuwert|zeitwert|ablöse|abloese|"
    r"steuer|ersteller|leistung|menge|einheit|gesamt|gewerk|vorlage|pos\.?"
    r")\b",
    re.IGNORECASE,
)
_COLUMN_START_TOLERANCE = 0.08
_COLUMN_MIN_GAP = 0.22
_COLUMN_MIN_OVERLAP = 0.45
_COLUMN_MAX_COUNT = 3
_COLUMN_MIN_CELLS = 3
# OCR/Text L13: shared threshold for treating a row as "occupying" a table's columns, and the
# minimum row count (the candidate row plus two more) before a run of aligned rows is trusted as a
# table without a recognized header keyword. Both keyword-header and generic geometric tables use
# the same conservative bar.
_TABLE_MIN_OCCUPIED_COLUMNS = 3
_GENERIC_TABLE_MIN_ROWS = 3
_MAX_LABEL_VALUE_CONTINUATION_LINES = 4
# A common attachment/photo/document file extension. Used to keep an attachment-list line (e.g. a
# photo caption naming its file) from being absorbed as a prose wrap continuation: such lines never
# end in sentence punctuation, so without this guard a preceding long line would keep swallowing
# every following list entry through to the end of the block.
_FILENAME_EXTENSION_RE = re.compile(
    r"\.(?:jpe?g|png|gif|bmp|tiff?|heic|webp|pdf|docx?|xlsx?)\b", re.IGNORECASE
)
# Standard German business-letter salutation openers and sign-offs. These are generic
# correspondence conventions (not tied to any sender/company) and mark a reliable paragraph
# boundary even on documents whose vertical PDF spacing does not otherwise separate blocks.
_GREETING_LINE_RE = re.compile(r"^(guten tag|sehr geehrte\w*)\b", re.IGNORECASE)
_CLOSING_LINE_RE = re.compile(
    r"^(mit freundlichen gr(?:ü|u)(?:ß|ss)en|freundliche gr(?:ü|u)(?:ß|ss)e"
    r"|beste gr(?:ü|u)(?:ß|ss)e|viele gr(?:ü|u)(?:ß|ss)e|liebe gr(?:ü|u)(?:ß|ss)e"
    r"|hochachtungsvoll)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReadingCell:
    """One transient text fragment with normalized horizontal bounds."""

    text: str
    x0: float
    x1: float


@dataclass(frozen=True)
class ReadingRow:
    """One transient top-to-bottom row; cells stay left-to-right.

    ``source_range`` is an optional page-local, half-open offset span into this page's technical raw
    text (``TextPageResult.text``) that this row's own text was constructed from. It is attached at
    collection time -- either directly from persisted L10 geometry line offsets (exact), or by
    matching this row's whitespace-collapsed text against the page's raw lines under a global-
    uniqueness requirement (see ``_match_row_source_ranges``) -- never by searching the finished
    rendered text afterward. It is row-granularity provenance, not a claim about individual cells or
    characters, and stays ``None`` whenever it cannot be established without guessing.
    """

    page_number: int
    y0: float
    y1: float
    cells: tuple[ReadingCell, ...]
    source_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class RowLineageSegment:
    """One construction-time-attributed reading-text line.

    ``[canonical_start, canonical_end)`` is this line's own half-open offset in the finished
    ``ReadingTextResult.text``; ``[page_start, page_end)`` is the page-local raw
    ``TextPageResult.text`` range (on ``page_number``) it was rendered from. Unlike the post-render
    projection mechanisms, every segment here traces back to a ``ReadingRow.source_range`` that was
    already known before this line was assembled -- offsets are computed by walking the same block
    structure the text was joined from, never by searching the finished string.
    """

    page_number: int
    canonical_start: int
    canonical_end: int
    page_start: int
    page_end: int


@dataclass(frozen=True)
class ReadingTextResult:
    """Reading text plus non-sensitive provenance/quality metadata."""

    text: str
    status: Literal["heuristic", "fallback"]
    flags: tuple[str, ...]
    row_lineage: tuple[RowLineageSegment, ...] = ()


def collect_pdf_reading_rows(
    page: PageObject, page_number: int, page_text: str
) -> list[ReadingRow]:
    """Collect transient positioned rows from a PDF text layer.

    This reads pypdf's decoded visitor callbacks and never persists word/cell geometry. Returning an
    empty list is the safe failure mode; callers then continue through the documented fallbacks.
    ``page_text`` is this page's already-extracted technical raw text (the same string the caller
    stores on ``TextPageResult.text``); it is used only to attach construction-time row source
    ranges (see ``_match_row_source_ranges``) and never changes which rows are collected.
    """

    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        left = float(page.mediabox.left)
        bottom = float(page.mediabox.bottom)
        if width <= 0.0 or height <= 0.0:
            return []
        fragments: list[tuple[str, float, float, float, float, tuple[int, int] | None]] = []
        state = _PdfTextState()

        def visitor_text(
            text: str, _cm: Any, _tm: Any, _font: Any, font_size: float
        ) -> None:
            normalized = _normalize_line(text)
            if state.pending is None:
                return
            x_text, y_text, cm = state.pending
            state.pending = None
            if not normalized:
                return
            size = float(font_size) if font_size > 0 else state.current_font_size
            x, y = _transform_point(x_text, y_text, cm)
            x -= left
            y -= bottom
            estimated_width = min(width - x, max(size * 0.5, len(normalized) * size * 0.52))
            x0 = _clamp(x / width)
            x1 = _clamp((x + estimated_width) / width)
            y0 = _clamp((height - y - size) / height)
            y1 = _clamp((height - y + size * 0.2) / height)
            if x1 > x0 and y1 > y0:
                fragments.append((normalized, x0, y0, x1, y1, None))

        page.extract_text(visitor_operand_before=state.visit_operand, visitor_text=visitor_text)
        rows = _group_fragments(fragments, page_number)
        return _match_row_source_ranges(rows, page_text)
    except Exception:
        return []


def build_reading_text(
    text: str,
    pages: Sequence[TextPageResult],
    text_geometry: TextGeometry | None,
    layout_blocks: Sequence[LayoutBlock],
    layout_text_result: str | None,
    *,
    positioned_rows: Sequence[ReadingRow] = (),
) -> ReadingTextResult | None:
    """Build the canonical reading text without mutating any legacy text field."""

    if not text.strip():
        return None

    positioned_by_page = _rows_by_page(positioned_rows)
    geometry_by_page = (
        {page.page_number: page for page in text_geometry.pages}
        if text_geometry is not None
        else {}
    )
    blocks_by_page: dict[int, list[LayoutBlock]] = {}
    for block in layout_blocks:
        blocks_by_page.setdefault(block.page_number, []).append(block)

    page_blocks: list[str] = []
    flags: list[str] = []
    used_heuristic_source = False
    # Page-local row lineage, kept alongside each contributed page's rendered text so it can be
    # discarded (never mis-mapped) if repeated-margin filtering or a whole-document fallback later
    # changes that page's text.
    page_numbers: list[int] = []
    page_lineage: list[list[tuple[int, int, int, int]]] = []
    for page in pages:
        page_geometry = geometry_by_page.get(page.page_number)
        rendered, page_flags, used_heuristic, page_segments = _build_page_reading(
            page,
            page_geometry,
            blocks_by_page.get(page.page_number, []),
            positioned_by_page.get(page.page_number, []),
        )
        if rendered:
            page_blocks.append(rendered)
            page_numbers.append(page.page_number)
            page_lineage.append(page_segments)
            flags.extend(page_flags)
        used_heuristic_source = used_heuristic_source or used_heuristic

    pre_filter_page_blocks = list(page_blocks)
    page_blocks, filtered_margins = _filter_repeated_page_margins(page_blocks)
    flags.extend(["repeated_page_margins_filtered"] if filtered_margins else [])
    used_heuristic_source = used_heuristic_source or filtered_margins

    # A document-level layout rendering is only safe to use whole when no page already contributed
    # a higher-priority geometric/block reconstruction; otherwise it would duplicate those pages.
    if (
        not used_heuristic_source
        and layout_text_result
        and _source_covers_raw((layout_text_result,), text)
    ):
        layout_fallback = _render_fallback_text(layout_text_result)
        if layout_fallback:
            page_blocks = [layout_fallback]
            flags = ["layout_text_fallback"]
            used_heuristic_source = True
    if not page_blocks:
        raw_fallback = _render_fallback_text(text)
        if not raw_fallback:
            return None
        page_blocks.append(raw_fallback)
        flags.append("raw_order_fallback")

    if len(page_blocks) > 1:
        flags.append("multi_page")

    # Row lineage is only trustworthy when the exact per-page strings it was computed against are
    # still the ones being joined into the final text -- never recomputed by searching the (possibly
    # margin-filtered, layout-fallback-replaced, or raw-fallback-replaced) final string.
    row_lineage = (
        _canonical_row_lineage(page_numbers, page_blocks, page_lineage)
        if page_blocks == pre_filter_page_blocks
        else ()
    )

    return ReadingTextResult(
        text="\n\n".join(page_blocks),
        status="heuristic" if used_heuristic_source else "fallback",
        flags=tuple(dict.fromkeys(flags)),
        row_lineage=row_lineage,
    )


def _canonical_row_lineage(
    page_numbers: Sequence[int],
    page_blocks: Sequence[str],
    page_lineage: Sequence[list[tuple[int, int, int, int]]],
) -> tuple[RowLineageSegment, ...]:
    """Offset each page's already-known page-local segments into the final joined text.

    Purely arithmetic: it walks ``page_blocks`` with the same running ``len(rendered) + 2``
    ("\\n\\n" join) accounting ``build_reading_text`` itself uses, never searching any text.
    """
    segments: list[RowLineageSegment] = []
    canonical_base = 0
    for page_number, rendered, page_segments in zip(
        page_numbers, page_blocks, page_lineage, strict=True
    ):
        for rendered_start, rendered_end, page_start, page_end in page_segments:
            segments.append(
                RowLineageSegment(
                    page_number=page_number,
                    canonical_start=canonical_base + rendered_start,
                    canonical_end=canonical_base + rendered_end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        canonical_base += len(rendered) + 2
    return tuple(segments)


def _build_page_reading(
    page: TextPageResult,
    geometry: TextGeometryPage | None,
    layout_blocks: Sequence[LayoutBlock],
    positioned_rows: Sequence[ReadingRow],
) -> tuple[str | None, list[str], bool, list[tuple[int, int, int, int]]]:
    """Render one page, returning text/flags/heuristic-used plus page-local row lineage segments.

    ``page_segments`` entries are ``(rendered_start, rendered_end, page_start, page_end)``: the
    line's ``[rendered_start, rendered_end)`` offset within the returned ``rendered`` string, paired
    with the page-local ``[page_start, page_end)`` raw range (into ``page.text``) it was
    constructed from. Only the geometry/positioned-row path can produce these; the layout-block and
    raw-fallback paths always return an empty list (no row lineage available there).
    """
    rows = list(positioned_rows)
    if not rows and geometry is not None and geometry.status != "unsupported":
        rows = _rows_from_geometry(page, geometry)
    if rows and _source_covers_raw(
        (cell.text for row in rows for cell in row.cells), page.text
    ):
        blocks, flags, blocks_lineage = _render_positioned_rows(rows)
        rendered, page_segments = _join_blocks_with_lineage(blocks, blocks_lineage)
        if rendered:
            flags.append("geometry_ordering")
            if geometry is not None and geometry.status != "complete":
                flags.append("partial_geometry")
            return rendered, flags, True, page_segments

    usable_blocks = [
        block
        for block in sorted(layout_blocks, key=lambda item: item.order)
        if block.block_type != "fallback" and block.text.strip()
    ]
    if usable_blocks and _source_covers_raw(
        (block.text for block in usable_blocks), page.text
    ):
        rendered = _render_layout_blocks(usable_blocks)
        if rendered:
            return rendered, ["layout_block_ordering"], True, []

    raw_fallback = _render_fallback_text(page.text)
    return raw_fallback or None, ["raw_order_fallback"] if raw_fallback else [], False, []


_Fragment = tuple[str, float, float, float, float, tuple[int, int] | None]


def _group_fragments(fragments: list[_Fragment], page_number: int) -> list[ReadingRow]:
    if not fragments:
        return []
    heights = [fragment[4] - fragment[2] for fragment in fragments]
    tolerance = max(0.002, median(heights) * 0.6)
    groups: list[list[_Fragment]] = []
    for fragment in sorted(fragments, key=lambda item: ((item[2] + item[4]) / 2, item[1])):
        center = (fragment[2] + fragment[4]) / 2
        if groups:
            previous_center = sum((item[2] + item[4]) / 2 for item in groups[-1]) / len(
                groups[-1]
            )
            if abs(center - previous_center) <= tolerance:
                groups[-1].append(fragment)
                continue
        groups.append([fragment])
    return [
        ReadingRow(
            page_number=page_number,
            y0=min(fragment[2] for fragment in group),
            y1=max(fragment[4] for fragment in group),
            cells=tuple(
                ReadingCell(text=fragment[0], x0=fragment[1], x1=fragment[3])
                for fragment in sorted(group, key=lambda item: item[1])
            ),
            source_range=_merge_fragment_ranges(group),
        )
        for group in groups
    ]


def _merge_fragment_ranges(group: Sequence[_Fragment]) -> tuple[int, int] | None:
    """Union contributing fragments' known raw ranges, or decline when any fragment lacks one.

    A fragment without a known range means part of this row's provenance is unaccounted for, so the
    whole row must decline rather than silently understate its own source span.
    """
    ranges: list[tuple[int, int]] = []
    for fragment in group:
        source_range = fragment[5]
        if source_range is None:
            return None
        ranges.append(source_range)
    return min(start for start, _end in ranges), max(end for _start, end in ranges)


def _match_row_source_ranges(rows: list[ReadingRow], page_text: str) -> list[ReadingRow]:
    """Attach construction-time page-local source ranges to pypdf-visitor-collected rows.

    The visitor path (unlike persisted L10 geometry) never learns a raw offset for any fragment it
    collects, so a row's range can only be established by matching its own (whitespace-collapsed)
    text against this page's raw lines -- the exact discipline ``text_geometry.py`` already uses for
    L10 span geometry, applied once per row at collection time instead of once per output line after
    rendering. A row's range is assigned only when both sides are globally unique on this page: its
    collapsed text is not shared by any other collected row, its match is the only raw line sharing
    that exact collapsed text, and no other row claims the same raw line. Any of those conditions
    failing declines (``source_range`` stays ``None``) rather than guessing by processing order --
    duplicated/repeated lines are exactly the case this must not silently resolve.
    """
    if not rows:
        return rows
    raw_lines = segment_page_lines(page_text)
    raw_line_indices_by_text: dict[str, list[int]] = {}
    for index, (_start, _end, collapsed) in enumerate(raw_lines):
        raw_line_indices_by_text.setdefault(collapsed, []).append(index)

    row_collapsed = [
        collapse_line(_join_cell_texts(cell.text for cell in row.cells)) for row in rows
    ]
    row_text_counts = Counter(text for text in row_collapsed if text)

    claims: dict[int, list[int]] = {}
    for row_index, collapsed in enumerate(row_collapsed):
        if not collapsed or row_text_counts[collapsed] != 1:
            continue
        candidates = raw_line_indices_by_text.get(collapsed, [])
        if len(candidates) != 1:
            continue
        claims.setdefault(candidates[0], []).append(row_index)

    resolved: dict[int, tuple[int, int]] = {}
    for raw_index, row_indices in claims.items():
        if len(row_indices) != 1:
            continue
        start, end, _collapsed = raw_lines[raw_index]
        resolved[row_indices[0]] = (start, end)

    if not resolved:
        return rows
    return [
        replace(row, source_range=resolved[index]) if index in resolved else row
        for index, row in enumerate(rows)
    ]


def _rows_by_page(rows: Sequence[ReadingRow]) -> dict[int, list[ReadingRow]]:
    result: dict[int, list[ReadingRow]] = {}
    for row in rows:
        if row.cells:
            result.setdefault(row.page_number, []).append(row)
    for page_rows in result.values():
        page_rows.sort(key=lambda row: (row.y0, row.cells[0].x0))
    return result


def _rows_from_geometry(page: TextPageResult, geometry: TextGeometryPage) -> list[ReadingRow]:
    fragments: list[_Fragment] = [
        (
            _normalize_line(page.text[line.page_start : line.page_end]),
            line.x0 / geometry.page_width,
            line.y0 / geometry.page_height,
            line.x1 / geometry.page_width,
            line.y1 / geometry.page_height,
            (line.page_start, line.page_end),
        )
        for line in geometry.lines
        if page.text[line.page_start : line.page_end].strip()
    ]
    return _group_fragments(fragments, page.page_number)


def _without_separator_cells(row: ReadingRow) -> ReadingRow:
    cells = tuple(
        cell for cell in row.cells if not _SEPARATOR_LINE_RE.fullmatch(cell.text.strip())
    )
    if cells == row.cells:
        return row
    return replace(row, cells=cells)


def _render_positioned_rows(
    rows: Sequence[ReadingRow],
) -> tuple[list[list[str]], list[str], list[list[tuple[int, int] | None]]]:
    # A separator-rule fragment (long underscore/dash run above a heading or table) can share a row
    # with real content purely because of PDF run boundaries. Left in, it both breaks table-header
    # leader detection (the rule becomes "cell 0" instead of the real label) and inflates rendered
    # line length enough to be mistaken for a long prose line. Dropping it here is render-only: the
    # caller's raw-coverage check already ran against the untouched rows, so no source character
    # accounting changes.
    cleaned = [row for row in (_without_separator_cells(row) for row in rows) if row.cells]
    if not cleaned:
        return [], [], []
    ordered = sorted(cleaned, key=lambda row: (row.y0, row.cells[0].x0))
    table_index = next(
        (index for index, row in enumerate(ordered) if _is_table_header(row.cells)), None
    )
    body_end = table_index if table_index is not None else len(ordered)
    party_index = next(
        (index for index, row in enumerate(ordered[:body_end]) if _is_party_heading_row(row)),
        None,
    )
    blocks: list[list[str]] = []
    flags: list[str] = []
    blocks_lineage: list[list[tuple[int, int] | None]] = []
    body_cursor = 0
    if party_index is not None:
        pre_party_blocks, pre_party_flags, pre_party_lineage = _body_blocks(ordered[:party_index])
        blocks.extend(pre_party_blocks)
        blocks_lineage.extend(pre_party_lineage)
        flags.extend(pre_party_flags)
        metadata_index = next(
            (
                index
                for index in range(party_index + 1, body_end)
                if _row_has_prefix(ordered[index], _METADATA_PREFIXES)
            ),
            body_end,
        )
        metadata_index = min(
            metadata_index,
            _party_gap_end(ordered, party_index, metadata_index),
        )
        left, right = _party_columns(ordered[party_index:metadata_index])
        if left and right:
            blocks.extend((left, right))
            blocks_lineage.extend(_none_lineage((left, right)))
            flags.append("two_column_grouping")
            body_cursor = metadata_index
        else:
            body_cursor = party_index
    else:
        metadata_index = next(
            (
                index
                for index, row in enumerate(ordered[:body_end])
                if _row_has_prefix(row, _STANDALONE_METADATA_PREFIXES)
            ),
            body_end,
        )
        body_blocks, body_flags, body_lineage = _body_blocks(ordered[:metadata_index])
        blocks.extend(body_blocks)
        blocks_lineage.extend(body_lineage)
        flags.extend(body_flags)
        body_cursor = metadata_index

    metadata_rows = ordered[body_cursor:body_end]
    if metadata_rows:
        metadata_blocks, metadata_flags = _render_metadata(metadata_rows)
        blocks.extend(metadata_blocks)
        blocks_lineage.extend(_none_lineage(metadata_blocks))
        flags.extend(metadata_flags)

    table_end = body_end
    if table_index is not None:
        table_block, table_end, table_flags = _render_table(ordered, table_index)
        if table_block:
            section_heading = _table_section_heading(ordered[table_index])
            rendered_table_block = [*([section_heading] if section_heading else []), *table_block]
            blocks.append(rendered_table_block)
            blocks_lineage.append([None] * len(rendered_table_block))
            flags.append("table_row_reconstruction")
            flags.extend(table_flags)
            if section_heading:
                flags.append("document_sections")
        else:
            fallback_blocks, fallback_flags, fallback_lineage = _body_blocks(
                ordered[table_index : table_index + 1]
            )
            blocks.extend(fallback_blocks)
            blocks_lineage.extend(fallback_lineage)
            flags.extend(fallback_flags)
            table_end = table_index + 1

    if table_end < len(ordered):
        post_blocks, post_flags = _render_post_table(ordered[table_end:])
        blocks.extend(post_blocks)
        blocks_lineage.extend(_none_lineage(post_blocks))
        flags.extend(post_flags)
    kept_blocks, kept_lineage = _drop_empty_blocks(blocks, blocks_lineage)
    return kept_blocks, flags, kept_lineage


def _drop_empty_blocks(
    blocks: Sequence[list[str]], blocks_lineage: Sequence[list[tuple[int, int] | None]]
) -> tuple[list[list[str]], list[list[tuple[int, int] | None]]]:
    kept_blocks = [block for block in blocks if block]
    kept_lineage = [
        lineage for block, lineage in zip(blocks, blocks_lineage, strict=True) if block
    ]
    return kept_blocks, kept_lineage


def _plain_blocks(rows: Sequence[ReadingRow]) -> list[list[str]]:
    blocks, _flags, _lineage = _plain_blocks_with_flags(rows)
    return blocks


def _body_blocks(
    rows: Sequence[ReadingRow],
) -> tuple[list[list[str]], list[str], list[list[tuple[int, int] | None]]]:
    column_result = _multi_column_blocks(rows)
    if column_result is not None:
        column_blocks, column_lineage = column_result
        return column_blocks, ["multi_column_reconstruction"], column_lineage
    table_result = _generic_table_blocks(rows)
    if table_result is not None:
        return table_result
    return _plain_blocks_with_flags(rows)


def _generic_table_blocks(
    rows: Sequence[ReadingRow],
) -> tuple[list[list[str]], list[str], list[list[tuple[int, int] | None]]] | None:
    """OCR/Text L13: detect a table from repeated row geometry alone, without header keywords.

    Only a maximal run of 3+ consecutive rows that all align on the same 3+ column x-positions
    counts as evidence — the same geometric bar the keyword-header table path already uses for its
    body rows. A shorter or less consistent run is left on the existing safe paths (plain rows, or
    multi-column prose when it already matched) instead of guessing at structure. Row order, cell
    text, and multiline continuation handling all reuse the same primitives as the keyword-header
    table renderer.

    Row lineage: only the plain prefix before the detected table (unmodified rows) can carry real
    lineage; the table block itself and any post-table rendering realign/reformat cells and always
    decline (``None``) in this step.
    """

    row_list = [row for row in rows if row.cells]
    if _has_existing_structural_owner(row_list) or _looks_like_label_value_form(row_list):
        return None
    run = _find_generic_table_run(row_list)
    if run is None:
        return None
    start, end, column_x = run
    body_rows, _ = _extend_aligned_table_rows(row_list, start + 1, column_x)
    aligned_rows = [_align_table_cells(row_list[start], column_x), *body_rows]
    table_block = [" | ".join(cells) for cells in aligned_rows]

    prefix_blocks: list[list[str]]
    prefix_flags: list[str]
    prefix_lineage: list[list[tuple[int, int] | None]]
    if start:
        prefix_blocks, prefix_flags, prefix_lineage = _plain_blocks_with_flags(row_list[:start])
    else:
        prefix_blocks, prefix_flags, prefix_lineage = [], [], []
    blocks: list[list[str]] = [*prefix_blocks, table_block]
    table_block_lineage: list[tuple[int, int] | None] = [None] * len(table_block)
    blocks_lineage: list[list[tuple[int, int] | None]] = [*prefix_lineage, table_block_lineage]
    flags = [*prefix_flags, "table_row_reconstruction", "generic_table_reconstruction"]
    if end < len(row_list):
        post_blocks, post_flags = _render_post_table(row_list[end:])
        blocks.extend(post_blocks)
        blocks_lineage.extend(_none_lineage(post_blocks))
        flags.extend(post_flags)
    return blocks, flags, blocks_lineage


def _none_lineage(blocks: Sequence[Sequence[str]]) -> list[list[tuple[int, int] | None]]:
    """A parallel all-``None`` lineage shape for a block list this step declines to attribute."""
    return [[None for _ in block] for block in blocks]


def _find_generic_table_run(
    rows: Sequence[ReadingRow],
) -> tuple[int, int, list[float]] | None:
    for index, row in enumerate(rows):
        if len(row.cells) < _TABLE_MIN_OCCUPIED_COLUMNS:
            continue
        column_x = [cell.x0 for cell in row.cells]
        body_rows, end = _extend_aligned_table_rows(rows, index + 1, column_x)
        if 1 + len(body_rows) >= _GENERIC_TABLE_MIN_ROWS:
            return index, end, column_x
    return None


def _multi_column_blocks(
    rows: Sequence[ReadingRow],
) -> tuple[list[list[str]], list[list[tuple[int, int] | None]]] | None:
    """Reconstruct multi-column prose.

    Column rows are synthesized from redistributed cells (``_column_rows``) and never carry a
    ``source_range``, so this path's lineage is always ``None`` -- consistent with declining
    lineage for every reordering rendering path in this step.
    """

    columns = _detect_multi_column_layout(rows)
    if columns is None:
        return None
    blocks: list[list[str]] = []
    blocks_lineage: list[list[tuple[int, int] | None]] = []
    for column_rows in columns:
        column_blocks, _flags, column_lineage = _plain_blocks_with_flags(column_rows)
        blocks.extend(column_blocks)
        blocks_lineage.extend(column_lineage)
    return (blocks, blocks_lineage) if blocks else None


def _detect_multi_column_layout(
    rows: Sequence[ReadingRow],
) -> tuple[tuple[ReadingRow, ...], ...] | None:
    row_list = [row for row in rows if row.cells]
    starts = _multi_column_starts(row_list)
    if starts is None:
        return None
    column_rows = _column_rows(row_list, [(left + right) / 2 for left, right in pairwise(starts)])
    if any(len(column) < _COLUMN_MIN_CELLS for column in column_rows):
        return None
    return tuple(
        tuple(sorted(column, key=lambda row: (row.y0, row.cells[0].x0)))
        for column in column_rows
    )


def _multi_column_starts(rows: Sequence[ReadingRow]) -> list[float] | None:
    if len(rows) < _COLUMN_MIN_CELLS:
        return None
    if (
        _has_existing_structural_owner(rows)
        or _looks_table_dense(rows)
        or _looks_like_label_value_form(rows)
    ):
        return None
    clusters = _column_start_clusters(rows)
    if not (2 <= len(clusters) <= _COLUMN_MAX_COUNT):
        return None
    if any(len(cluster) < _COLUMN_MIN_CELLS for cluster in clusters):
        return None
    starts = [median(cell.x0 for _row, cell in cluster) for cluster in clusters]
    if any(right - left < _COLUMN_MIN_GAP for left, right in pairwise(starts)):
        return None
    if not _columns_overlap_vertically(clusters):
        return None
    if not _columns_look_like_prose(clusters):
        return None
    return starts


def _column_rows(rows: Sequence[ReadingRow], boundaries: Sequence[float]) -> list[list[ReadingRow]]:
    column_rows: list[list[ReadingRow]] = [[] for _ in range(len(boundaries) + 1)]
    for row in rows:
        assigned: list[list[ReadingCell]] = [[] for _ in column_rows]
        for cell in row.cells:
            index = _column_index(cell, boundaries)
            assigned[index].append(cell)
        for index, cells in enumerate(assigned):
            if not cells:
                continue
            column_rows[index].append(
                ReadingRow(
                    page_number=row.page_number,
                    y0=row.y0,
                    y1=row.y1,
                    cells=(
                        ReadingCell(
                            text=_join_cell_texts(cell.text for cell in cells),
                            x0=min(cell.x0 for cell in cells),
                            x1=max(cell.x1 for cell in cells),
                        ),
                    ),
                )
            )
    return column_rows


def _has_existing_structural_owner(rows: Sequence[ReadingRow]) -> bool:
    return any(_is_party_heading_row(row) or _is_table_header(row.cells) for row in rows)


def _looks_table_dense(rows: Sequence[ReadingRow]) -> bool:
    too_many_cell_rows = sum(1 for row in rows if len(row.cells) > _COLUMN_MAX_COUNT)
    data_rows = sum(1 for row in rows if _looks_like_data_row(_row_text(row)))
    if too_many_cell_rows >= 1:
        return True
    return data_rows >= 2


def _looks_like_label_value_form(rows: Sequence[ReadingRow]) -> bool:
    candidate_rows = [row for row in rows if len(row.cells) == 2]
    if len(candidate_rows) < _COLUMN_MIN_CELLS:
        return False

    paired_rows: list[ReadingRow] = []
    label_starts: list[float] = []
    value_starts: list[float] = []
    for row in candidate_rows:
        label_cell, value_cell = row.cells
        label = _normalize_line(label_cell.text)
        value = _normalize_line(value_cell.text)
        if (
            _is_standalone_field_label(label)
            and value
            and not _is_standalone_field_label(value)
            and value_cell.x0 - label_cell.x0 >= 0.08
        ):
            paired_rows.append(row)
            label_starts.append(label_cell.x0)
            value_starts.append(value_cell.x0)

    if len(paired_rows) < _COLUMN_MIN_CELLS:
        return False
    if len(paired_rows) / len(candidate_rows) < 0.6:
        return False
    return _starts_are_aligned(label_starts) and _starts_are_aligned(value_starts)


def _starts_are_aligned(starts: Sequence[float]) -> bool:
    if not starts:
        return False
    center = median(starts)
    return all(abs(start - center) <= _COLUMN_START_TOLERANCE for start in starts)


def _column_start_clusters(
    rows: Sequence[ReadingRow],
) -> list[list[tuple[ReadingRow, ReadingCell]]]:
    clusters: list[list[tuple[ReadingRow, ReadingCell]]] = []
    for cluster_row, cell in sorted(
        ((candidate_row, cell) for candidate_row in rows for cell in candidate_row.cells),
        key=lambda item: item[1].x0,
    ):
        if not cell.text.strip():
            continue
        if not clusters:
            clusters.append([(cluster_row, cell)])
            continue
        previous_start = median(existing.x0 for _existing_row, existing in clusters[-1])
        if cell.x0 - previous_start > _COLUMN_START_TOLERANCE:
            clusters.append([(cluster_row, cell)])
        else:
            clusters[-1].append((cluster_row, cell))
    return clusters


def _columns_overlap_vertically(
    clusters: Sequence[Sequence[tuple[ReadingRow, ReadingCell]]],
) -> bool:
    ranges = [
        (
            min(row.y0 for row, _cell in cluster),
            max(row.y1 for row, _cell in cluster),
        )
        for cluster in clusters
    ]
    for left, right in pairwise(ranges):
        overlap = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
        left_height = max(left[1] - left[0], 0.001)
        right_height = max(right[1] - right[0], 0.001)
        if overlap / min(left_height, right_height) < _COLUMN_MIN_OVERLAP:
            return False
    return True


def _columns_look_like_prose(
    clusters: Sequence[Sequence[tuple[ReadingRow, ReadingCell]]],
) -> bool:
    for cluster in clusters:
        texts = [_normalize_line(cell.text) for _row, cell in cluster if cell.text.strip()]
        prose_like = sum(1 for text in texts if _is_column_prose_fragment(text))
        average_words = sum(_word_count(text) for text in texts) / max(len(texts), 1)
        if prose_like < 2 and average_words < 3.0:
            return False
    return True


def _is_column_prose_fragment(text: str) -> bool:
    return len(text) >= 28 or _word_count(text) >= 4


def _word_count(text: str) -> int:
    return sum(1 for token in re.findall(r"\w+", text) if any(char.isalpha() for char in token))


def _column_index(cell: ReadingCell, boundaries: Sequence[float]) -> int:
    for index, boundary in enumerate(boundaries):
        if cell.x0 < boundary:
            return index
    return len(boundaries)


def _plain_blocks_with_flags(
    rows: Sequence[ReadingRow],
) -> tuple[list[list[str]], list[str], list[list[tuple[int, int] | None]]]:
    if not rows:
        return [], [], []
    groups: list[list[ReadingRow]] = [[]]
    heights = [max(0.001, row.y1 - row.y0) for row in rows]
    gap_limit = median(heights) * 2.2
    previous: ReadingRow | None = None
    previous_is_letter_marker = False
    for row in rows:
        is_letter_marker = _is_letter_marker_row(row)
        if previous is not None and (
            row.y0 - previous.y1 > gap_limit or is_letter_marker or previous_is_letter_marker
        ):
            groups.append([])
        groups[-1].append(row)
        previous = row
        previous_is_letter_marker = is_letter_marker
    blocks: list[list[str]] = []
    flags: list[str] = []
    blocks_lineage: list[list[tuple[int, int] | None]] = []
    for group in groups:
        if not group:
            continue
        lines, group_flags, lines_lineage = _join_continuations_with_flags(group)
        blocks.append(lines)
        blocks_lineage.append(lines_lineage)
        flags.extend(group_flags)
    return blocks, flags, blocks_lineage


def _is_letter_marker_row(row: ReadingRow) -> bool:
    """A greeting opener or sign-off closing always starts its own paragraph.

    Unlike ordinary paragraph gaps, these are fixed, well-known correspondence conventions, so they
    are a safe boundary signal even where this document's vertical spacing is not.
    """

    stripped = _row_text(row).strip()
    return bool(_GREETING_LINE_RE.match(stripped) or _CLOSING_LINE_RE.match(stripped))


def _join_continuations(rows: Sequence[ReadingRow]) -> list[str]:
    lines, _flags, _lineage = _join_continuations_with_flags(rows)
    return lines


def _join_continuations_with_flags(
    rows: Sequence[ReadingRow],
) -> tuple[list[str], list[str], list[tuple[int, int] | None]]:
    """Render one gap-grouped block, joining bullet/prose wrap continuations conservatively.

    A bulleted item or long prose line keeps absorbing the next row while it has not yet reached a
    sentence end, the next row is neither a new bullet nor a label/value line, and the two rows sit
    at normal single-line spacing. The terminal-punctuation stop is required here (unlike the
    post-table joiner below): this block's rows can share near-identical line spacing between
    genuinely separate sentences, so row-closeness alone is not a reliable continuation signal and
    would otherwise keep absorbing unrelated following lines.

    This is the one rendering path this OCR/Text stabilization step attaches real, construction-time
    row lineage to. The third return value is a per-output-line list of page-local raw source ranges
    (parallel to ``lines``): a single untouched row passes its own known ``source_range`` through
    directly, a merge of several rows (wrap continuation, adjacent label/value pairing) unions their
    ranges only when *every* contributing row has one, and a within-row split
    (``_paired_cell_lines``) declines (``None``) rather than guess a sub-row range. Every other
    rendering path in this module (party columns, tables, multi-column reconstruction, metadata,
    post-table) still redistributes or reformats cells and is not instrumented in this step; its
    lines always carry ``None`` here.
    """

    row_list = list(rows)
    rendered = [_row_text(row) for row in row_list]
    lines: list[str] = []
    flags: list[str] = []
    lines_lineage: list[tuple[int, int] | None] = []
    cursor = 0
    while cursor < len(rendered):
        paired = _paired_cell_lines(row_list[cursor])
        if paired:
            lines.extend(paired)
            lines_lineage.extend([None] * len(paired))
            flags.append("label_value_pairing")
            cursor += 1
            continue
        line = rendered[cursor]
        if (
            cursor + 1 < len(rendered)
            and _safe_adjacent_label_value(row_list[cursor], row_list[cursor + 1])
        ):
            value_end = _label_value_continuation_end(row_list, cursor + 1)
            value_text = rendered[cursor + 1]
            for extra in rendered[cursor + 2 : value_end]:
                value_text = _join_wrapped_line(value_text, extra)
            lines.append(f"{line.rstrip().rstrip(':')}: {value_text}")
            lines_lineage.append(_union_source_ranges(row_list[cursor:value_end]))
            flags.append("label_value_pairing")
            if value_end > cursor + 2:
                flags.append("multiline_value_pairing")
            cursor = value_end
            continue
        is_bullet = line.startswith("- ")
        if is_bullet or _is_long_prose_line(line):
            paragraph = line
            paragraph_rows = [row_list[cursor]]
            cursor += 1
            while (
                cursor < len(rendered)
                and not paragraph.rstrip().endswith((".", "!", "?"))
                and not rendered[cursor].startswith("- ")
                and not _starts_new_post_block(rendered[cursor])
                and not _looks_like_data_row(rendered[cursor])
                and not _looks_like_filename_row(rendered[cursor])
                and _rows_are_close(row_list[cursor - 1], row_list[cursor])
            ):
                paragraph = _join_wrapped_line(paragraph, rendered[cursor])
                paragraph_rows.append(row_list[cursor])
                cursor += 1
            lines.append(paragraph)
            lines_lineage.append(_union_source_ranges(paragraph_rows))
            continue
        lines.append(line)
        lines_lineage.append(row_list[cursor].source_range)
        cursor += 1
    return lines, flags, lines_lineage


def _union_source_ranges(rows: Sequence[ReadingRow]) -> tuple[int, int] | None:
    """Union rows' known source ranges when every row has one and raw order stays non-decreasing.

    Rows merged here were adjacent in *visual* (reading) order, not necessarily in *raw* order --
    reordered columns/sections can interleave. Requiring each next row's range to start no earlier
    than the previous row's own range ended keeps a merged envelope from silently spanning raw text
    that belongs to some other, separately rendered row; any out-of-order pair declines instead.
    """
    ranges: list[tuple[int, int]] = []
    for row in rows:
        if row.source_range is None:
            return None
        ranges.append(row.source_range)
    if not ranges:
        return None
    for previous, current in pairwise(ranges):
        if current[0] < previous[1]:
            return None
    return ranges[0][0], ranges[-1][1]


def _paired_cell_lines(row: ReadingRow) -> list[str]:
    if len(row.cells) < 4 or len(row.cells) % 2 != 0:
        return []
    pairs: list[str] = []
    for index in range(0, len(row.cells), 2):
        label = _normalize_line(row.cells[index].text)
        value = _normalize_line(row.cells[index + 1].text)
        if not _is_standalone_field_label(label) or _is_standalone_field_label(value):
            return []
        pairs.append(f"{label.rstrip(':')}: {value}")
    return pairs


def _safe_adjacent_label_value(label_row: ReadingRow, value_row: ReadingRow) -> bool:
    label = _row_text(label_row)
    value = _row_text(value_row)
    if (
        not _is_standalone_field_label(label)
        or not value
        or _is_standalone_field_label(value)
        or _looks_like_heading_text(value)
        or not _rows_are_close(label_row, value_row)
    ):
        return False
    label_x = label_row.cells[0].x0
    value_x = value_row.cells[0].x0
    horizontal_offset = value_x - label_x
    if 0.08 <= horizontal_offset <= 0.45:
        return True
    return abs(horizontal_offset) <= 0.05 and _looks_like_short_field_value(value)


def _label_value_continuation_end(row_list: Sequence[ReadingRow], value_index: int) -> int:
    """OCR/Text L13: extend a paired adjacent-row value across following continuation rows.

    Each extra row must sit in the same column as the first value row, stay at normal line
    spacing, and not itself look like a new label, heading, bullet, or data/filename row —
    otherwise the original single-row value is kept, matching the existing conservative
    adjacent-pairing rule this extends. A hard cap bounds how many extra rows can join so a
    genuinely unrelated but superficially value-like run of short lines cannot be absorbed
    indefinitely.
    """

    value_row = row_list[value_index]
    end = value_index + 1
    limit = min(len(row_list), value_index + 1 + _MAX_LABEL_VALUE_CONTINUATION_LINES)
    while end < limit:
        candidate = row_list[end]
        if len(candidate.cells) != 1:
            break
        text = _row_text(candidate)
        if (
            not text
            or _is_standalone_field_label(text)
            or _starts_new_post_block(text)
            or _looks_like_heading_text(text)
            or _looks_like_data_row(text)
            or _looks_like_filename_row(text)
            or text.startswith("- ")
            or abs(candidate.cells[0].x0 - value_row.cells[0].x0) > _COLUMN_START_TOLERANCE
            or not _rows_are_close(row_list[end - 1], candidate)
        ):
            break
        end += 1
    return end


def _is_standalone_field_label(text: str) -> bool:
    stripped = text.strip()
    return bool(
        _STANDALONE_FIELD_LABEL_RE.fullmatch(stripped)
        and 1 <= _word_count(stripped.rstrip(":")) <= 5
    )


def _looks_like_short_field_value(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(stripped)
        and len(stripped) <= 60
        and not stripped.endswith((".", "!", "?"))
        and bool(_SHORT_FIELD_VALUE_RE.match(stripped))
    )


def _looks_like_heading_text(text: str) -> bool:
    stripped = text.strip().rstrip(":")
    if not stripped or len(stripped) > 80 or any(char in stripped for char in "|;\t"):
        return False
    words = stripped.split()
    if len(words) > 8 or any(char.isdigit() for char in stripped):
        return False
    letters = [char for char in stripped if char.isalpha()]
    return bool(letters) and (
        stripped.isupper()
        or (len(words) <= 5 and all(word[:1].isupper() for word in words if word))
    )


def _join_wrapped_line(previous: str, current: str) -> str:
    """Join a wrap continuation, repairing a source line-break hyphen when present.

    Mirrors the same conservative rule already used for the separate ``readable_text`` view: a
    line ending in a 2+ letter word followed by a hyphen, continued by a line starting with a
    letter, is a PDF line-wrap hyphenation, not a real compound-word or range hyphen.
    """

    if _DEHYPHENATE_RE.search(previous) and _WORD_START_RE.match(current):
        return previous[:-1] + current
    return f"{previous} {current}"


def _is_party_heading_row(row: ReadingRow) -> bool:
    if len(row.cells) < 2:
        return False
    matches = sum(_is_party_heading_cell(cell.text) for cell in row.cells)
    return matches >= 2 and row.cells[-1].x0 - row.cells[0].x0 >= 0.25


def _is_party_heading_cell(text: str) -> bool:
    normalized = _normalize_line(text).upper().rstrip(":")
    if len(normalized) > 36:
        return False
    return normalized in _PARTY_HEADING_MARKERS


def _party_columns(rows: Sequence[ReadingRow]) -> tuple[list[str], list[str]]:
    if not rows or len(rows[0].cells) < 2:
        return [], []
    boundary = (rows[0].cells[0].x0 + rows[0].cells[-1].x0) / 2
    left: list[str] = []
    right: list[str] = []
    for row in rows:
        for cell in row.cells:
            target = left if cell.x0 < boundary else right
            target.append(cell.text)
    return left, right


def _party_gap_end(rows: Sequence[ReadingRow], start: int, limit: int) -> int:
    candidate_rows = rows[start:limit]
    if len(candidate_rows) < 2:
        return limit
    heights = [max(0.001, row.y1 - row.y0) for row in candidate_rows]
    gap_limit = median(heights) * 2.2
    for index in range(start + 1, limit):
        if rows[index].y0 - rows[index - 1].y1 > gap_limit:
            return index
    return limit


def _render_metadata(rows: Sequence[ReadingRow]) -> tuple[list[list[str]], list[str]]:
    lines = [part for row in rows for part in _split_paired_labels(_row_text(row))]
    if not lines:
        return [], []
    has_offer = any(
        line.casefold().startswith(("angebot", "datum:", "bauvorhaben:"))
        for line in lines
    )
    if has_offer:
        return [["ANGEBOT", *lines]], []
    return [lines], []


def _is_table_header(cells: Sequence[ReadingCell]) -> bool:
    if len(cells) >= _TABLE_MIN_OCCUPIED_COLUMNS:
        texts = [_normalized_header_text(cell.text) for cell in cells]
    elif cells:
        # OCR/Text L13: a 1- or 2-cell header row may be fused (a PDF/OCR run boundary landed
        # mid-header) or partially fused (only some columns fused). Concatenating whatever cells
        # exist and re-splitting on known markers handles both the already-supported single fused
        # cell and a new partially fused 2-cell case with the same regex-based evidence.
        combined = " ".join(cell.text for cell in cells)
        texts = [
            _normalized_header_text(label) for label in _split_fused_table_header(combined)
        ]
    else:
        return False
    if len(texts) < 3:
        return False
    if not texts[0].startswith(_TABLE_HEADER_LEADERS):
        return False
    marker_count = sum(any(marker in text for marker in _TABLE_HEADER_MARKERS) for text in texts)
    return marker_count >= min(3, len(texts))


def _split_fused_table_header(text: str) -> list[str]:
    matches = list(_HEADER_LABEL_RE.finditer(text))
    if len(matches) < 3:
        return []
    labels: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = text[match.start() : end].strip(" |:;,-")
        if label:
            labels.append(label)
    return labels


def _normalized_header_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().strip().rstrip(":"))


def _table_section_heading(header: ReadingRow) -> str | None:
    first = _normalized_header_text(header.cells[0].text)
    return "LEISTUNGEN" if first.startswith("pos") and len(header.cells) >= 5 else None


def _render_table(rows: Sequence[ReadingRow], start: int) -> tuple[list[str], int, list[str]]:
    header = rows[start]
    header_labels = _table_header_labels(header)
    column_x = _table_column_positions(rows, start, len(header_labels))
    if len(header_labels) < 3 or column_x is None:
        return [], start, []
    body_rows, end = _extend_aligned_table_rows(rows, start + 1, column_x)
    aligned_rows = [header_labels, *body_rows]
    flags = ["dense_table_reconstruction"] if len(header.cells) in (1, 2) else []
    return [" | ".join(cells) for cells in aligned_rows], end, flags


def _extend_aligned_table_rows(
    rows: Sequence[ReadingRow], start: int, column_x: Sequence[float]
) -> tuple[list[list[str]], int]:
    """Row-align rows from ``start`` onward while column occupancy stays safe.

    Shared by the keyword-header table renderer and the OCR/Text L13 generic geometric table
    detector below. A lone single-cell row landing in an already-used column is treated as a
    wrapped multiline continuation of the previous row's cell in that column rather than a new
    row, keeping a multiline table description attached to its owning row.
    """

    aligned_rows: list[list[str]] = []
    end = start
    while end < len(rows):
        aligned, occupied = _align_table_cells_with_occupied(rows[end], column_x)
        if len(occupied) >= min(_TABLE_MIN_OCCUPIED_COLUMNS, len(column_x)):
            aligned_rows.append(aligned)
            end += 1
            continue
        if aligned_rows and len(rows[end].cells) == 1 and len(occupied) == 1:
            continuation_column = next(iter(occupied))
            if continuation_column > 0:
                continuation = aligned[continuation_column]
                aligned_rows[-1][continuation_column] = (
                    f"{aligned_rows[-1][continuation_column]} {continuation}".strip()
                )
                end += 1
                continue
        break
    return aligned_rows, end


def _table_header_labels(header: ReadingRow) -> list[str]:
    if len(header.cells) >= _TABLE_MIN_OCCUPIED_COLUMNS:
        return [cell.text for cell in header.cells]
    combined = " ".join(cell.text for cell in header.cells)
    return _split_fused_table_header(combined)


def _table_column_positions(
    rows: Sequence[ReadingRow], start: int, expected_count: int
) -> list[float] | None:
    header = rows[start]
    if len(header.cells) >= expected_count:
        return [cell.x0 for cell in header.cells[:expected_count]]
    for row in rows[start + 1 :]:
        if len(row.cells) >= expected_count:
            return [cell.x0 for cell in row.cells[:expected_count]]
        if len(row.cells) == 1:
            continue
        break
    return None


def _align_table_cells(row: ReadingRow, column_x: Sequence[float]) -> list[str]:
    cells, _ = _align_table_cells_with_occupied(row, column_x)
    return cells


def _align_table_cells_with_occupied(
    row: ReadingRow, column_x: Sequence[float]
) -> tuple[list[str], set[int]]:
    if len(row.cells) == len(column_x):
        return [fragment.text for fragment in row.cells], set(range(len(column_x)))
    cells = [""] * len(column_x)
    occupied: set[int] = set()
    for fragment in row.cells:
        nearest = min(range(len(column_x)), key=lambda index: abs(column_x[index] - fragment.x0))
        cells[nearest] = f"{cells[nearest]} {fragment.text}".strip()
        occupied.add(nearest)
    return cells, occupied


def _render_post_table(rows: Sequence[ReadingRow]) -> tuple[list[list[str]], list[str]]:
    lines = [_row_text(row) for row in rows]
    blocks: list[list[str]] = []
    flags: list[str] = []
    total_lines: list[str] = []
    cursor = 0
    while cursor < len(lines) and lines[cursor].casefold().startswith(_TOTAL_PREFIXES):
        total_lines.append(lines[cursor])
        cursor += 1
    if total_lines:
        blocks.append(["SUMMEN", *total_lines])
        flags.append("document_sections")

    while cursor < len(lines):
        line = lines[cursor]
        if line.casefold().startswith(_PARAGRAPH_PREFIXES):
            paragraph = line
            cursor += 1
            while (
                cursor < len(lines)
                and not paragraph.rstrip().endswith((".", "!", "?"))
                and not _starts_new_post_block(lines[cursor])
                and not _looks_like_filename_row(lines[cursor])
            ):
                paragraph = f"{paragraph} {lines[cursor]}"
                cursor += 1
            blocks.append([paragraph])
            flags.append("conservative_line_joining")
            continue
        if _is_long_prose_line(line):
            paragraph = line
            cursor += 1
            while (
                cursor < len(lines)
                and _rows_are_close(rows[cursor - 1], rows[cursor])
                and not _starts_new_post_block(lines[cursor])
                and not _looks_like_filename_row(lines[cursor])
            ):
                paragraph = f"{paragraph} {lines[cursor]}"
                cursor += 1
            blocks.append([paragraph])
            flags.append("conservative_line_joining")
            continue
        blocks.append([line])
        cursor += 1
    return blocks, flags


def _is_long_prose_line(line: str) -> bool:
    return (
        len(line) >= 60
        and not _starts_new_post_block(line)
        and not _looks_like_data_row(line)
        and not _looks_like_filename_row(line)
    )


def _looks_like_filename_row(line: str) -> bool:
    """A line naming an attachment/photo file is a list entry, not a prose sentence.

    Such a line (e.g. a photo caption like "Bild Küche / IMG_1234.jpg") never ends in sentence
    punctuation, so without this guard it would either be misread as a long-prose paragraph starter
    itself, or get silently absorbed into a preceding one, together with every following list entry
    through to the end of the block.
    """

    return bool(_FILENAME_EXTENSION_RE.search(line))


def _looks_like_data_row(line: str) -> bool:
    """A line naming two or more decimal amounts is a flattened table/cost row, not prose.

    A genuine sentence rarely cites more than one decimal figure; a row from a table that failed
    column detection (e.g. "Beschreibung 6,00 Std 67,50 405,00") typically strings several
    together. Treating it as prose would make the continuation loop below swallow the rest of the
    table, since such rows are tightly spaced and never end in sentence punctuation.
    """

    return len(_DECIMAL_AMOUNT_RE.findall(line)) >= 2


def _rows_are_close(previous: ReadingRow, current: ReadingRow) -> bool:
    row_height = max(previous.y1 - previous.y0, current.y1 - current.y0, 0.001)
    return current.y0 - previous.y0 <= row_height * 1.65


def _starts_new_post_block(line: str) -> bool:
    folded = line.casefold()
    return bool(_LABEL_VALUE_RE.match(line)) or folded.startswith(
        ("sachbearbeiter:", "ansprechpartner:", *_TOTAL_PREFIXES)
    )


def _row_has_prefix(row: ReadingRow, prefixes: Sequence[str]) -> bool:
    return any(cell.text.casefold().startswith(tuple(prefixes)) for cell in row.cells)


def _row_text(row: ReadingRow) -> str:
    text = _join_cell_texts(cell.text for cell in row.cells)
    return _BULLET_PREFIX_RE.sub("- ", text, count=1)


def _join_cell_texts(texts: Iterable[str]) -> str:
    """Join transient cell fragments, closing punctuation-only splits without adding a space.

    Positioned PDF/OCR extraction sometimes yields a trailing punctuation mark (or a punctuation
    mark plus trailing words) as its own fragment purely because of run-boundary quirks, not a real
    word gap. A plain space-join would then introduce a space the source text never had (e.g.
    ``"word ."``). Only exact closing-punctuation-only fragments (and closing-punctuation-prefixed
    fragments) are glued tightly; anything else keeps the normal single space between fragments.
    """

    result = ""
    previous_open_punct = False
    for token in texts:
        if not token:
            continue
        if not result:
            result = token
            previous_open_punct = token in _OPEN_PUNCT_TOKENS
            continue
        match = _LEADING_CLOSE_PUNCT_RE.match(token)
        if match and match.group(1):
            punct, _gap, rest = match.groups()
            result = f"{result}{punct}"
            if rest:
                result = f"{result} {rest}"
            previous_open_punct = False
            continue
        result = f"{result}{token}" if previous_open_punct else f"{result} {token}"
        previous_open_punct = token in _OPEN_PUNCT_TOKENS
    return result.strip()


def _render_layout_blocks(blocks: Sequence[LayoutBlock]) -> str:
    normalized = [
        [_normalize_line(line) for line in block.text.splitlines() if _normalize_line(line)]
        for block in blocks
    ]
    return _join_blocks([block for block in normalized if block])


def _render_fallback_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in normalized.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            if current:
                blocks.append(current)
                current = []
            continue
        if "\t" in stripped:
            cells = [_normalize_line(cell) for cell in stripped.split("\t")]
            current.append(" | ".join(cells))
        else:
            current.append(_normalize_line(stripped))
    if current:
        blocks.append(current)
    return _join_blocks(blocks)


def _filter_repeated_page_margins(page_blocks: Sequence[str]) -> tuple[list[str], bool]:
    if len(page_blocks) <= 1:
        return list(page_blocks), False
    cleaned_pages, cleaned_changed = _clean_page_blocks(page_blocks)
    occurrences = _margin_occurrences(cleaned_pages)
    removals = _repeated_margin_removals(occurrences)
    filtered_pages = [
        "\n".join(
            line
            for line_index, line in enumerate(lines)
            if (page_index, line_index) not in removals
        ).strip()
        for page_index, lines in enumerate(cleaned_pages)
    ]
    return [page for page in filtered_pages if page], cleaned_changed or bool(removals)


def _clean_page_blocks(page_blocks: Sequence[str]) -> tuple[list[list[str]], bool]:
    cleaned_pages: list[list[str]] = []
    changed = False
    for block in page_blocks:
        cleaned_lines: list[str] = []
        for line in block.splitlines():
            if not line.strip():
                cleaned_lines.append("")
                continue
            cleaned = _clean_page_margin_line(line)
            if cleaned != line:
                changed = True
            if cleaned is not None:
                cleaned_lines.append(cleaned)
        cleaned_pages.append(cleaned_lines)
    return cleaned_pages, changed


def _margin_occurrences(
    cleaned_pages: Sequence[Sequence[str]],
) -> dict[str, list[tuple[int, int, Literal["top", "bottom"]]]]:
    occurrences: dict[str, list[tuple[int, int, Literal["top", "bottom"]]]] = {}
    for page_index, lines in enumerate(cleaned_pages):
        content_indices = [index for index, line in enumerate(lines) if line]
        top_indices = set(content_indices[:_MARGIN_LINE_COUNT])
        bottom_indices = set(content_indices[-_MARGIN_LINE_COUNT:])
        for line_index in top_indices | bottom_indices:
            key = _normalize_line(lines[line_index]).casefold()
            if not key:
                continue
            if line_index in top_indices and line_index in bottom_indices:
                position: Literal["top", "bottom"] = (
                    "top" if line_index < len(lines) / 2 else "bottom"
                )
            else:
                position = "top" if line_index in top_indices else "bottom"
            occurrences.setdefault(key, []).append((page_index, line_index, position))
    return occurrences


def _repeated_margin_removals(
    occurrences: dict[str, list[tuple[int, int, Literal["top", "bottom"]]]],
) -> set[tuple[int, int]]:
    removals: set[tuple[int, int]] = set()
    for repeated in occurrences.values():
        page_indices = {page_index for page_index, _, _ in repeated}
        if len(page_indices) < 2:
            continue
        positions = {position for _, _, position in repeated}
        preferred_page = max(page_indices) if positions == {"bottom"} else min(page_indices)
        kept = False
        for page_index, line_index, _ in repeated:
            occurrence = (page_index, line_index)
            if page_index == preferred_page and not kept:
                kept = True
                continue
            removals.add(occurrence)
    return removals


def _clean_page_margin_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or _SEPARATOR_LINE_RE.fullmatch(stripped):
        return None
    stripped = _normalize_line(_INLINE_SEPARATOR_RE.sub(" ", stripped))
    if not stripped:
        return None
    # Strip a trailing page-number suffix repeatedly, not just once: two adjacent PDF text runs
    # that are both, on their own, the exact same bare page-number marker (e.g. a duplicated
    # running header fragment landing in the same positioned row) must not leave one copy of that
    # marker behind disguised as a "real" prefix after only the last copy is removed.
    while True:
        match = _PAGE_NUMBER_SUFFIX_RE.search(stripped)
        if match is None:
            return stripped
        prefix = stripped[: match.start()].rstrip(" |,;-")
        # A bare page-number line (e.g. "Seite 3 von 8", "Page 1/3") has no real prefix and is
        # always noise. Any other non-empty prefix is real content and must survive the suffix
        # strip: a short prefix that repeats across pages (e.g. a running "<case-number> Seite: N"
        # header) is exactly what the cross-page dedup below is for, and a short prefix that
        # appears on only one page is not page-margin noise at all.
        if not prefix:
            return None
        if prefix == stripped:
            return stripped
        stripped = prefix


def _split_paired_labels(line: str) -> list[str]:
    return [part.strip() for part in _PAIRED_LABEL_RE.split(line) if part.strip()]


def _join_blocks(blocks: Sequence[Sequence[str]]) -> str:
    return "\n\n".join("\n".join(line for line in block if line) for block in blocks if block)


def _join_blocks_with_lineage(
    blocks: Sequence[Sequence[str]],
    blocks_lineage: Sequence[Sequence[tuple[int, int] | None]],
) -> tuple[str, list[tuple[int, int, int, int]]]:
    """Join blocks exactly like ``_join_blocks`` while also locating each surviving line's offset.

    Positions are computed purely from line lengths and the same ``"\\n\\n"``/``"\\n"`` separators
    ``_join_blocks`` uses -- never by searching the joined text -- so the returned string is always
    byte-identical to ``_join_blocks(blocks)``. The second return value is ``(rendered_start,
    rendered_end, page_start, page_end)`` for every line that both survives the same truthiness
    filtering ``_join_blocks`` applies and carries a known ``blocks_lineage`` entry.
    """
    rendered_blocks: list[str] = []
    segments: list[tuple[int, int, int, int]] = []
    cursor = 0
    first_block = True
    for block, block_lineage in zip(blocks, blocks_lineage, strict=True):
        lines = [
            (line, source_range)
            for line, source_range in zip(block, block_lineage, strict=True)
            if line
        ]
        if not lines:
            continue
        if not first_block:
            cursor += 2
        first_block = False
        rendered_lines: list[str] = []
        first_line = True
        for line, source_range in lines:
            if not first_line:
                cursor += 1
            first_line = False
            start = cursor
            cursor += len(line)
            if source_range is not None:
                segments.append((start, cursor, source_range[0], source_range[1]))
            rendered_lines.append(line)
        rendered_blocks.append("\n".join(rendered_lines))
    return "\n\n".join(rendered_blocks), segments


def _normalize_line(text: str) -> str:
    return _SPACE_RUN_RE.sub(" ", text.strip())


def _source_covers_raw(source_parts: Iterable[str], raw: str) -> bool:
    """Require every non-whitespace raw character before trusting a reordered source.

    The check is intentionally order-independent because the purpose of this layer is to improve
    reading order. A partial visitor/layout result can never silently drop source data; it falls
    through to the next safer source instead.
    """

    source_counts = Counter(
        character
        for part in source_parts
        for character in part
        if not character.isspace()
    )
    raw_counts = Counter(character for character in raw if not character.isspace())
    return all(source_counts[character] >= count for character, count in raw_counts.items())


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
