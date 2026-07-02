"""Semantic reading-order reconstruction for PDF text-layer pages (OCR L9 slice, PII-input v1).

Builds ``pii_input_text``: an internal, additive text view that groups two-column blocks and
reconstructs table rows using the position data pypdf already computes while walking a page's
content stream (via ``extract_text(visitor_operand_before=...)``). It relies entirely on pypdf's own
content-stream interpreter for operator semantics (``Td``/``TD``/``Tm``/``T*`` etc.) and only reads
the resulting text matrix at each ``Tj``/``TJ`` draw operation — no bespoke PDF parsing.

This is **not** the active PII detection input. PII continues to run on canonical text
(`text_result.text`); this field is internal and not displayed in the UI. See
docs/engine/ocr-layout-text-contract.md for the full contract and the separation rule that must
hold before `pii_input_text` may ever diverge from canonical as a real detection input.

Deliberately narrow and heuristic, matching the "small, deterministic, bounded" principle in
AGENTS.md:

- Block boundaries are **geometric** (left column / right column), not semantic role labels
  (e.g. it never claims to know which side is a "contractor" vs. a "customer").
- The table heuristic recognises exactly one known header-token set and treats every line after it
  as a table row through the end of the page — not a general table detector.
- Any page where fragment positions cannot be collected or grouped confidently returns ``None`` so
  the caller falls back to that page's canonical text with a marker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pypdf import PageObject

_COLUMN_GAP_POINTS = 100.0
_COLUMN_STABILITY_POINTS = 20.0
_LINE_Y_TOLERANCE_POINTS = 3.0
_MIN_TWO_COLUMN_LINES = 2

_TABLE_HEADER_TOKENS = ("Pos.", "Leistung", "Menge", "Einheit", "Einzelpreis", "Gesamt")
_MIN_TABLE_HEADER_MATCHES = 4


@dataclass(frozen=True)
class _Fragment:
    """One drawn text run and its absolute page position (PDF points, origin bottom-left)."""

    text: str
    x: float
    y: float


def build_page_pii_input_text(page: PageObject) -> str | None:
    """Best-effort semantic grouping for one PDF text-layer page.

    Returns ``None`` when fragments cannot be collected or no content is found, so callers fall
    back to the page's canonical text.
    """
    try:
        fragments = _collect_fragments(page)
        if not fragments:
            return None
        lines = _group_into_lines(fragments)
        rendered = _render_lines(lines)
    except Exception:
        return None
    return rendered or None


def _collect_fragments(page: PageObject) -> list[_Fragment]:
    fragments: list[_Fragment] = []

    def visitor(operator: Any, operands: Any, _cm: Any, tm: Any) -> None:
        if operator not in (b"Tj", b"TJ") or tm is None:
            return
        if not isinstance(operands, (list, tuple)) or not operands:
            return
        text = _decode_operand(operands[0])
        if text.strip():
            fragments.append(_Fragment(text=text, x=float(tm[4]), y=float(tm[5])))

    page.extract_text(visitor_operand_before=visitor)
    return fragments


def _decode_operand(operand: object) -> str:
    """Decode a ``Tj``/``TJ`` operand into drawn text, ignoring ``TJ`` kerning numbers."""
    if isinstance(operand, (bytes, bytearray)):
        return bytes(operand).decode("latin-1", errors="replace")
    if isinstance(operand, (list, tuple)):
        pieces = [bytes(item) for item in operand if isinstance(item, (bytes, bytearray))]
        return b"".join(pieces).decode("latin-1", errors="replace")
    return ""


def _group_into_lines(fragments: list[_Fragment]) -> list[list[_Fragment]]:
    """Group fragments into reading-order lines (PDF y grows upward; top of page first)."""
    ordered = sorted(fragments, key=lambda fragment: (-fragment.y, fragment.x))
    lines: list[list[_Fragment]] = []
    for fragment in ordered:
        if lines and abs(lines[-1][0].y - fragment.y) <= _LINE_Y_TOLERANCE_POINTS:
            lines[-1].append(fragment)
        else:
            lines.append([fragment])
    for line in lines:
        line.sort(key=lambda fragment: fragment.x)
    return lines


def _render_lines(lines: list[list[_Fragment]]) -> str:
    table_start = next(
        (index for index, line in enumerate(lines) if _is_table_header_line(line)), None
    )
    body_lines = lines if table_start is None else lines[:table_start]
    table_lines = [] if table_start is None else lines[table_start:]

    blocks = _render_body(body_lines)
    if table_lines:
        blocks.append(_render_table(table_lines))
    return "\n\n".join(block for block in blocks if block)


def _is_table_header_line(line: list[_Fragment]) -> bool:
    texts = {fragment.text.strip() for fragment in line}
    return sum(1 for token in _TABLE_HEADER_TOKENS if token in texts) >= _MIN_TABLE_HEADER_MATCHES


def _render_body(lines: list[list[_Fragment]]) -> list[str]:
    """Render non-table lines: grouped left/right blocks where a stable two-column split exists,
    otherwise plain top-to-bottom lines."""
    boundary = _detect_column_boundary(lines)
    if boundary is None:
        return ["\n".join(_join_line(line) for line in lines if line)]
    left = [fragment for line in lines for fragment in line if fragment.x < boundary]
    right = [fragment for line in lines for fragment in line if fragment.x >= boundary]
    blocks: list[str] = []
    if left:
        blocks.append("[BLOCK: left]\n" + "\n".join(fragment.text.strip() for fragment in left))
    if right:
        blocks.append("[BLOCK: right]\n" + "\n".join(fragment.text.strip() for fragment in right))
    return blocks


def _detect_column_boundary(lines: list[list[_Fragment]]) -> float | None:
    """Return an x boundary separating a stable two-column layout, or ``None`` if not detected.

    A line qualifies when it has a fragment at least ``_COLUMN_GAP_POINTS`` to the right of its
    first fragment. The boundary is only accepted when at least ``_MIN_TWO_COLUMN_LINES`` qualify
    and both the left- and right-column start positions are stable (within
    ``_COLUMN_STABILITY_POINTS``) across those lines.
    """
    left_starts: list[float] = []
    right_starts: list[float] = []
    for line in lines:
        if len(line) < 2:
            continue
        left_x = line[0].x
        right_fragment = next(
            (fragment for fragment in line[1:] if fragment.x - left_x >= _COLUMN_GAP_POINTS),
            None,
        )
        if right_fragment is None:
            continue
        left_starts.append(left_x)
        right_starts.append(right_fragment.x)
    if len(left_starts) < _MIN_TWO_COLUMN_LINES:
        return None
    if max(left_starts) - min(left_starts) > _COLUMN_STABILITY_POINTS:
        return None
    if max(right_starts) - min(right_starts) > _COLUMN_STABILITY_POINTS:
        return None
    return (sum(left_starts) / len(left_starts) + sum(right_starts) / len(right_starts)) / 2


def _render_table(lines: list[list[_Fragment]]) -> str:
    """Render the detected header line and every following line as row-wise table cells.

    Narrow by design: everything from the header line to the end of the page is treated as table
    content (no table-end detection) — sufficient for a bounded v1 heuristic, not a table engine.
    """
    header = lines[0]
    column_x = [fragment.x for fragment in header]
    rows = [_align_to_columns(line, column_x) for line in lines]
    return "[TABLE]\n" + "\n".join(" | ".join(cell) for cell in rows)


def _align_to_columns(line: list[_Fragment], column_x: list[float]) -> list[str]:
    cells = [""] * len(column_x)
    for fragment in line:
        nearest = min(range(len(column_x)), key=lambda index: abs(column_x[index] - fragment.x))
        cells[nearest] = (
            f"{cells[nearest]} {fragment.text}".strip() if cells[nearest] else fragment.text
        )
    return cells


def _join_line(line: list[_Fragment]) -> str:
    return " ".join(fragment.text.strip() for fragment in line)
