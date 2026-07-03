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
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

from pypdf import PageObject

from app.schemas import LayoutBlock, TextGeometry, TextGeometryPage, TextPageResult
from app.services.layout_text import _PdfTextState, _transform_point

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


@dataclass(frozen=True)
class ReadingCell:
    """One transient text fragment with normalized horizontal bounds."""

    text: str
    x0: float
    x1: float


@dataclass(frozen=True)
class ReadingRow:
    """One transient top-to-bottom row; cells stay left-to-right."""

    page_number: int
    y0: float
    y1: float
    cells: tuple[ReadingCell, ...]


@dataclass(frozen=True)
class ReadingTextResult:
    """Reading text plus non-sensitive provenance/quality metadata."""

    text: str
    status: Literal["heuristic", "fallback"]
    flags: tuple[str, ...]


def collect_pdf_reading_rows(page: PageObject, page_number: int) -> list[ReadingRow]:
    """Collect transient positioned rows from a PDF text layer.

    This reads pypdf's decoded visitor callbacks and never persists word/cell geometry. Returning an
    empty list is the safe failure mode; callers then continue through the documented fallbacks.
    """

    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        left = float(page.mediabox.left)
        bottom = float(page.mediabox.bottom)
        if width <= 0.0 or height <= 0.0:
            return []
        fragments: list[tuple[str, float, float, float, float]] = []
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
                fragments.append((normalized, x0, y0, x1, y1))

        page.extract_text(visitor_operand_before=state.visit_operand, visitor_text=visitor_text)
        return _group_fragments(fragments, page_number)
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
    for page in pages:
        page_geometry = geometry_by_page.get(page.page_number)
        rendered, page_flags, used_heuristic = _build_page_reading(
            page,
            page_geometry,
            blocks_by_page.get(page.page_number, []),
            positioned_by_page.get(page.page_number, []),
        )
        if rendered:
            page_blocks.append(rendered)
            flags.extend(page_flags)
        used_heuristic_source = used_heuristic_source or used_heuristic

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
    return ReadingTextResult(
        text="\n\n".join(page_blocks),
        status="heuristic" if used_heuristic_source else "fallback",
        flags=tuple(dict.fromkeys(flags)),
    )


def _build_page_reading(
    page: TextPageResult,
    geometry: TextGeometryPage | None,
    layout_blocks: Sequence[LayoutBlock],
    positioned_rows: Sequence[ReadingRow],
) -> tuple[str | None, list[str], bool]:
    rows = list(positioned_rows)
    if not rows and geometry is not None and geometry.status != "unsupported":
        rows = _rows_from_geometry(page, geometry)
    if rows and _source_covers_raw(
        (cell.text for row in rows for cell in row.cells), page.text
    ):
        blocks, flags = _render_positioned_rows(rows)
        rendered = _join_blocks(blocks)
        if rendered:
            flags.append("geometry_ordering")
            if geometry is not None and geometry.status != "complete":
                flags.append("partial_geometry")
            return rendered, flags, True

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
            return rendered, ["layout_block_ordering"], True

    raw_fallback = _render_fallback_text(page.text)
    return raw_fallback or None, ["raw_order_fallback"] if raw_fallback else [], False


