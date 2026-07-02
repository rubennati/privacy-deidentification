"""Deterministic OCR L9 coarse layout blocks.

The builder uses positions already reported by pypdf or PaddleOCR. It intentionally stores only
page-relative block regions used for reading order and conservative display typing. It does not
produce canonical offsets, reusable line/word boxes, semantic roles, or table/form structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

from pypdf import PageObject

from app.schemas import LayoutBlock
from app.services.ocr_adapters import OcrExtractionResult

_LINE_MIN_TOLERANCE = 0.004
_BAND_MIN_GAP = 0.025
_COLUMN_GAP = 0.3
_COLUMN_STABILITY = 0.08


@dataclass(frozen=True)
class _Fragment:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    source: Literal["pdf_text_layer", "paddleocr"]
    confidence: float | None = None


@dataclass(frozen=True)
class _Line:
    fragments: tuple[_Fragment, ...]

    @property
    def y0(self) -> float:
        return min(fragment.y0 for fragment in self.fragments)

    @property
    def y1(self) -> float:
        return max(fragment.y1 for fragment in self.fragments)


@dataclass(frozen=True)
class _BlockDraft:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    source: Literal["pdf_text_layer", "paddleocr"]
    confidence: float | None


@dataclass
class _PdfTextState:
    """Minimal text-position state layered on pypdf's decoded visitor callbacks.

    Tracking line movement here avoids a pypdf visitor-matrix scaling issue for repeated ``T*``
    operations while leaving content parsing and text decoding to pypdf.
    """

    current_font_size: float = 10.0
    leading: float = 0.0
    line_x: float = 0.0
    line_y: float = 0.0
    text_x: float = 0.0
    text_y: float = 0.0
    pending: tuple[float, float, tuple[float, ...]] | None = None

    def visit_operand(self, operator: Any, operands: Any, cm: Any, _tm: Any) -> None:
        values = operands if isinstance(operands, (list, tuple)) else []
        if operator == b"BT":
            self.line_x = self.line_y = self.text_x = self.text_y = 0.0
            self.pending = None
        elif operator == b"Tf" and len(values) >= 2:
            self._set_font_size(values[1])
        elif operator == b"TL" and values:
            self.leading = float(values[0])
        elif operator == b"Tm" and len(values) >= 6:
            self.line_x = self.text_x = float(values[4])
            self.line_y = self.text_y = float(values[5])
        elif operator in (b"Td", b"TD") and len(values) >= 2:
            self._move_line(float(values[0]), float(values[1]), operator == b"TD")
        elif operator == b"T*":
            self.line_y -= self.leading
            self.text_x, self.text_y = self.line_x, self.line_y
        elif operator in (b"Tj", b"TJ") and cm is not None:
            self.pending = (
                self.text_x,
                self.text_y,
                tuple(float(value) for value in cm),
            )

    def _set_font_size(self, value: object) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0:
            self.current_font_size = float(value)

    def _move_line(self, x: float, y: float, sets_leading: bool) -> None:
        self.line_x += x
        self.line_y += y
        self.text_x, self.text_y = self.line_x, self.line_y
        if sets_leading:
            self.leading = -y


def build_pdf_layout_blocks(
    page: PageObject, page_number: int, fallback_text: str
) -> list[LayoutBlock]:
    """Build coarse ordered blocks from one PDF text-layer page."""
    try:
        fragments = _collect_pdf_fragments(page)
        if fragments:
            return _build_blocks(fragments, page_number)
    except Exception:
        pass
    return build_fallback_layout_blocks(fallback_text, page_number)


def build_ocr_layout_blocks(
    result: OcrExtractionResult, page_number: int
) -> list[LayoutBlock]:
    """Build coarse blocks from transient OCR polygons, or one explicit fallback block."""
    if result.image_width and result.image_height and result.layout_lines:
        fragments: list[_Fragment] = []
        for line in result.layout_lines:
            xs = [point[0] for point in line.polygon]
            ys = [point[1] for point in line.polygon]
            x0 = _clamp(min(xs) / result.image_width)
            y0 = _clamp(min(ys) / result.image_height)
            x1 = _clamp(max(xs) / result.image_width)
            y1 = _clamp(max(ys) / result.image_height)
            if x1 <= x0 or y1 <= y0:
                continue
            fragments.append(
                _Fragment(
                    text=line.text.strip(),
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    font_size=max(1.0, max(ys) - min(ys)),
                    source="paddleocr",
                    confidence=line.confidence,
                )
            )
        if fragments:
            return _build_blocks(fragments, page_number)
    return build_fallback_layout_blocks(result.text, page_number)


def build_fallback_layout_blocks(text: str, page_number: int = 1) -> list[LayoutBlock]:
    """Represent non-empty text with one explicitly non-geometric fallback block."""
    stripped = text.strip()
    if not stripped:
        return []
    return [
        LayoutBlock(
            page_number=page_number,
            order=1,
            block_type="fallback",
            text=stripped,
            x0=0.0,
            y0=0.0,
            x1=1.0,
            y1=1.0,
            source="fallback",
        )
    ]


def _collect_pdf_fragments(page: PageObject) -> list[_Fragment]:
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    left = float(page.mediabox.left)
    bottom = float(page.mediabox.bottom)
    if width <= 0.0 or height <= 0.0:
        return []
    fragments: list[_Fragment] = []
    state = _PdfTextState()

    def visitor_text(text: str, _cm: Any, _tm: Any, _font: Any, font_size: float) -> None:
        text = text.strip()
        if state.pending is None:
            return
        x_text, y_text, cm = state.pending
        state.pending = None
        if not text:
            return
        size = float(font_size) if font_size > 0 else state.current_font_size
        x, y = _transform_point(x_text, y_text, cm)
        x -= left
        y -= bottom
        estimated_width = min(
            width - x,
            max(size * 0.5, len(text) * size * 0.52),
        )
        x0 = _clamp(x / width)
        x1 = _clamp((x + estimated_width) / width)
        y0 = _clamp((height - y - size) / height)
        y1 = _clamp((height - y + size * 0.2) / height)
        if x1 <= x0 or y1 <= y0:
            return
        fragments.append(
            _Fragment(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                font_size=size,
                source="pdf_text_layer",
            )
        )

    page.extract_text(visitor_operand_before=state.visit_operand, visitor_text=visitor_text)
    return fragments


def _build_blocks(fragments: list[_Fragment], page_number: int) -> list[LayoutBlock]:
    lines = _group_lines(fragments)
    bands = _group_bands(lines)
    drafts: list[_BlockDraft] = []
    for band in bands:
        drafts.extend(_drafts_for_band(band))
    median_font_size = median(fragment.font_size for fragment in fragments)
    return [
        LayoutBlock(
            page_number=page_number,
            order=order,
            block_type=_classify(draft, median_font_size),
            text=draft.text,
            x0=draft.x0,
            y0=draft.y0,
            x1=draft.x1,
            y1=draft.y1,
            source=draft.source,
            confidence=draft.confidence,
        )
        for order, draft in enumerate(drafts, start=1)
    ]


def _group_lines(fragments: list[_Fragment]) -> list[_Line]:
    typical_height = median(fragment.y1 - fragment.y0 for fragment in fragments)
    tolerance = max(_LINE_MIN_TOLERANCE, typical_height * 0.6)
    grouped: list[list[_Fragment]] = []
    for fragment in sorted(fragments, key=lambda item: ((item.y0 + item.y1) / 2, item.x0)):
        center = (fragment.y0 + fragment.y1) / 2
        if grouped:
            previous_center = sum(
                (item.y0 + item.y1) / 2 for item in grouped[-1]
            ) / len(grouped[-1])
            if abs(previous_center - center) <= tolerance:
                grouped[-1].append(fragment)
                continue
        grouped.append([fragment])
    return [_Line(tuple(sorted(group, key=lambda item: item.x0))) for group in grouped]


def _group_bands(lines: list[_Line]) -> list[list[_Line]]:
    if not lines:
        return []
    typical_height = median(line.y1 - line.y0 for line in lines)
    gap_limit = max(_BAND_MIN_GAP, typical_height * 1.8)
    bands: list[list[_Line]] = [[lines[0]]]
    for line in lines[1:]:
        if line.y0 - bands[-1][-1].y1 > gap_limit:
            bands.append([line])
        else:
            bands[-1].append(line)
    return bands


def _drafts_for_band(lines: list[_Line]) -> list[_BlockDraft]:
    region = _two_column_region(lines)
    if region is not None:
        start, end, boundary = region
        drafts = _line_drafts(lines[:start])
        column_lines = lines[start:end]
        left = [
            fragment
            for line in column_lines
            for fragment in line.fragments
            if fragment.x0 < boundary
        ]
        right = [
            fragment
            for line in column_lines
            for fragment in line.fragments
            if fragment.x0 >= boundary
        ]
        drafts.extend(_draft_from_fragments(group) for group in (left, right) if group)
        drafts.extend(_line_drafts(lines[end:]))
        return drafts
    return _line_drafts(lines)


def _line_drafts(lines: list[_Line]) -> list[_BlockDraft]:
    return _merge_adjacent_drafts(
        [_draft_from_fragments(list(line.fragments)) for line in lines]
    )


def _two_column_region(lines: list[_Line]) -> tuple[int, int, float] | None:
    """Find one stable contiguous two-column run without swallowing titles/tables around it."""
    runs: list[tuple[int, int, list[tuple[float, float]]]] = []
    start = 0
    current: list[tuple[float, float]] = []
    for index, line in enumerate(lines):
        candidate = _column_candidate(line)
        if candidate is not None:
            if not current:
                start = index
            current.append(candidate)
        elif current:
            runs.append((start, index, current))
            current = []
    if current:
        runs.append((start, len(lines), current))
    for run_start, run_end, candidates in sorted(runs, key=lambda item: -len(item[2])):
        if len(candidates) < 2:
            continue
        left_starts = [candidate[0] for candidate in candidates]
        right_starts = [candidate[1] for candidate in candidates]
        if max(left_starts) - min(left_starts) > _COLUMN_STABILITY:
            continue
        if max(right_starts) - min(right_starts) > _COLUMN_STABILITY:
            continue
        boundary = (median(left_starts) + median(right_starts)) / 2
        return run_start, run_end, boundary
    return None


def _column_candidate(line: _Line) -> tuple[float, float] | None:
    if len(line.fragments) != 2:
        return None
    left, right = line.fragments
    if right.x0 - left.x0 < _COLUMN_GAP:
        return None
    return left.x0, right.x0


def _draft_from_fragments(fragments: list[_Fragment]) -> _BlockDraft:
    ordered = sorted(fragments, key=lambda item: (item.y0, item.x0))
    line_groups = _group_lines(ordered)
    text = "\n".join(
        " ".join(fragment.text for fragment in line.fragments) for line in line_groups
    )
    confidences = [fragment.confidence for fragment in fragments if fragment.confidence is not None]
    return _BlockDraft(
        text=text,
        x0=min(fragment.x0 for fragment in fragments),
        y0=min(fragment.y0 for fragment in fragments),
        x1=max(fragment.x1 for fragment in fragments),
        y1=max(fragment.y1 for fragment in fragments),
        font_size=max(fragment.font_size for fragment in fragments),
        source=fragments[0].source,
        confidence=sum(confidences) / len(confidences) if confidences else None,
    )


def _merge_adjacent_drafts(drafts: list[_BlockDraft]) -> list[_BlockDraft]:
    merged: list[_BlockDraft] = []
    for draft in drafts:
        if merged and _can_merge(merged[-1], draft):
            previous = merged.pop()
            confidences = [
                value for value in (previous.confidence, draft.confidence) if value is not None
            ]
            merged.append(
                _BlockDraft(
                    text=f"{previous.text}\n{draft.text}",
                    x0=min(previous.x0, draft.x0),
                    y0=min(previous.y0, draft.y0),
                    x1=max(previous.x1, draft.x1),
                    y1=max(previous.y1, draft.y1),
                    font_size=max(previous.font_size, draft.font_size),
                    source=previous.source,
                    confidence=sum(confidences) / len(confidences) if confidences else None,
                )
            )
        else:
            merged.append(draft)
    return merged


def _can_merge(previous: _BlockDraft, current: _BlockDraft) -> bool:
    return (
        previous.source == current.source
        and abs(previous.x0 - current.x0) <= 0.04
        and 0.0 <= current.y0 - previous.y1 <= 0.025
        and max(previous.font_size, current.font_size)
        / min(previous.font_size, current.font_size)
        <= 1.25
    )


def _classify(
    draft: _BlockDraft, median_font_size: float
) -> Literal["heading", "body", "caption", "header", "footer"]:
    if draft.y0 <= 0.25 and len(draft.text) <= 120 and draft.font_size >= median_font_size * 1.25:
        return "heading"
    if draft.y0 <= 0.04:
        return "header"
    if draft.y1 >= 0.94:
        return "footer"
    if draft.y0 >= 0.78 and len(draft.text) <= 140:
        return "caption"
    return "body"


def _transform_point(x: float, y: float, cm: Any) -> tuple[float, float]:
    return (
        x * float(cm[0]) + y * float(cm[2]) + float(cm[4]),
        x * float(cm[1]) + y * float(cm[3]) + float(cm[5]),
    )


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
