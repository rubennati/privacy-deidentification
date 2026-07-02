"""Deterministic OCR/Text L10 line-level span geometry.

This module builds the first canonical-text-to-page-geometry mapping: it resolves a canonical line
span to one or more page-local line boxes. Offsets are derived by matching page-local text segments
against the immutable canonical page text, never by regenerating or altering that text. Boxes come
from positions already reported by pypdf (PDF text layer) or PaddleOCR polygons (OCR/image pages).

This is line-level source-anchoring geometry for review/debug and traceability, and a foundation for
future placeholder mapping in AI-ready pseudonymized document generation. It does **not** perform
pseudonymization, placeholder mapping, document export, or pixel-perfect visual redaction. When
precise line boxes are not safely derivable the page degrades to a ``partial``/``unsupported``
status with a coverage flag rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pypdf import PageObject

from app.schemas import TextGeometry, TextGeometryPage, TextLineGeometry
from app.services.layout_text import _PdfTextState, _transform_point
from app.services.ocr_adapters import OcrExtractionResult

_CoordinateUnit = Literal["pdf_points", "image_pixels"]
_Source = Literal["pdf_text_layer", "paddleocr", "fallback"]
_LINE_MIN_TOLERANCE = 0.5


@dataclass(frozen=True)
class _GeoLine:
    """One reading-order line candidate with page-local bounds and optional OCR confidence."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    source: _Source
    confidence: float | None = None


@dataclass(frozen=True)
class SpanLineBox:
    """A resolved line box for a canonical span lookup. Carries geometry only, never raw text."""

    page_number: int
    line_index: int
    coordinate_unit: _CoordinateUnit
    x0: float
    y0: float
    x1: float
    y1: float
    source: _Source
    confidence: float | None = None


def build_pdf_page_geometry(
    page: PageObject, page_number: int, page_text: str, canonical_base: int
) -> TextGeometryPage | None:
    """Build line geometry for one PDF text-layer page, or ``None`` when unavailable."""
    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if width <= 0.0 or height <= 0.0:
            return None
        geo_lines = _collect_pdf_geo_lines(page, width, height)
    except Exception:
        return None
    return _assemble_page(
        geo_lines,
        page_text,
        page_number=page_number,
        page_width=width,
        page_height=height,
        coordinate_unit="pdf_points",
        source="pdf_text_layer",
        canonical_base=canonical_base,
    )


def build_ocr_page_geometry(
    result: OcrExtractionResult, page_number: int, page_text: str, canonical_base: int
) -> TextGeometryPage | None:
    """Build line geometry from OCR polygons, or ``None`` when image size is unknown."""
    if not result.image_width or not result.image_height:
        return None
    width = float(result.image_width)
    height = float(result.image_height)
    geo_lines: list[_GeoLine] = []
    for line in result.layout_lines:
        xs = [point[0] for point in line.polygon]
        ys = [point[1] for point in line.polygon]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if x1 <= x0 or y1 <= y0:
            continue
        geo_lines.append(
            _GeoLine(
                text=line.text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                source="paddleocr",
                confidence=line.confidence,
            )
        )
    return _assemble_page(
        geo_lines,
        page_text,
        page_number=page_number,
        page_width=width,
        page_height=height,
        coordinate_unit="image_pixels",
        source="paddleocr",
        canonical_base=canonical_base,
    )


def build_text_geometry(
    geometry_pages: list[TextGeometryPage], total_pages: int
) -> TextGeometry | None:
    """Assemble per-page geometry into one versioned artifact with coverage and flags.

    ``None`` when no page produced geometry (e.g. DOCX or an all-unknown-dimension document), so the
    field stays absent and legacy/unsupported artifacts remain valid.
    """
    if not geometry_pages:
        return None
    ordered = sorted(geometry_pages, key=lambda page: page.page_number)
    covered = sum(1 for page in ordered if page.status != "unsupported")
    coverage = covered / total_pages if total_pages > 0 else 0.0
    sources = {page.source for page in ordered}
    flags: list[str] = []
    if "pdf_text_layer" in sources:
        flags.append("text_layer_geometry")
    if "paddleocr" in sources:
        flags.append("ocr_geometry")
    if {"pdf_text_layer", "paddleocr"} <= sources:
        flags.append("mixed_geometry")
    if coverage < 1.0 or any(page.status != "complete" for page in ordered):
        flags.append("partial_geometry")
    return TextGeometry(pages=ordered, coverage=coverage, flags=flags)


def resolve_span_geometry(
    text_geometry: TextGeometry | None, start_offset: int, end_offset: int
) -> list[SpanLineBox]:
    """Return the page line boxes whose canonical span intersects ``[start, end)``.

    Ranges are validated defensively: a missing geometry, a negative start, or a non-positive-width
    span yields a safe empty result. No raw text is ever returned.
    """
    if text_geometry is None or start_offset < 0 or end_offset <= start_offset:
        return []
    matches: list[SpanLineBox] = []
    for page in text_geometry.pages:
        for line in page.lines:
            if line.canonical_start < end_offset and start_offset < line.canonical_end:
                matches.append(
                    SpanLineBox(
                        page_number=page.page_number,
                        line_index=line.line_index,
                        coordinate_unit=page.coordinate_unit,
                        x0=line.x0,
                        y0=line.y0,
                        x1=line.x1,
                        y1=line.y1,
                        source=line.source,
                        confidence=line.confidence,
                    )
                )
    matches.sort(key=lambda box: (box.page_number, box.line_index))
    return matches


