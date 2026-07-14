"""Builder-emitted, construction-time row lineage (see ``reading_text.py``'s ``RowLineageSegment``).

This module does no matching, searching, or resolution of its own for *attributed* segments — it
only converts already-known ``RowLineageSegment`` values (attached to a ``ReadingRow``/
``ReadingCell`` at collection time, then carried through rendering by ``reading_text.py``) into the
versioned ``ReadingTextRowLineageMap`` schema shape, with row-local page offsets converted to
document-level raw offsets and each segment's already-computed, byte-verified ``status``
(``exact``/``normalized``/``merged``/``split``) passed straight through as its ``mapping_status``.
Unlike ``reading_text_geometry_projection.py``, there is no post-render search over unknown content
here at all.

The one exception is synthetic section headings (``reading_text.SYNTHETIC_HEADINGS`` — the closed,
enumerable set of literal strings ``reading_text.py`` itself inserts, e.g. ``"LEISTUNGEN"``): a
canonical gap between attributed segments whose stripped text exactly equals one of these known
constants is recognized as an ``"inserted"`` segment with no source range. This is not a text
search over unknown content — it recognizes exactly the fixed vocabulary this codebase itself
writes — so it stays within the "no guessing" discipline.

Coverage can still be partial: rendering paths that decline attribution (fused table headers,
layout-block ordering, spans dropped by the overlap sweep — see ``reading_text.py``) leave
canonical gaps this map does not cover. Callers should keep falling back to the geometry
projection / unique-token ``reading_text_map`` for those, and only for those.
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
from app.services.reading_text import SYNTHETIC_HEADINGS, RowLineageSegment

_REASON_ROW_CONSTRUCTION = "row_construction"
_REASON_IN_ROW_SPLIT = "in_row_split"
_REASON_SYNTHETIC_HEADING = "synthetic_heading"
_STATUS_CONFIDENCE = {"exact": 1.0, "normalized": 0.9, "split": 0.9, "merged": 0.85}


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
        # This should be unreachable given the collection-time discipline and overlap sweep in
        # ``reading_text.py``, but a document this module has never seen must never crash artifact
        # creation over an edge case that discipline missed -- decline the later segment instead.
        if any(
            raw_start < other_end and other_start < raw_end
            for other_start, other_end in claimed_raw_ranges
        ):
            continue
        claimed_raw_ranges.append((raw_start, raw_end))
        reason_codes = [_REASON_ROW_CONSTRUCTION]
        if row_segment.status == "split":
            reason_codes.append(_REASON_IN_ROW_SPLIT)
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
                mapping_status=row_segment.status,
                confidence=_STATUS_CONFIDENCE[row_segment.status],
                reason_codes=reason_codes,
                page_number=row_segment.page_number,
            )
        )
    if not segments:
        return None
    segments.extend(_synthetic_heading_segments(document_id, reading_text, segments))
    segments.sort(key=lambda segment: segment.canonical_start)
    return ReadingTextRowLineageMap(segments=segments, summary=_summary(reading_text, segments))


def _synthetic_heading_segments(
    document_id: str, reading_text: str, segments: Sequence[CanonicalTextSegmentV1]
) -> list[CanonicalTextSegmentV1]:
    """Recognize a canonical gap that is exactly a known synthetic heading, and only that.

    Not a text search: it checks a gap's stripped content against the closed, enumerable set of
    literal strings ``reading_text.py`` itself inserts. A gap containing anything else (a heading
    plus still-unattributed following content, for example) is left alone rather than guessed.
    """
    ordered = sorted(segments, key=lambda segment: segment.canonical_start)
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for segment in ordered:
        if segment.canonical_start > cursor:
            gaps.append((cursor, segment.canonical_start))
        cursor = max(cursor, segment.canonical_end)
    if cursor < len(reading_text):
        gaps.append((cursor, len(reading_text)))

    inserted: list[CanonicalTextSegmentV1] = []
    for gap_start, gap_end in gaps:
        gap_text = reading_text[gap_start:gap_end]
        stripped = gap_text.strip()
        if stripped not in SYNTHETIC_HEADINGS:
            continue
        offset = gap_text.index(stripped)
        start = gap_start + offset
        end = start + len(stripped)
        inserted.append(
            CanonicalTextSegmentV1(
                segment_id=_inserted_segment_id(document_id, start, end),
                canonical_start=start,
                canonical_end=end,
                source_range=None,
                segment_role="heading",
                mapping_status="inserted",
                confidence=1.0,
                reason_codes=[_REASON_SYNTHETIC_HEADING],
                page_number=None,
            )
        )
    return inserted


def _summary(
    reading_text: str, segments: Sequence[CanonicalTextSegmentV1]
) -> ReadingTextRowLineageSummary:
    # "Mapped" means raw-attributed: an "inserted" synthetic heading has no source range, so it
    # counts towards total_segments but not towards mapped/coverage -- it was never in raw text.
    mapped_chars = sum(
        segment.canonical_end - segment.canonical_start
        for segment in segments
        if segment.source_range is not None
    )
    total = len(reading_text)
    status_counts = {
        status: sum(segment.mapping_status == status for segment in segments)
        for status in ("exact", "normalized", "merged", "split", "inserted")
    }
    return ReadingTextRowLineageSummary(
        lineage_source="row_construction",
        total_segments=len(segments),
        canonical_char_count=total,
        mapped_canonical_char_count=mapped_chars,
        coverage_ratio=(mapped_chars / total) if total else 0.0,
        exact_segment_count=status_counts["exact"],
        normalized_segment_count=status_counts["normalized"],
        merged_segment_count=status_counts["merged"],
        split_segment_count=status_counts["split"],
        inserted_segment_count=status_counts["inserted"],
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


def _inserted_segment_id(document_id: str, canonical_start: int, canonical_end: int) -> str:
    material = f"{document_id}\x00inserted\x00{canonical_start}\x00{canonical_end}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]