def _group_fragments(
    fragments: list[tuple[str, float, float, float, float]], page_number: int
) -> list[ReadingRow]:
    if not fragments:
        return []
    heights = [fragment[4] - fragment[2] for fragment in fragments]
    tolerance = max(0.002, median(heights) * 0.6)
    groups: list[list[tuple[str, float, float, float, float]]] = []
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
        )
        for group in groups
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
    fragments = [
        (
            _normalize_line(page.text[line.page_start : line.page_end]),
            line.x0 / geometry.page_width,
            line.y0 / geometry.page_height,
            line.x1 / geometry.page_width,
            line.y1 / geometry.page_height,
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
    return ReadingRow(page_number=row.page_number, y0=row.y0, y1=row.y1, cells=cells)


def _render_positioned_rows(rows: Sequence[ReadingRow]) -> tuple[list[list[str]], list[str]]:
    # A separator-rule fragment (long underscore/dash run above a heading or table) can share a row
    # with real content purely because of PDF run boundaries. Left in, it both breaks table-header
    # leader detection (the rule becomes "cell 0" instead of the real label) and inflates rendered
    # line length enough to be mistaken for a long prose line. Dropping it here is render-only: the
    # caller's raw-coverage check already ran against the untouched rows, so no source character
    # accounting changes.
    cleaned = [row for row in (_without_separator_cells(row) for row in rows) if row.cells]
    if not cleaned:
        return [], []
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
    body_cursor = 0
    if party_index is not None:
        blocks.extend(_plain_blocks(ordered[:party_index]))
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
        blocks.extend(_plain_blocks(ordered[:metadata_index]))
        body_cursor = metadata_index

    metadata_rows = ordered[body_cursor:body_end]
    if metadata_rows:
        blocks.extend(_render_metadata(metadata_rows))

    table_end = body_end
    if table_index is not None:
        table_block, table_end = _render_table(ordered, table_index)
        if table_block:
            section_heading = _table_section_heading(ordered[table_index])
            blocks.append([*([section_heading] if section_heading else []), *table_block])
            flags.append("table_row_reconstruction")
            if section_heading:
                flags.append("document_sections")
        else:
            blocks.extend(_plain_blocks(ordered[table_index : table_index + 1]))
            table_end = table_index + 1

    if table_end < len(ordered):
        post_blocks, post_flags = _render_post_table(ordered[table_end:])
        blocks.extend(post_blocks)
        flags.extend(post_flags)
    return [block for block in blocks if block], flags


def _plain_blocks(rows: Sequence[ReadingRow]) -> list[list[str]]:
    if not rows:
        return []
    groups: list[list[ReadingRow]] = [[]]
    heights = [max(0.001, row.y1 - row.y0) for row in rows]
    gap_limit = median(heights) * 2.2
    previous: ReadingRow | None = None
    for row in rows:
        if previous is not None and row.y0 - previous.y1 > gap_limit:
            groups.append([])
        groups[-1].append(row)
        previous = row
    return [_join_continuations(group) for group in groups if group]


def _join_continuations(rows: Sequence[ReadingRow]) -> list[str]:
    """Render one gap-grouped block, joining bullet/prose wrap continuations conservatively.

    A bulleted item or long prose line keeps absorbing the next row while it has not yet reached a
    sentence end, the next row is neither a new bullet nor a label/value line, and the two rows sit
    at normal single-line spacing. The terminal-punctuation stop is required here (unlike the
    post-table joiner below): this block's rows can share near-identical line spacing between
    genuinely separate sentences, so row-closeness alone is not a reliable continuation signal and
    would otherwise keep absorbing unrelated following lines.
    """

    row_list = list(rows)
    rendered = [_row_text(row) for row in row_list]
    lines: list[str] = []
    cursor = 0
    while cursor < len(rendered):
        line = rendered[cursor]
        is_bullet = line.startswith("- ")
        if is_bullet or _is_long_prose_line(line):
            paragraph = line
            cursor += 1
            while (
                cursor < len(rendered)
                and not paragraph.rstrip().endswith((".", "!", "?"))
                and not rendered[cursor].startswith("- ")
                and not _starts_new_post_block(rendered[cursor])
                and not _looks_like_data_row(rendered[cursor])
                and _rows_are_close(row_list[cursor - 1], row_list[cursor])
            ):
                paragraph = _join_wrapped_line(paragraph, rendered[cursor])
                cursor += 1
            lines.append(paragraph)
            continue
        lines.append(line)
        cursor += 1
    return lines


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
    markers = [cell.text.upper() for cell in row.cells]
    matches = sum(any(marker in text for marker in _PARTY_HEADING_MARKERS) for text in markers)
    return matches >= 2 and row.cells[-1].x0 - row.cells[0].x0 >= 0.25


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


def _render_metadata(rows: Sequence[ReadingRow]) -> list[list[str]]:
    lines = [part for row in rows for part in _split_paired_labels(_row_text(row))]
    if not lines:
        return []
    has_offer = any(
        line.casefold().startswith(("angebot", "datum:", "bauvorhaben:"))
        for line in lines
    )
    if has_offer:
        return [["ANGEBOT", *lines]]
    return [lines]


def _is_table_header(cells: Sequence[ReadingCell]) -> bool:
    if len(cells) < 3:
        return False
    texts = [_normalized_header_text(cell.text) for cell in cells]
    if not texts[0].startswith(_TABLE_HEADER_LEADERS):
        return False
    marker_count = sum(any(marker in text for marker in _TABLE_HEADER_MARKERS) for text in texts)
    return marker_count >= min(3, len(texts))


def _normalized_header_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().strip().rstrip(":"))


def _table_section_heading(header: ReadingRow) -> str | None:
    first = _normalized_header_text(header.cells[0].text)
    return "LEISTUNGEN" if first.startswith("pos") and len(header.cells) >= 5 else None


def _render_table(rows: Sequence[ReadingRow], start: int) -> tuple[list[str], int]:
    header = rows[start]
    if len(header.cells) < 3:
        return [], start
    column_x = [cell.x0 for cell in header.cells]
    aligned_rows = [_align_table_cells(header, column_x)]
    end = start + 1
    while end < len(rows):
        aligned, occupied = _align_table_cells_with_occupied(rows[end], column_x)
        if len(occupied) >= min(3, len(column_x)):
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
    return [" | ".join(cells) for cells in aligned_rows], end


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
    return len(line) >= 60 and not _starts_new_post_block(line) and not _looks_like_data_row(line)


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
    match = _PAGE_NUMBER_SUFFIX_RE.search(stripped)
    if match is None:
        return stripped
    prefix = stripped[: match.start()].rstrip(" |,;-")
    return prefix if len(prefix) > 40 else None


def _split_paired_labels(line: str) -> list[str]:
    return [part.strip() for part in _PAIRED_LABEL_RE.split(line) if part.strip()]


def _join_blocks(blocks: Sequence[Sequence[str]]) -> str:
    return "\n\n".join("\n".join(line for line in block if line) for block in blocks if block)


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
