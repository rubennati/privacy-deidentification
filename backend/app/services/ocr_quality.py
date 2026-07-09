"""Deterministic OCR/Text L14 quality evidence and lineage coverage.

This module answers, for every OCR/Text artifact, *where the text came from* and *how well it is
connected* — without touching any text layer, PII input, or review decision. It is additive,
metrics-only evidence: every locator is an offset range, page number, page zone, coarse bound,
count, flag, or stable ``reason_code``. It never stores raw document text (``details`` is
``dict[str, int]`` by construction), never reorders or deletes text, and never changes PII
detection.

It is *evidence before correction*: it reads the already-built reading text, its strategy flags, the
reading↔raw map, span geometry, and structured content, and reports what happened. It does not
re-run OCR, does not guess structure, and classifies missing signals (``unavailable``/
``not_applicable``) instead of inventing them.

Future evidence sources (dictionary/lexicon checks, domain vocabulary, per-token OCR confidence,
PDF-text-layer-versus-OCR comparison, second-engine agreement, a local model, and review feedback)
are designed to plug in as additional :class:`QualityEvidenceItem`s. They are *evidence, not truth*:
they may raise or lower confidence but must never silently rewrite OCR/Text or change PII decisions.

OCR/Text L15 adds one such source deterministically: ``ocr_noise.build_ocr_noise_evidence`` scans
technical raw per-page text for shape-based noise/token-artifact signals (glyph artifacts,
suspicious token shapes, character-confusion candidates, and spacing candidates) plus a
document-level ``ocr_noise_summary``. It is folded into the same flat ``items`` list below — no new
artifact, no new schema version, and no dictionary/multi-OCR/local-LLM behavior. See
[ADR-0026](../../../docs/adr/0026-ocr-l15-noise-token-artifact-evidence.md).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas import (
    QualityEvidence,
    QualityEvidenceBounds,
    QualityEvidenceItem,
    QualityEvidenceLevel,
    QualityEvidenceStatus,
    QualityEvidenceSummary,
    QualityEvidenceType,
    QualityLineageCoverage,
    QualityOffsetRange,
    QualityPageZone,
    ReadingTextMapSegment,
    StructuredContent,
    TextGeometry,
    TextGeometryPage,
    TextLineGeometry,
    TextPageResult,
)
from app.services.ocr_noise import build_ocr_noise_evidence
from app.services.reading_text import ReadingTextResult

# Reading-text strategy flags grouped by what they tell us. These mirror the non-sensitive flags the
# reading-text builder already emits (see ``reading_text.py``); grouping them here keeps the mapping
# from "strategy that ran" to "evidence" in one place.
_MULTI_COLUMN_FLAGS = frozenset({"two_column_grouping", "multi_column_reconstruction"})
_TABLE_FLAGS = frozenset(
    {"table_row_reconstruction", "generic_table_reconstruction", "dense_table_reconstruction"}
)
_FORM_FLAGS = frozenset({"label_value_pairing", "multiline_value_pairing"})
_RECONSTRUCTION_FLAGS = (
    _MULTI_COLUMN_FLAGS
    | _TABLE_FLAGS
    | _FORM_FLAGS
    | frozenset(
        {"geometry_ordering", "layout_block_ordering", "document_sections",
         "conservative_line_joining"}
    )
)
_FALLBACK_FLAGS = frozenset({"raw_order_fallback", "layout_text_fallback", "partial_geometry"})
# Evidence types whose ``unavailable`` status genuinely blocks downstream understanding, as opposed
# to a merely absent optional layer (e.g. no PDF text layer on an image is expected, not a blocker).
_BLOCKER_TYPES = frozenset({"source_text", "reading_order"})

# Conservative page-zone bands as a fraction of page height/width. Zones are *evidence only*: they
# explain likely origin/position and never delete or reorder text. Geometry uses a top-left origin
# (see ``text_geometry.py``), so a smaller normalized y is nearer the top.
_HEADER_ZONE_MAX = 0.10
_FOOTER_ZONE_MIN = 0.90
_RIGHT_ZONE_MIN_START = 0.60
_LEFT_ZONE_MAX_END = 0.15
_ZONE_TIE_ORDER: tuple[QualityPageZone, ...] = (
    "body",
    "header",
    "footer",
    "left_margin",
    "right_margin",
)


def build_quality_evidence(
    *,
    source: str,
    text: str,
    pages: Sequence[TextPageResult],
    reading: ReadingTextResult | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
    text_geometry: TextGeometry | None,
    structured_content: StructuredContent | None,
) -> QualityEvidence:
    """Build additive quality evidence and lineage coverage for one OCR/Text artifact.

    Always returns evidence, even for an empty extraction (which reports ``unavailable`` signals) so
    every freshly created artifact can be audited. Legacy artifacts simply carry no evidence.
    """

    reading_flags = set(reading.flags) if reading is not None else set()
    has_raw = bool(text.strip())
    raw_length = len(text)

    items: list[QualityEvidenceItem] = [
        _source_text_item(text, has_raw, raw_length),
        _pdf_text_layer_item(source, pages),
        _ocr_engine_item(source, pages),
    ]
    items.extend(_geometry_items(source, text_geometry))
    items.append(_positioned_rows_item(source, text_geometry))
    items.extend(_page_zone_items(text_geometry))
    items.append(_reading_order_item(reading, reading_flags, has_raw))
    items.extend(_reconstruction_items(reading_flags))
    items.extend(_fallback_items(reading, reading_flags, has_raw))
    items.append(_structured_content_item(structured_content))

    items.extend(
        build_ocr_noise_evidence(
            text=text, pages=pages, page_zones=_page_zone_map(text_geometry)
        )
    )

    lineage = _lineage(reading, reading_text_map, text_geometry, structured_content)
    items.extend(_lineage_items(reading, reading_text_map, lineage))

    summary = _summary(items, reading, reading_flags, has_raw, lineage)
    return QualityEvidence(items=items, summary=summary)


def _item(
    evidence_id: str,
    level: QualityEvidenceLevel,
    type_: QualityEvidenceType,
    status: QualityEvidenceStatus,
    reason_code: str,
    **kwargs: object,
) -> QualityEvidenceItem:
    return QualityEvidenceItem(
        evidence_id=evidence_id,
        level=level,
        type=type_,
        status=status,
        reason_code=reason_code,
        **kwargs,
    )


def _source_text_item(text: str, has_raw: bool, raw_length: int) -> QualityEvidenceItem:
    non_whitespace = sum(1 for character in text if not character.isspace())
    details = {"raw_char_count": raw_length, "raw_non_whitespace_chars": non_whitespace}
    if not has_raw:
        return _item(
            "doc-source-text", "document", "source_text", "unavailable",
            "raw_text_missing", details=details,
        )
    return _item(
        "doc-source-text", "document", "source_text", "confident", "raw_text_available",
        raw_text_range=QualityOffsetRange(start=0, end=raw_length), details=details,
    )


def _pdf_text_layer_item(source: str, pages: Sequence[TextPageResult]) -> QualityEvidenceItem:
    text_layer_pages = sum(1 for page in pages if page.has_text_layer)
    details = {"text_layer_pages": text_layer_pages, "page_count": len(pages)}
    if source == "docx_text":
        return _item(
            "doc-pdf-text-layer", "document", "pdf_text_layer", "not_applicable",
            "docx_has_no_pdf_text_layer", details=details,
        )
    if source == "paddleocr":
        return _item(
            "doc-pdf-text-layer", "document", "pdf_text_layer", "not_applicable",
            "pdf_text_layer_not_used", details=details,
        )
    if source == "pdf_mixed":
        return _item(
            "doc-pdf-text-layer", "document", "pdf_text_layer", "partial",
            "pdf_text_layer_partial", details=details,
        )
    return _item(
        "doc-pdf-text-layer", "document", "pdf_text_layer", "confident",
        "pdf_text_layer_used", details=details,
    )


def _ocr_engine_item(source: str, pages: Sequence[TextPageResult]) -> QualityEvidenceItem:
    ocr_pages = sum(1 for page in pages if page.ocr_used)
    ocr_with_confidence = sum(
        1 for page in pages if page.ocr_used and page.ocr_confidence is not None
    )
    details = {"ocr_pages": ocr_pages, "ocr_pages_with_confidence": ocr_with_confidence}
    if ocr_pages:
        return _item(
            "doc-ocr-engine", "document", "ocr_engine", "confident", "ocr_engine_used",
            details=details,
        )
    if source == "docx_text":
        return _item(
            "doc-ocr-engine", "document", "ocr_engine", "not_applicable", "docx_uses_no_ocr",
            details=details,
        )
    return _item(
        "doc-ocr-engine", "document", "ocr_engine", "not_applicable", "ocr_not_required",
        details=details,
    )


def _geometry_items(
    source: str, text_geometry: TextGeometry | None
) -> list[QualityEvidenceItem]:
    if text_geometry is None:
        if source == "docx_text":
            return [_item(
                "doc-page-geometry", "document", "page_geometry", "not_applicable",
                "docx_has_no_geometry",
            )]
        return [_item(
            "doc-page-geometry", "document", "page_geometry", "unavailable",
            "page_geometry_unavailable",
        )]
    geometry_pages = text_geometry.pages
    complete = sum(1 for page in geometry_pages if page.status == "complete")
    partial = sum(1 for page in geometry_pages if page.status == "partial")
    unsupported = sum(1 for page in geometry_pages if page.status == "unsupported")
    coverage = text_geometry.coverage
    if coverage <= 0.0:
        status: QualityEvidenceStatus = "unavailable"
        reason = "page_geometry_unavailable"
    elif coverage >= 0.999 and partial == 0 and unsupported == 0:
        status = "confident"
        reason = "page_geometry_complete"
    else:
        status = "partial"
        reason = "page_geometry_partial"
    items = [_item(
        "doc-page-geometry", "document", "page_geometry", status, reason,
        confidence=round(coverage, 6),
        details={
            "geometry_pages": len(geometry_pages),
            "complete_pages": complete,
            "partial_pages": partial,
            "unsupported_pages": unsupported,
        },
    )]
    items.extend(_page_geometry_item(page) for page in geometry_pages)
    return items


_PAGE_STATUS_TO_EVIDENCE: dict[str, QualityEvidenceStatus] = {
    "complete": "confident",
    "partial": "partial",
    "unsupported": "unavailable",
}


def _page_geometry_item(page: TextGeometryPage) -> QualityEvidenceItem:
    details = {"line_count": len(page.lines)}
    with_confidence = sum(1 for line in page.lines if line.confidence is not None)
    if with_confidence:
        details["lines_with_confidence"] = with_confidence
    return _item(
        f"page-{page.page_number}-geometry", "page", "page_geometry",
        _PAGE_STATUS_TO_EVIDENCE[page.status], f"page_geometry_{page.status}",
        page_number=page.page_number, related_artifact="text_geometry", details=details,
    )


def _positioned_rows_item(
    source: str, text_geometry: TextGeometry | None
) -> QualityEvidenceItem:
    if text_geometry is None:
        if source == "docx_text":
            return _item(
                "doc-positioned-rows", "document", "positioned_rows", "not_applicable",
                "docx_has_no_positioned_rows",
            )
        return _item(
            "doc-positioned-rows", "document", "positioned_rows", "unavailable",
            "positioned_rows_unavailable",
        )
    geometry_pages = text_geometry.pages
    total_rows = sum(len(page.lines) for page in geometry_pages)
    pages_with_rows = sum(1 for page in geometry_pages if page.lines)
    details = {
        "row_count": total_rows,
        "pages_with_rows": pages_with_rows,
        "geometry_pages": len(geometry_pages),
    }
    if total_rows == 0:
        return _item(
            "doc-positioned-rows", "document", "positioned_rows", "unavailable",
            "positioned_rows_unavailable", details=details,
        )
    if pages_with_rows == len(geometry_pages):
        return _item(
            "doc-positioned-rows", "document", "positioned_rows", "confident",
            "positioned_rows_available", details=details,
        )
    return _item(
        "doc-positioned-rows", "document", "positioned_rows", "partial",
        "positioned_rows_partial", details=details,
    )


def _page_zone_items(text_geometry: TextGeometry | None) -> list[QualityEvidenceItem]:
    if text_geometry is None:
        return []
    return [_page_zone_item(page) for page in text_geometry.pages]


def _zone_counts(page: TextGeometryPage) -> dict[QualityPageZone, int]:
    zone_counts: dict[QualityPageZone, int] = {
        "header": 0, "footer": 0, "left_margin": 0, "right_margin": 0, "body": 0,
    }
    for line in page.lines:
        zone = _line_zone(line, page.page_width, page.page_height)
        if zone != "unknown":
            zone_counts[zone] += 1
    return zone_counts


def _dominant_zone(zone_counts: dict[QualityPageZone, int]) -> QualityPageZone | None:
    if sum(zone_counts.values()) == 0:
        return None
    dominant = max(_ZONE_TIE_ORDER, key=lambda zone: zone_counts[zone])
    return dominant


def _page_zone_map(text_geometry: TextGeometry | None) -> dict[int, QualityPageZone]:
    """Page-number -> dominant-zone map, reused as-is from the L14 page zone classification.

    L15 noise evidence tags its findings with this same conservative, already-computed zone instead
    of inventing a second classification — a page with no safely classifiable zone (no geometry, or
    zero classified lines) simply carries no zone tag.
    """

    if text_geometry is None:
        return {}
    zone_map: dict[int, QualityPageZone] = {}
    for page in text_geometry.pages:
        dominant = _dominant_zone(_zone_counts(page))
        if dominant is not None:
            zone_map[page.page_number] = dominant
    return zone_map


def _page_zone_item(page: TextGeometryPage) -> QualityEvidenceItem:
    zone_counts = _zone_counts(page)
    details = {f"{zone}_lines": count for zone, count in zone_counts.items()}
    dominant = _dominant_zone(zone_counts)
    if dominant is None:
        return _item(
            f"page-{page.page_number}-zone", "page", "page_zone", "unavailable",
            "page_zone_unavailable", page_number=page.page_number, page_zone="unknown",
            related_artifact="text_geometry", details=details,
        )
    status: QualityEvidenceStatus = "confident" if page.status == "complete" else "partial"
    return _item(
        f"page-{page.page_number}-zone", "page", "page_zone", status, "page_zone_classified",
        page_number=page.page_number, page_zone=dominant, bbox=_page_line_bounds(page),
        related_artifact="text_geometry", details=details,
    )


def _line_zone(
    line: TextLineGeometry, page_width: float, page_height: float
) -> QualityPageZone:
    if page_width <= 0.0 or page_height <= 0.0:
        return "unknown"
    y_center = ((line.y0 + line.y1) / 2) / page_height
    if y_center <= _HEADER_ZONE_MAX:
        return "header"
    if y_center >= _FOOTER_ZONE_MIN:
        return "footer"
    if line.x0 / page_width >= _RIGHT_ZONE_MIN_START:
        return "right_margin"
    if line.x1 / page_width <= _LEFT_ZONE_MAX_END:
        return "left_margin"
    return "body"


def _page_line_bounds(page: TextGeometryPage) -> QualityEvidenceBounds | None:
    if not page.lines or page.page_width <= 0.0 or page.page_height <= 0.0:
        return None
    return QualityEvidenceBounds(
        x0=_clamp(min(line.x0 for line in page.lines) / page.page_width),
        y0=_clamp(min(line.y0 for line in page.lines) / page.page_height),
        x1=_clamp(max(line.x1 for line in page.lines) / page.page_width),
        y1=_clamp(max(line.y1 for line in page.lines) / page.page_height),
        coordinate_unit="normalized",
    )


def _reading_order_item(
    reading: ReadingTextResult | None, reading_flags: set[str], has_raw: bool
) -> QualityEvidenceItem:
    if reading is None:
        reason = "reading_text_unavailable" if not has_raw else "reading_text_not_built"
        return _item(
            "doc-reading-order", "reading_text", "reading_order", "unavailable", reason,
            related_artifact="reading_text",
        )
    if reading.status == "fallback":
        status: QualityEvidenceStatus = "fallback"
        reason = "reading_order_fallback"
    elif "geometry_ordering" in reading_flags:
        status = "confident"
        reason = "reading_order_from_geometry"
    elif "layout_block_ordering" in reading_flags:
        status = "confident"
        reason = "reading_order_from_layout_blocks"
    elif "layout_text_fallback" in reading_flags:
        status = "partial"
        reason = "reading_order_from_layout_text"
    else:
        status = "partial"
        reason = "reading_order_heuristic"
    if status == "confident" and "partial_geometry" in reading_flags:
        status = "partial"
    return _item(
        "doc-reading-order", "reading_text", "reading_order", status, reason,
        reading_text_range=QualityOffsetRange(start=0, end=len(reading.text)),
        related_artifact="reading_text", flags=sorted(reading_flags),
    )


def _reconstruction_items(reading_flags: set[str]) -> list[QualityEvidenceItem]:
    items: list[QualityEvidenceItem] = []
    if reading_flags & _MULTI_COLUMN_FLAGS:
        items.append(_item(
            "recon-multi-column", "reading_text", "multi_column_reconstruction", "confident",
            "multi_column_layout_reconstructed", related_artifact="reading_text",
            flags=sorted(reading_flags & _MULTI_COLUMN_FLAGS),
        ))
    if reading_flags & _TABLE_FLAGS:
        items.append(_item(
            "recon-table", "reading_text", "table_reconstruction", "confident",
            "table_structure_reconstructed", related_artifact="reading_text",
            flags=sorted(reading_flags & _TABLE_FLAGS),
        ))
    if reading_flags & _FORM_FLAGS:
        items.append(_item(
            "recon-form", "reading_text", "form_reconstruction", "confident",
            "label_value_pairs_reconstructed", related_artifact="reading_text",
            flags=sorted(reading_flags & _FORM_FLAGS),
        ))
    return items


def _fallback_items(
    reading: ReadingTextResult | None, reading_flags: set[str], has_raw: bool
) -> list[QualityEvidenceItem]:
    items: list[QualityEvidenceItem] = []
    if reading is None:
        if not has_raw:
            items.append(_item(
                "doc-skipped-reconstruction", "reading_text", "skipped_reconstruction",
                "unavailable", "reconstruction_unavailable_no_text",
            ))
        return items
    fallback_present = sorted(reading_flags & _FALLBACK_FLAGS)
    if reading.status == "fallback":
        items.append(_item(
            "doc-fallback", "reading_text", "fallback", "fallback", "reading_text_fallback_order",
            related_artifact="reading_text", flags=fallback_present,
        ))
        items.append(_item(
            "doc-skipped-reconstruction", "reading_text", "skipped_reconstruction", "skipped",
            "reconstruction_skipped_low_confidence", related_artifact="reading_text",
        ))
    elif fallback_present:
        items.append(_item(
            "doc-fallback", "reading_text", "fallback", "partial", "reading_text_partial_fallback",
            related_artifact="reading_text", flags=fallback_present,
        ))
    if "partial_geometry" in reading_flags:
        items.append(_item(
            "doc-low-confidence-geometry", "reading_text", "low_confidence", "low_confidence",
            "row_geometry_insufficient", related_artifact="text_geometry",
            flags=["partial_geometry"],
        ))
    return items


def _structured_content_item(
    structured_content: StructuredContent | None,
) -> QualityEvidenceItem:
    if structured_content is None:
        return _item(
            "doc-structured-content", "structured_content", "structured_content", "unavailable",
            "structured_content_unavailable",
        )
    summary = structured_content.summary
    partial = "partial_structure" in structured_content.flags
    return _item(
        "doc-structured-content", "structured_content", "structured_content",
        "partial" if partial else "confident",
        "structured_content_partial" if partial else "structured_content_available",
        related_artifact="structured_content",
        details={
            "page_count": summary.page_count,
            "table_count": summary.table_count,
            "field_count": summary.field_count,
            "section_count": summary.section_count,
        },
    )


def _lineage_items(
    reading: ReadingTextResult | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
    lineage: QualityLineageCoverage,
) -> list[QualityEvidenceItem]:
    items = [_reading_text_map_item(reading, reading_text_map, lineage)]
    items.append(_lineage_coverage_item(lineage))
    items.append(_projection_lineage_item(reading, reading_text_map, lineage))
    return items


def _reading_text_map_item(
    reading: ReadingTextResult | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
    lineage: QualityLineageCoverage,
) -> QualityEvidenceItem:
    if reading is None or lineage.reading_text_length == 0:
        return _item(
            "doc-reading-text-map", "projection_lineage", "reading_text_map", "unavailable",
            "reading_text_map_unavailable", related_artifact="reading_text_map",
        )
    ratio = lineage.mapping_coverage_ratio
    if not reading_text_map:
        status: QualityEvidenceStatus = "unavailable"
        reason = "reading_text_map_empty"
    elif ratio >= 0.8:
        status = "confident"
        reason = "reading_text_map_high_coverage"
    elif ratio >= 0.3:
        status = "partial"
        reason = "reading_text_map_partial_coverage"
    else:
        status = "low_confidence"
        reason = "reading_text_map_low_coverage"
    return _item(
        "doc-reading-text-map", "projection_lineage", "reading_text_map", status, reason,
        confidence=ratio,
        reading_text_range=QualityOffsetRange(start=0, end=lineage.reading_text_length),
        related_artifact="reading_text_map",
        details={
            "mapped_chars": lineage.mapped_reading_text_chars,
            "unmapped_chars": lineage.unmapped_reading_text_chars,
            "coverage_percent": round(ratio * 100),
            "exact_spans": lineage.exact_span_count,
            "partial_spans": lineage.partial_span_count,
            "unmapped_spans": lineage.unmapped_span_count,
        },
    )


def _lineage_coverage_item(lineage: QualityLineageCoverage) -> QualityEvidenceItem:
    geometry_ratio = lineage.source_geometry_coverage_ratio
    details: dict[str, int] = {}
    if geometry_ratio is not None:
        details["source_geometry_coverage_percent"] = round(geometry_ratio * 100)
    if lineage.structured_content_reference_count is not None:
        details["structured_content_references"] = lineage.structured_content_reference_count
    if geometry_ratio is None or geometry_ratio <= 0.0:
        return _item(
            "doc-lineage-coverage", "document", "lineage_coverage", "unavailable",
            "source_geometry_unavailable",
            confidence=None if geometry_ratio is None else 0.0, details=details,
        )
    if geometry_ratio >= 0.999:
        return _item(
            "doc-lineage-coverage", "document", "lineage_coverage", "confident",
            "source_geometry_complete", confidence=round(geometry_ratio, 6), details=details,
        )
    return _item(
        "doc-lineage-coverage", "document", "lineage_coverage", "partial",
        "source_geometry_partial", confidence=round(geometry_ratio, 6), details=details,
    )


def _projection_lineage_item(
    reading: ReadingTextResult | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
    lineage: QualityLineageCoverage,
) -> QualityEvidenceItem:
    if reading is None or lineage.reading_text_length == 0 or not reading_text_map:
        return _item(
            "doc-projection-lineage", "projection_lineage", "projection_lineage", "unavailable",
            "projection_substrate_unavailable", related_artifact="reading_text_map",
        )
    ratio = lineage.mapping_coverage_ratio
    if lineage.exact_span_count == 0:
        status: QualityEvidenceStatus = "unavailable"
        reason = "projection_substrate_unavailable"
    elif ratio >= 0.8:
        status = "confident"
        reason = "projection_substrate_available"
    else:
        status = "partial"
        reason = "projection_substrate_limited"
    return _item(
        "doc-projection-lineage", "projection_lineage", "projection_lineage", status, reason,
        confidence=ratio, related_artifact="reading_text_map",
        details={
            "exact_spans": lineage.exact_span_count,
            "unmapped_spans": lineage.unmapped_span_count,
        },
    )


def _lineage(
    reading: ReadingTextResult | None,
    reading_text_map: Sequence[ReadingTextMapSegment],
    text_geometry: TextGeometry | None,
    structured_content: StructuredContent | None,
) -> QualityLineageCoverage:
    reading_text = reading.text if reading is not None else ""
    reading_length = len(reading_text)
    exact = sum(1 for segment in reading_text_map if segment.mapping_status == "exact")
    partial = sum(1 for segment in reading_text_map if segment.mapping_status != "exact")
    merged = _merge_ranges(
        [(segment.reading_start, segment.reading_end) for segment in reading_text_map]
    )
    mapped = sum(
        min(end, reading_length) - start for start, end in merged if start < reading_length
    )
    mapped = max(0, min(mapped, reading_length))
    unmapped = reading_length - mapped
    coverage_ratio = round(mapped / reading_length, 6) if reading_length else 0.0
    return QualityLineageCoverage(
        reading_text_length=reading_length,
        mapped_reading_text_chars=mapped,
        unmapped_reading_text_chars=unmapped,
        mapping_coverage_ratio=coverage_ratio,
        exact_span_count=exact,
        partial_span_count=partial,
        unmapped_span_count=_unmapped_span_count(reading_text, merged),
        source_geometry_coverage_ratio=(
            text_geometry.coverage if text_geometry is not None else None
        ),
        structured_content_reference_count=(
            _structured_reference_count(structured_content)
            if structured_content is not None
            else None
        ),
    )


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _unmapped_span_count(reading_text: str, merged: list[tuple[int, int]]) -> int:
    length = len(reading_text)
    count = 0
    cursor = 0
    for start, end in merged:
        if start > cursor and reading_text[cursor:start].strip():
            count += 1
        cursor = max(cursor, end)
    if cursor < length and reading_text[cursor:length].strip():
        count += 1
    return count


def _structured_reference_count(structured_content: StructuredContent) -> int:
    total = 0
    for page in structured_content.pages:
        total += sum(len(table.cells) for table in page.tables)
        total += len(page.fields)
        total += len(page.sections)
    return total


def _summary(
    items: Sequence[QualityEvidenceItem],
    reading: ReadingTextResult | None,
    reading_flags: set[str],
    has_raw: bool,
    lineage: QualityLineageCoverage,
) -> QualityEvidenceSummary:
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
        type_counts[item.type] = type_counts.get(item.type, 0) + 1
    warnings = sorted(
        {
            item.reason_code
            for item in items
            if item.status in ("partial", "low_confidence", "fallback", "skipped")
        }
    )
    blockers = sorted(
        {
            item.reason_code
            for item in items
            if item.status == "unavailable" and item.type in _BLOCKER_TYPES
        }
    )
    return QualityEvidenceSummary(
        overall_status=_overall_status(reading, reading_flags, has_raw),
        overall_score=_overall_score(reading, lineage, has_raw),
        counts_by_status=dict(sorted(status_counts.items())),
        counts_by_type=dict(sorted(type_counts.items())),
        warnings=warnings,
        blockers=blockers,
        reconstruction_summary={flag: 1 for flag in sorted(reading_flags & _RECONSTRUCTION_FLAGS)},
        fallback_summary={flag: 1 for flag in sorted(reading_flags & _FALLBACK_FLAGS)},
        lineage_summary=lineage,
    )


def _overall_status(
    reading: ReadingTextResult | None, reading_flags: set[str], has_raw: bool
) -> QualityEvidenceStatus:
    if not has_raw:
        return "unavailable"
    if reading is None:
        return "low_confidence"
    if reading.status == "fallback":
        return "fallback"
    if "partial_geometry" in reading_flags:
        return "partial"
    return "confident"


def _overall_score(
    reading: ReadingTextResult | None, lineage: QualityLineageCoverage, has_raw: bool
) -> float | None:
    """Advisory 0.0-1.0 confidence blend, never a gate, only a comparable signal over time."""
    if not has_raw or reading is None:
        return None
    components = [
        1.0 if reading.status == "heuristic" else 0.3,
        lineage.mapping_coverage_ratio,
    ]
    if lineage.source_geometry_coverage_ratio is not None:
        components.append(lineage.source_geometry_coverage_ratio)
    return round(min(1.0, max(0.0, sum(components) / len(components))), 4)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