def _assemble_page(
    geo_lines: list[_GeoLine],
    page_text: str,
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    coordinate_unit: _CoordinateUnit,
    source: _Source,
    canonical_base: int,
) -> TextGeometryPage:
    """Match reading-order line candidates to canonical page-text segments and build line boxes."""
    segments = _segment_offsets(page_text)
    matched: list[tuple[int, int, _GeoLine]] = []
    cursor = 0
    for geo_line in geo_lines:
        target = _collapse(geo_line.text)
        if not target:
            continue
        index = cursor
        while index < len(segments):
            if segments[index][2] == target:
                matched.append((segments[index][0], segments[index][1], geo_line))
                cursor = index + 1
                break
            index += 1
    matched.sort(key=lambda item: (item[0], item[1]))

    lines: list[TextLineGeometry] = []
    for line_index, (page_start, page_end, geo_line) in enumerate(matched, start=1):
        x0 = _clamp(geo_line.x0, page_width)
        y0 = _clamp(geo_line.y0, page_height)
        x1 = _clamp(geo_line.x1, page_width)
        y1 = _clamp(geo_line.y1, page_height)
        lines.append(
            TextLineGeometry(
                line_index=line_index,
                canonical_start=canonical_base + page_start,
                canonical_end=canonical_base + page_end,
                page_start=page_start,
                page_end=page_end,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                source=geo_line.source,
                confidence=geo_line.confidence,
            )
        )

    if not lines:
        status: Literal["complete", "partial", "unsupported"] = "unsupported"
    elif len(lines) == len(segments):
        status = "complete"
    else:
        status = "partial"
    return TextGeometryPage(
        page_number=page_number,
        page_width=page_width,
        page_height=page_height,
        coordinate_unit=coordinate_unit,
        source=source,
        status=status,
        lines=lines,
    )


def _collect_pdf_geo_lines(page: PageObject, width: float, height: float) -> list[_GeoLine]:
    """Collect page-point line candidates from pypdf text-draw operations (top-left origin)."""
    left = float(page.mediabox.left)
    bottom = float(page.mediabox.bottom)
    fragments: list[tuple[str, float, float, float, float]] = []
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
        estimated_width = min(width - x, max(size * 0.5, len(text) * size * 0.52))
        x0 = x
        x1 = x + estimated_width
        y0 = height - y - size
        y1 = height - y + size * 0.2
        if x1 <= x0 or y1 <= y0:
            return
        fragments.append((text, x0, y0, x1, y1))

    page.extract_text(visitor_operand_before=state.visit_operand, visitor_text=visitor_text)
    return _group_fragment_lines(fragments)


def _group_fragment_lines(
    fragments: list[tuple[str, float, float, float, float]],
) -> list[_GeoLine]:
    """Group fragments sharing a vertical band into one left-to-right line candidate."""
    if not fragments:
        return []
    ordered = sorted(fragments, key=lambda item: ((item[2] + item[4]) / 2, item[1]))
    heights = sorted(item[4] - item[2] for item in ordered)
    typical = heights[len(heights) // 2]
    tolerance = max(_LINE_MIN_TOLERANCE, typical * 0.6)
    groups: list[list[tuple[str, float, float, float, float]]] = []
    for fragment in ordered:
        center = (fragment[2] + fragment[4]) / 2
        if groups:
            previous = groups[-1]
            previous_center = sum((item[2] + item[4]) / 2 for item in previous) / len(previous)
            if abs(previous_center - center) <= tolerance:
                previous.append(fragment)
                continue
        groups.append([fragment])
    lines: list[_GeoLine] = []
    for group in groups:
        row = sorted(group, key=lambda item: item[1])
        lines.append(
            _GeoLine(
                text=" ".join(item[0] for item in row),
                x0=min(item[1] for item in row),
                y0=min(item[2] for item in row),
                x1=max(item[3] for item in row),
                y1=max(item[4] for item in row),
                source="pdf_text_layer",
            )
        )
    return lines


def _segment_offsets(text: str) -> list[tuple[int, int, str]]:
    """Half-open ``(start, end, collapsed)`` for each non-blank ``\\n``-delimited page-text line."""
    segments: list[tuple[int, int, str]] = []
    start = 0
    for line in text.split("\n"):
        end = start + len(line)
        collapsed = _collapse(line)
        if collapsed:
            segments.append((start, end, collapsed))
        start = end + 1
    return segments


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _clamp(value: float, upper: float) -> float:
    return min(upper, max(0.0, value))
