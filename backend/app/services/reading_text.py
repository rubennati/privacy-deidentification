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
_TABLE_HEADER_TOKENS = ("Pos.", "Leistung", "Menge", "Einheit", "Einzelpreis", "Gesamt")
_PARTY_HEADING_MARKERS = (
    "AUFTRAGNEHMER",
    "AUFTRAGGEBER",
    "RECHNUNGSSTELLER",
    "RECHNUNGSEMPFÄNGER",
    "KUNDE",
    "LIEFERANT",
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
_TOTAL_PREFIXES = (
    "zwischensumme",
    "nettosumme",
    "ust ",
    "mwst ",
    "gesamtbetrag",
    "gesamtsumme",
)
_PARAGRAPH_PREFIXES = ("zahlungsbedingungen:", "zahlbar ", "dieses angebot")
_PAIRED_LABEL_RE = re.compile(
    r"(?=\s+(?:Datum|Bauvorhaben|Projekt|Angebot\s+Nr\.|Angebotsnummer|Rechnungsnummer)\s*:)",
    re.IGNORECASE,
)
_NUMERIC_ROW_RE = re.compile(r"^\d+[.)]?$|^\d+(?:[.,]\d+)?$")


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


def _render_positioned_rows(rows: Sequence[ReadingRow]) -> tuple[list[list[str]], list[str]]:
    ordered = sorted(rows, key=lambda row: (row.y0, row.cells[0].x0))
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
                if _row_has_prefix(row, _METADATA_PREFIXES)
            ),
            0,
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
            blocks.append(["LEISTUNGEN", *table_block])
            flags.extend(("table_row_reconstruction", "document_sections"))
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
    blocks: list[list[str]] = [[]]
    heights = [max(0.001, row.y1 - row.y0) for row in rows]
    gap_limit = median(heights) * 2.2
    previous: ReadingRow | None = None
    for row in rows:
        if previous is not None and row.y0 - previous.y1 > gap_limit:
            blocks.append([])
        blocks[-1].append(_row_text(row))
        previous = row
    return [block for block in blocks if block]


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
    texts = {cell.text.strip() for cell in cells}
    return sum(token in texts for token in _TABLE_HEADER_TOKENS) >= 4


def _render_table(rows: Sequence[ReadingRow], start: int) -> tuple[list[str], int]:
    header = rows[start]
    if len(header.cells) < 4:
        return [], start
    column_x = [cell.x0 for cell in header.cells]
    rendered = [_align_table_row(header, column_x)]
    end = start + 1
    while end < len(rows):
        first_text = rows[end].cells[0].text.strip() if rows[end].cells else ""
        if not _NUMERIC_ROW_RE.fullmatch(first_text):
            break
        rendered.append(_align_table_row(rows[end], column_x))
        end += 1
    return rendered, end


def _align_table_row(row: ReadingRow, column_x: Sequence[float]) -> str:
    cells = [""] * len(column_x)
    for fragment in row.cells:
        nearest = min(range(len(column_x)), key=lambda index: abs(column_x[index] - fragment.x0))
        cells[nearest] = f"{cells[nearest]} {fragment.text}".strip()
    return " | ".join(cells)


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
        blocks.append([line])
        cursor += 1
    return blocks, flags


def _starts_new_post_block(line: str) -> bool:
    folded = line.casefold()
    return folded.startswith(("sachbearbeiter:", "ansprechpartner:", *_TOTAL_PREFIXES))


def _row_has_prefix(row: ReadingRow, prefixes: Sequence[str]) -> bool:
    return any(cell.text.casefold().startswith(tuple(prefixes)) for cell in row.cells)


def _row_text(row: ReadingRow) -> str:
    return " ".join(cell.text for cell in row.cells).strip()


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
