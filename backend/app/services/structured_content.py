"""Conservative OCR/Text L11 table, form-field, and section reconstruction.

The extractor only adds references into immutable canonical/page text. It never rewrites text,
feeds PII, logs source values, or creates pseudonymized/redacted output. Deterministic patterns are
deliberately narrow: uncertain structures are omitted or marked partial instead of being invented.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.schemas import (
    LayoutBlock,
    StructuredBounds,
    StructuredContent,
    StructuredContentSummary,
    StructuredField,
    StructuredPageContent,
    StructuredSection,
    StructuredSpan,
    StructuredTable,
    StructuredTableCell,
    TextGeometry,
    TextPageResult,
)
from app.services.text_geometry import resolve_span_geometry

_StructureSource = Literal["layout_blocks", "text_geometry", "canonical_text", "hybrid"]
_COMMON_LABEL_HINTS: dict[str, str] = {
    "name": "person_name",
    "patient": "person_name",
    "arzt": "person_name",
    "firma": "company",
    "company": "company",
    "adresse": "address",
    "anschrift": "address",
    "address": "address",
    "iban": "iban",
    "vertragsnummer": "contract_id",
    "contract number": "contract_id",
    "aktenzeichen": "contract_id",
    "rechnungsnummer": "invoice_id",
    "invoice number": "invoice_id",
    "kundennummer": "customer_id",
    "customer number": "customer_id",
    "versicherungsnummer": "customer_id",
    "geburtsdatum": "date",
    "datum": "date",
    "date": "date",
    "telefon": "phone",
    "phone": "phone",
    "e-mail": "email",
    "email": "email",
    "bic": "unknown",
    "steuernummer": "unknown",
    "uid": "unknown",
}
_LABEL_CHARS = re.compile(r"^[^\W\d_][\wÄÖÜäöüß .()/&-]{0,78}$", re.UNICODE)
_INLINE_FIELD = re.compile(
    r"^(?P<label>[^:\n]{1,80}?)(?P<separator>\s*:\s*|\s+-\s+)(?P<value>\S.*)$"
)
_MULTISPACE_FIELD = re.compile(r"^(?P<label>\S(?:.*?\S)?) {2,}(?P<value>\S.*)$")
_MULTISPACE_SEPARATOR = re.compile(r" {2,}")
# OCR/Text L13: how many extra lines a field value may absorb when a value wraps onto more than
# one line (e.g. a multiline address). Bounded so an unrelated following line cannot be swept in.
_MAX_FIELD_VALUE_CONTINUATION_LINES = 3


@dataclass(frozen=True)
class _Line:
    text: str
    page_start: int
    page_end: int
    canonical_start: int
    canonical_end: int


@dataclass(frozen=True)
class _CellDraft:
    page_start: int
    page_end: int


@dataclass(frozen=True)
class _RowDraft:
    line: _Line
    delimiter: str
    cells: tuple[_CellDraft, ...]


def build_structured_content(
    canonical_text: str,
    pages: list[TextPageResult],
    layout_blocks: list[LayoutBlock],
    text_geometry: TextGeometry | None,
) -> StructuredContent | None:
    """Build additive structure for physical pages or one logical DOCX page."""
    inputs: list[tuple[int, str, int]] = []
    if pages:
        canonical_base = 0
        for page in pages:
            inputs.append((page.page_number, page.text, canonical_base))
            canonical_base += len(page.text) + 2
    elif canonical_text:
        inputs.append((1, canonical_text, 0))

    structured_pages: list[StructuredPageContent] = []
    for page_number, page_text, canonical_base in inputs:
        lines = _lines(page_text, canonical_base)
        page_blocks = [block for block in layout_blocks if block.page_number == page_number]
        fields = _detect_fields(page_number, lines, text_geometry)
        tables = _detect_tables(page_number, lines, canonical_base, text_geometry)
        sections = _detect_sections(
            page_number,
            lines,
            fields,
            tables,
            page_blocks,
            canonical_base,
            text_geometry,
        )
        if not fields and not tables and not sections:
            continue
        flags: list[str] = []
        if any("partial_table" in table.flags for table in tables):
            flags.append("partial_table_structure")
        if text_geometry is None:
            flags.append("geometry_unavailable")
        sources = {
            *(field.source for field in fields),
            *(table.source for table in tables),
            *(section.source for section in sections),
        }
        source: _StructureSource = next(iter(sources)) if len(sources) == 1 else "hybrid"
        confidences = [
            *(field.confidence for field in fields),
            *(table.confidence for table in tables),
            *(section.confidence for section in sections),
        ]
        structured_pages.append(
            StructuredPageContent(
                page_number=page_number,
                tables=tables,
                fields=fields,
                sections=sections,
                source=source,
                confidence=sum(confidences) / len(confidences),
                quality_flags=flags,
            )
        )

    if not structured_pages:
        return None
    summary = StructuredContentSummary(
        page_count=len(structured_pages),
        table_count=sum(len(page.tables) for page in structured_pages),
        field_count=sum(len(page.fields) for page in structured_pages),
        section_count=sum(len(page.sections) for page in structured_pages),
    )
    flags = ["span_backed", "pii_input_unchanged"]
    if any(page.quality_flags for page in structured_pages):
        flags.append("partial_structure")
    return StructuredContent(pages=structured_pages, summary=summary, flags=flags)


def _lines(page_text: str, canonical_base: int) -> list[_Line]:
    result: list[_Line] = []
    cursor = 0
    for raw in page_text.splitlines(keepends=True):
        text = raw.rstrip("\r\n")
        end = cursor + len(text)
        result.append(
            _Line(
                text=text,
                page_start=cursor,
                page_end=end,
                canonical_start=canonical_base + cursor,
                canonical_end=canonical_base + end,
            )
        )
        cursor += len(raw)
    if page_text and (not result or cursor < len(page_text)):
        text = page_text[cursor:]
        result.append(
            _Line(
                text=text,
                page_start=cursor,
                page_end=len(page_text),
                canonical_start=canonical_base + cursor,
                canonical_end=canonical_base + len(page_text),
            )
        )
    return result


def _looks_like_value_continuation(text: str) -> bool:
    """OCR/Text L13: a following line only extends a field value when it stays value-shaped.

    A recognizable field, a heading, or a sentence ending in terminal punctuation is never
    absorbed — those are far more likely to be the start of unrelated content than a wrapped
    value line (e.g. the second line of a multiline address).
    """

    stripped = text.strip()
    if (
        not stripped
        or _INLINE_FIELD.match(stripped)
        or _MULTISPACE_FIELD.match(stripped)
        or _looks_like_heading(stripped)
        or stripped.endswith((".", "!", "?"))
    ):
        return False
    return len(stripped.split()) <= 8


def _field_value_continuation_end(lines: list[_Line], start_index: int) -> int:
    end = start_index + 1
    limit = min(len(lines), start_index + 1 + _MAX_FIELD_VALUE_CONTINUATION_LINES)
    while end < limit and _looks_like_value_continuation(lines[end].text):
        end += 1
    return end


_FieldDraft = tuple[_Line, int, int, int, int, str, float, list[str]]


def _inline_field_draft(
    index: int,
    line: _Line,
    lines: list[_Line],
    match: re.Match[str],
    confidence: float,
    flags: list[str],
) -> tuple[_FieldDraft, set[int]] | None:
    label = match.group("label").strip()
    value = match.group("value").strip()
    label_key = _label_key(label)
    if not _valid_label(label) or (
        ":" not in match.group(0) and label_key not in _COMMON_LABEL_HINTS
    ):
        return None
    stripped_offset = len(line.text) - len(line.text.lstrip())
    label_start = stripped_offset + match.start("label")
    label_end = stripped_offset + match.end("label")
    value_start = stripped_offset + match.start("value")
    value_end = value_start + len(value)
    consumed: set[int] = set()
    # OCR/Text L13: an inline label/value line may still wrap onto following lines (e.g. a
    # multiline address after "Adresse: Hauptstraße 1"). Only absorb lines that read as a plain
    # value continuation, never another recognizable field or heading.
    cont_end = _field_value_continuation_end(lines, index)
    if cont_end > index + 1:
        last_line = lines[cont_end - 1]
        last_value = last_line.text.strip()
        value_end = (
            last_line.page_start
            - line.page_start
            + last_line.text.index(last_value)
            + len(last_value)
        )
        flags = [*flags, "multiline_value"]
        consumed = set(range(index + 1, cont_end))
    draft: _FieldDraft = (
        line, label_start, label_end, value_start, value_end, label, confidence, flags
    )
    return draft, consumed


def _next_line_field_draft(
    index: int, line: _Line, lines: list[_Line]
) -> tuple[_FieldDraft, set[int]] | None:
    label = line.text.strip().rstrip(":").strip()
    if _label_key(label) not in _COMMON_LABEL_HINTS or not _valid_label(label):
        return None
    next_index = index + 1
    if next_index >= len(lines):
        return None
    value_line = lines[next_index]
    value = value_line.text.strip()
    if not value or _looks_like_heading(value) or _INLINE_FIELD.match(value):
        return None
    label_start = line.text.index(label)
    value_start = value_line.text.index(value)
    field_confidence = 0.7
    field_flags = ["value_on_next_line"]
    value_end_index = next_index + 1
    # OCR/Text L13: a value placed on the line below its label may itself span several lines
    # (e.g. a wrapped multiline address); extend through following plain continuation lines.
    cont_end = _field_value_continuation_end(lines, next_index)
    if cont_end > value_end_index:
        value_end_index = cont_end
        field_confidence = 0.6
        field_flags = [*field_flags, "multiline_value"]
    last_line = lines[value_end_index - 1]
    last_value = last_line.text.strip()
    value_end = (
        last_line.page_start
        - line.page_start
        + last_line.text.index(last_value)
        + len(last_value)
    )
    draft: _FieldDraft = (
        line,
        label_start,
        label_start + len(label),
        value_line.page_start - line.page_start + value_start,
        value_end,
        label,
        field_confidence,
        field_flags,
    )
    return draft, set(range(next_index, value_end_index))


def _detect_fields(
    page_number: int, lines: list[_Line], text_geometry: TextGeometry | None
) -> list[StructuredField]:
    drafts: list[_FieldDraft] = []
    consumed_value_lines: set[int] = set()
    for index, line in enumerate(lines):
        if index in consumed_value_lines or not line.text.strip():
            continue
        stripped = line.text.strip()
        match = _INLINE_FIELD.match(stripped)
        confidence = 0.9
        flags: list[str] = []
        if match is None:
            match = _MULTISPACE_FIELD.match(stripped)
            confidence = 0.78
            flags = ["aligned_text_pair"]
        if match is not None:
            result = _inline_field_draft(index, line, lines, match, confidence, flags)
            if result is not None:
                drafts.append(result[0])
                consumed_value_lines.update(result[1])
            continue

        result = _next_line_field_draft(index, line, lines)
        if result is not None:
            drafts.append(result[0])
            consumed_value_lines.update(result[1])

    fields: list[StructuredField] = []
    for field_index, draft in enumerate(drafts, start=1):
        line, label_start, label_end, value_start, value_end, label, confidence, flags = draft
        canonical_base = line.canonical_start - line.page_start
        label_span = _span(
            canonical_base, line.page_start + label_start, line.page_start + label_end
        )
        value_span = _span(
            canonical_base, line.page_start + value_start, line.page_start + value_end
        )
        bounds = _bounds_for_span(
            text_geometry, label_span.canonical_start, value_span.canonical_end
        )
        source: _StructureSource = "hybrid" if bounds is not None else "canonical_text"
        fields.append(
            StructuredField(
                field_id=f"field-p{page_number}-{field_index}",
                page_number=page_number,
                label=label,
                label_span=label_span,
                value_span=value_span,
                bounds=bounds,
                field_type_hint=_COMMON_LABEL_HINTS.get(_label_key(label), "unknown"),
                confidence=confidence,
                source=source,
                flags=flags,
            )
        )
    return fields


def _detect_tables(
    page_number: int,
    lines: list[_Line],
    canonical_base: int,
    text_geometry: TextGeometry | None,
) -> list[StructuredTable]:
    rows = [_parse_row(line) for line in lines]
    groups: list[list[_RowDraft]] = []
    current: list[_RowDraft] = []
    for row in rows:
        if row is not None and (not current or row.delimiter == current[-1].delimiter):
            current.append(row)
            continue
        if current:
            groups.append(current)
        current = [row] if row is not None else []
    if current:
        groups.append(current)

    tables: list[StructuredTable] = []
    for group in groups:
        if len(group) < 2 or (group[0].delimiter == "semicolon" and len(group) < 3):
            continue
        counts = [len(row.cells) for row in group]
        if min(counts) < 2:
            continue
        partial = len(set(counts)) > 1
        column_count = max(counts)
        cells: list[StructuredTableCell] = []
        first_row_header = _header_like(group[0].line.text)
        for row_index, row in enumerate(group):
            for column_index, cell in enumerate(row.cells):
                span = _span(canonical_base, cell.page_start, cell.page_end)
                cells.append(
                    StructuredTableCell(
                        row_index=row_index,
                        column_index=column_index,
                        span=span,
                        bounds=_bounds_for_span(
                            text_geometry, span.canonical_start, span.canonical_end
                        ),
                        role="header" if row_index == 0 and first_row_header else "data",
                    )
                )
        table_start = min(cell.span.canonical_start for cell in cells)
        table_end = max(cell.span.canonical_end for cell in cells)
        bounds = _bounds_for_span(text_geometry, table_start, table_end)
        flags = ["partial_table", "inconsistent_column_count"] if partial else []
        tables.append(
            StructuredTable(
                table_id=f"table-p{page_number}-{len(tables) + 1}",
                page_number=page_number,
                row_count=len(group),
                column_count=column_count,
                cells=cells,
                bounds=bounds,
                source="hybrid" if bounds is not None else "canonical_text",
                confidence=0.62 if partial else 0.86,
                flags=flags,
            )
        )
    return tables


def _parse_row(line: _Line) -> _RowDraft | None:
    if not line.text.strip():
        return None
    delimiter: str
    separator: re.Pattern[str]
    if "|" in line.text:
        delimiter, separator = "pipe", re.compile(r"\|")
    elif "\t" in line.text:
        delimiter, separator = "tab", re.compile(r"\t+")
    elif ";" in line.text:
        delimiter, separator = "semicolon", re.compile(r";")
    elif _MULTISPACE_SEPARATOR.search(line.text):
        delimiter, separator = "multi_space", _MULTISPACE_SEPARATOR
    else:
        return None
    cells: list[_CellDraft] = []
    cursor = 0
    for match in separator.finditer(line.text):
        cell = _trimmed_cell(line, cursor, match.start())
        if cell is not None:
            cells.append(cell)
        cursor = match.end()
    cell = _trimmed_cell(line, cursor, len(line.text))
    if cell is not None:
        cells.append(cell)
    if len(cells) < 2:
        return None
    return _RowDraft(line=line, delimiter=delimiter, cells=tuple(cells))


def _trimmed_cell(line: _Line, start: int, end: int) -> _CellDraft | None:
    raw = line.text[start:end]
    trimmed = raw.strip()
    if not trimmed or set(trimmed) <= {"-", "=", ":"}:
        return None
    local_start = start + len(raw) - len(raw.lstrip())
    return _CellDraft(
        page_start=line.page_start + local_start,
        page_end=line.page_start + local_start + len(trimmed),
    )


def _detect_sections(
    page_number: int,
    lines: list[_Line],
    fields: list[StructuredField],
    tables: list[StructuredTable],
    layout_blocks: list[LayoutBlock],
    canonical_base: int,
    text_geometry: TextGeometry | None,
) -> list[StructuredSection]:
    structures: list[tuple[int, int, str]] = [
        *(
            (field.label_span.page_start, field.value_span.page_end, field.field_id)
            for field in fields
        ),
        *(
            (
                min(cell.span.page_start for cell in table.cells),
                max(cell.span.page_end for cell in table.cells),
                table.table_id,
            )
            for table in tables
            if table.cells
        ),
    ]
    if not structures:
        return []
    block_headings = {
        " ".join(block.text.split())
        for block in layout_blocks
        if block.block_type == "heading"
    }
    heading_lines = [
        line
        for line in lines
        if line.text.strip()
        and (
            _looks_like_heading(line.text.strip())
            or " ".join(line.text.split()) in block_headings
        )
    ]
    sections: list[StructuredSection] = []
    for heading in heading_lines:
        following = [item for item in structures if item[0] > heading.page_end]
        if not following:
            continue
        next_heading_start = min(
            (line.page_start for line in heading_lines if line.page_start > heading.page_start),
            default=10**12,
        )
        contained = [item for item in following if item[0] < next_heading_start]
        if not contained:
            continue
        heading_text = heading.text.strip().rstrip(":")
        heading_start = heading.page_start + heading.text.index(heading.text.strip())
        heading_span = _span(canonical_base, heading_start, heading_start + len(heading_text))
        section_end = max(item[1] for item in contained)
        section_span = _span(canonical_base, heading_start, section_end)
        ids = [item[2] for item in contained]
        has_layout_heading = " ".join(heading.text.split()) in block_headings
        bounds = _bounds_for_span(
            text_geometry, section_span.canonical_start, section_span.canonical_end
        )
        source: _StructureSource
        if has_layout_heading and bounds is not None:
            source = "hybrid"
        elif has_layout_heading:
            source = "layout_blocks"
        elif bounds is not None:
            source = "hybrid"
        else:
            source = "canonical_text"
        sections.append(
            StructuredSection(
                section_id=f"section-p{page_number}-{len(sections) + 1}",
                page_number=page_number,
                heading=heading_text,
                heading_span=heading_span,
                span=section_span,
                field_ids=[item_id for item_id in ids if item_id.startswith("field-")],
                table_ids=[item_id for item_id in ids if item_id.startswith("table-")],
                source=source,
                confidence=0.88 if has_layout_heading else 0.72,
            )
        )
    return sections


def _span(canonical_base: int, page_start: int, page_end: int) -> StructuredSpan:
    return StructuredSpan(
        canonical_start=canonical_base + page_start,
        canonical_end=canonical_base + page_end,
        page_start=page_start,
        page_end=page_end,
    )


def _bounds_for_span(
    text_geometry: TextGeometry | None, canonical_start: int, canonical_end: int
) -> StructuredBounds | None:
    boxes = resolve_span_geometry(text_geometry, canonical_start, canonical_end)
    if not boxes or len({box.coordinate_unit for box in boxes}) != 1:
        return None
    return StructuredBounds(
        x0=min(box.x0 for box in boxes),
        y0=min(box.y0 for box in boxes),
        x1=max(box.x1 for box in boxes),
        y1=max(box.y1 for box in boxes),
        coordinate_unit=boxes[0].coordinate_unit,
    )


def _label_key(label: str) -> str:
    normalized = unicodedata.normalize("NFKC", label).casefold().strip().rstrip(":")
    return " ".join(normalized.split())


def _valid_label(label: str) -> bool:
    return bool(_LABEL_CHARS.fullmatch(label)) and len(label.split()) <= 6


def _looks_like_heading(text: str) -> bool:
    stripped = text.strip().rstrip(":")
    if not stripped or len(stripped) > 80 or any(char in stripped for char in ":|;\t"):
        return False
    words = stripped.split()
    if len(words) > 8 or any(char.isdigit() for char in stripped):
        return False
    letters = [char for char in stripped if char.isalpha()]
    return bool(letters) and (
        stripped.isupper()
        or (len(words) <= 5 and all(word[:1].isupper() for word in words if word))
    )


def _header_like(text: str) -> bool:
    cells = [part.strip() for part in re.split(r"\||\t+|;| {2,}", text) if part.strip()]
    return bool(cells) and all(any(char.isalpha() for char in cell) for cell in cells)
