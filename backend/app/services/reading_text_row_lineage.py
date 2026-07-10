"""Builder-emitted, construction-time row lineage (see ``reading_text.py``'s ``RowLineageSegment``).

This module does no matching, searching, or resolution of its own — it only converts already-known
``RowLineageSegment`` values (attached to a ``ReadingRow`` at collection time, then carried through
rendering by ``reading_text.py``) into the versioned ``ReadingTextRowLineageMap`` schema shape, with
row-local page offsets converted to document-level raw offsets. Unlike
``reading_text_geometry_projection.py``, there is no post-render search step here at all.

Coverage is intentionally sparse: only the plain-paragraph/body rendering path in
``reading_text.py`` attaches lineage, so most documents will have canonical spans this map does not
cover. Callers should keep falling back to the geometry projection / unique-token
``reading_text_map`` for those.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.schemas import (
    CanonicalTextSegmentV1,
    CanonicalTextSourceRange,
    ReadingTextRowLineageMap,
    ReadingTextRowLineageSummary,
    TextPageResult,
)
from app.services.reading_text import RowLineageSegment

_REASON_ROW_CONSTRUCTION = "row_construction"


def build_reading_text_row_lineage_map(
    *,
    document_id: str,
    reading_text: str | None,
    pages: Sequence[TextPageResult],
    row_lineage: Sequence[RowLineageSegment],
) -> ReadingTextRowLineageMap | None:
    """Convert builder-emitted row lineage into the versioned map, or ``None`` when there is none.

    Callers fall back to the geometry projection / unique-token map when this returns ``None`` (no
    canonical text, or no row on this document ever resolved a construction-time source range).
    """
    if not reading_text or not row_lineage:
        return None

    page_bases = _page_bases(pages)
    page_lengths = {page.page_number: len(page.text) for page in pages}
    segments: list[CanonicalTextSegmentV1] = []
    claimed_raw_ranges: list[tuple[int, int]] = []
    for row_segment in sorted(row_lineage, key=lambda item: item.canonical_start):
        base = page_bases.get(row_segment.page_number)
        page_length = page_lengths.get(row_segment.page_number)
        if base is None or page_length is None:
            continue
        if row_segment.canonical_end > len(reading_text) or row_segment.page_end > page_length:
            continue
        raw_start = base + row_segment.page_start
        raw_end = base + row_segment.page_end
        # Defensive: never let two segments claim overlapping raw ranges (the schema forbids it).
        # This should be unreachable given the collection-time global-uniqueness discipline in
        # ``reading_text.py``, but a document this module has never seen must never crash artifact
        # creation over an edge case that discipline missed -- decline the later segment instead.
        if any(
            raw_start < other_end and other_start < raw_end
            for other_start, other_end in claimed_raw_ranges
        ):
            continue
        claimed_raw_ranges.append((raw_start, raw_end))
        segments.append(
            CanonicalTextSegmentV1(
                segment_id=_segment_id(
                    document_id,
                    row_segment.canonical_start,
                    row_segment.canonical_end,
                    (raw_start, raw_end),
                ),
                canonical_start=row_segment.canonical_start,
                canonical_end=row_segment.canonical_end,
                source_range=CanonicalTextSourceRange(
                    start=raw_start, end=raw_end, source_role="body"
                ),
                segment_role="body",
                mapping_status="exact",
                confidence=1.0,
                reason_codes=[_REASON_ROW_CONSTRUCTION],
                page_number=row_segment.page_number,
            )
        )
    if not segments:
        return None
    return ReadingTextRowLineageMap(segments=segments, summary=_summary(reading_text, segments))


def _summary(
    reading_text: str, segments: Sequence[CanonicalTextSegmentV1]
) -> ReadingTextRowLineageSummary:
    mapped_chars = sum(segment.canonical_end - segment.canonical_start for segment in segments)
    total = len(reading_text)
    return ReadingTextRowLineageSummary(
        lineage_source="row_construction",
        total_segments=len(segments),
        canonical_char_count=total,
        mapped_canonical_char_count=mapped_chars,
        coverage_ratio=(mapped_chars / total) if total else 0.0,
    )


def _page_bases(pages: Sequence[TextPageResult]) -> dict[int, int]:
    """Document-level base offset of each page (pages joined by ``\\n\\n`` in the raw text)."""
    bases: dict[int, int] = {}
    base = 0
    for page in pages:
        bases[page.page_number] = base
        base += len(page.text) + 2
    return bases


def _segment_id(
    document_id: str, canonical_start: int, canonical_end: int, raw_span: tuple[int, int]
) -> str:
    material = (
        f"{document_id}\x00{canonical_start}\x00{canonical_end}\x00{raw_span[0]}\x00{raw_span[1]}"
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]
