"""Geometry-backed reading projection (post-render; NOT construction-time lineage).

**Canonical Reading Text already exists, fully rendered, by the time this module runs.** It is
called from ``ocr_service._text_content`` *after* ``build_reading_text(...)`` has already returned a
finished string; this module never receives control from, and is never called by, the reading-text
builder (``reading_text.py``) itself. The builder's own per-fragment source knowledge
(``ReadingRow``/``ReadingCell``, which carry fractional page coordinates but no raw offsets) is
still discarded before this module ever sees anything — that gap is unchanged by this module and
remains open future work (the real ``anchor-first-text-package-v2``).

What this module actually does: it takes the OCR L10 ``text_geometry`` line boxes (an independently
computed, raw-line-level artifact — not something the reading-text builder consulted to decide
*this* rendering, only ever a fallback *input* to it) and **searches the already-completed canonical
string** for an exact, line-bounded occurrence of each raw geometry line's text. This is a post-hoc
projection, exactly like the pre-existing unique-token
``reading_text_projection.build_reading_text_map`` — the difference is granularity (whole verbatim
line vs. globally-unique whitespace token) and a stricter uniqueness requirement, not a difference
in *when* it runs relative to construction.

**Identity discipline (the reason this module exists as a hardened rewrite).** A textual occurrence
may be claimed as ``exact`` only when it is genuinely unresolvable any other way: the source line's
exact text must occur exactly once among the collected verbatim source lines, **and** exactly once
(line-bounded) in the canonical text. Processing/iteration order over source lines is *never* used
as identity evidence — an earlier version of this mechanism assigned duplicate full-line values to
canonical occurrences by cursor/encounter order alone, which is deterministic but not correct: the
same raw and canonical text can be bound in mutually-inverted ways depending only on the order
geometry lines are visited, with no way to tell which is right. Any line whose exact text is not
globally unique in this sense is marked ``ambiguous`` (a real raw correspondence exists, but which
canonical occurrence it is cannot be established) and gets **no** source range, no ``exact`` status,
and no ``confidence=1.0`` claim — this module declines rather than guesses.

Safety rules:

- **Only exact, known raw offsets are used** as candidates, from ``text_geometry`` line spans
  (``page_start``/``page_end`` into the immutable raw page text) — never invented.
- **A claim requires global uniqueness, not just a search hit.** A single ``str.find`` match is
  never sufficient by itself; the match must be the *only* line-bounded occurrence of that exact
  text in the canonical string, and the source line must be the *only* raw line with that exact
  text among those collected for this run.
- **Non-verbatim, reformatted, merged, or split lines decline** rather than invent a range.
- **Text-free.** Segments and reason codes carry canonical/raw offsets, ids, roles, statuses, and
  reason codes only — never copied source text, and never the duplicated value itself.

This is a stronger, more structured *post-hoc* mechanism than the pre-existing unique-token
``reading_text_map`` (full-line granularity, geometry-anchored raw offsets), which is why it is
*preferred* when it can resolve a line unambiguously. It is **not** authoritative construction
identity, and it is **not** a substitute for genuine builder-emitted construction-time lineage —
that remains a separate, unimplemented, future step (a real ``anchor-first-text-package-v2``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas import (
    CanonicalTextSegmentV1,
    CanonicalTextSourceRange,
    ReadingTextGeometryProjectionMap,
    ReadingTextGeometryProjectionSummary,
    TextGeometry,
    TextPageResult,
)

_SPACE_RUN_RE = re.compile(r"[ \t]+")

_REASON_EXACT = "geometry_line_projection"
_REASON_GAP = "geometry_projection_gap"
_REASON_DUPLICATE_SOURCE = "duplicate_source_value"
_REASON_MULTIPLE_CANDIDATES = "multiple_canonical_candidates"
_REASON_IDENTITY_AMBIGUOUS = "identity_ambiguous"
_REASON_ORDER_NOT_PROOF = "relative_order_not_identity_proof"


def build_reading_text_geometry_projection_map(
    *,
    document_id: str,
    reading_text: str | None,
    raw_text: str,
    pages: Sequence[TextPageResult],
    text_geometry: TextGeometry | None,
) -> ReadingTextGeometryProjectionMap | None:
    """Project raw geometry-line offsets onto the *already-completed* canonical text, or decline.

    Returns ``None`` (caller falls back to the post-hoc unique-token map) when there is no canonical
    text, no line geometry, or no geometry line could be resolved at all — safely or ambiguously —
    against the canonical text. This is a post-render projection: ``reading_text`` is a finished
    string by the time this function is called; nothing here is emitted by the reading-text builder.
    """
    if not reading_text or text_geometry is None:
        return None

    lines = [line for line in _source_lines(raw_text, pages, text_geometry) if line.verbatim]
    if not lines:
        return None

    mapped, ambiguous_entries = _resolve_segments(document_id, reading_text, lines)
    if not mapped and not ambiguous_entries:
        return None

    segments = _assemble_segments(document_id, reading_text, mapped, ambiguous_entries)
    return ReadingTextGeometryProjectionMap(
        segments=segments,
        summary=_summary(reading_text, segments),
    )


@dataclass(frozen=True)
class _SourceLine:
    """One raw line reduced to what projection needs: its normalized text, raw span, and page."""

    normalized: str
    raw_start: int
    raw_end: int
    verbatim: bool
    page_number: int


def _source_lines(
    raw_text: str, pages: Sequence[TextPageResult], text_geometry: TextGeometry
) -> list[_SourceLine]:
    pages_by_number = {page.page_number: page for page in pages}
    page_bases = _page_bases(pages)
    lines: list[_SourceLine] = []
    for geometry_page in text_geometry.pages:
        page = pages_by_number.get(geometry_page.page_number)
        base = page_bases.get(geometry_page.page_number)
        if page is None or base is None:
            continue
        for line in geometry_page.lines:
            raw_slice = page.text[line.page_start : line.page_end]
            normalized = _normalize(raw_slice)
            if not normalized:
                continue
            lines.append(
                _SourceLine(
                    normalized=normalized,
                    raw_start=base + line.page_start,
                    raw_end=base + line.page_end,
                    verbatim=raw_slice == normalized,
                    page_number=geometry_page.page_number,
                )
            )
    return lines


def _resolve_segments(
    document_id: str, reading_text: str, lines: Sequence[_SourceLine]
) -> tuple[list[CanonicalTextSegmentV1], list[tuple[int, int, list[str]]]]:
    """Group source lines by exact text; claim ``exact`` only for globally-unique lines.

    A line's exact text must occur exactly once among the collected verbatim source lines (this
    run's raw candidates) **and** exactly once, line-bounded, in the canonical text before it may
    be projected as ``exact``. Every other candidate occurrence of a non-unique value is returned
    as an explicit ambiguous entry instead of being picked by processing order — a duplicate raw
    line and a duplicate canonical occurrence are structurally indistinguishable from each other's
    swap, and order alone is never treated as identity proof.
    """
    groups: dict[str, list[_SourceLine]] = {}
    for line in lines:
        groups.setdefault(line.normalized, []).append(line)

    mapped: list[CanonicalTextSegmentV1] = []
    ambiguous_entries: list[tuple[int, int, list[str]]] = []
    used_raw: list[tuple[int, int]] = []
    for value, group in groups.items():
        candidates = _line_bounded_occurrences(reading_text, value)
        if len(group) == 1 and len(candidates) == 1:
            line = group[0]
            raw_span = (line.raw_start, line.raw_end)
            if _overlaps(raw_span, used_raw):
                # Defensive: never let two segments claim overlapping raw ranges (schema forbids
                # it); this should be unreachable given per-group uniqueness above.
                continue
            start, end = candidates[0]
            mapped.append(
                CanonicalTextSegmentV1(
                    segment_id=_segment_id(document_id, start, end, raw_span),
                    canonical_start=start,
                    canonical_end=end,
                    source_range=CanonicalTextSourceRange(
                        start=line.raw_start, end=line.raw_end, source_role="body"
                    ),
                    segment_role="body",
                    mapping_status="exact",
                    confidence=1.0,
                    reason_codes=[_REASON_EXACT],
                    page_number=line.page_number,
                )
            )
            used_raw.append(raw_span)
            continue
        if not candidates:
            # Neither this mechanism's raw duplicate(s) nor its canonical search found a
            # line-bounded home; nothing to mark ambiguous about in canonical space either.
            continue
        reasons = [_REASON_IDENTITY_AMBIGUOUS, _REASON_ORDER_NOT_PROOF]
        if len(group) > 1:
            reasons.append(_REASON_DUPLICATE_SOURCE)
        if len(candidates) > 1:
            reasons.append(_REASON_MULTIPLE_CANDIDATES)
        for start, end in candidates:
            ambiguous_entries.append((start, end, reasons))
    return mapped, ambiguous_entries


def _line_bounded_occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Every occurrence of ``value`` in ``text`` that is delimited by ``\\n`` (or string edges).

    A plain substring search would let a short whole-line value (e.g. ``"Wien"``) falsely match
    *inside* a longer, unrelated line (e.g. ``"1010 Wien"``); this boundary check rejects that.
    """
    occurrences: list[tuple[int, int]] = []
    start = 0
    while True:
        position = text.find(value, start)
        if position < 0:
            break
        end = position + len(value)
        before_ok = position == 0 or text[position - 1] == "\n"
        after_ok = end == len(text) or text[end] == "\n"
        if before_ok and after_ok:
            occurrences.append((position, end))
        start = position + 1
    return occurrences


def _overlaps(span: tuple[int, int], others: Sequence[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in others)


def _assemble_segments(
    document_id: str,
    reading_text: str,
    mapped: Sequence[CanonicalTextSegmentV1],
    ambiguous_entries: Sequence[tuple[int, int, list[str]]],
) -> list[CanonicalTextSegmentV1]:
    """Merge exact and ambiguous segments in canonical order, filling remaining gaps as inserted.

    Every canonical character is then classified into exactly one of three states: attributed to a
    uniquely-resolved raw source line (``exact``), attributed to a real-but-unresolvable raw
    correspondence (``ambiguous``, never a copied value), or genuinely without any raw
    correspondence at all (``inserted`` — a separator, join, or synthetic heading the renderer
    added).
    """
    ambiguous_segments = [
        CanonicalTextSegmentV1(
            segment_id=_segment_id(document_id, start, end, None),
            canonical_start=start,
            canonical_end=end,
            source_range=None,
            segment_role="body",
            mapping_status="ambiguous",
            reason_codes=list(reasons),
        )
        for start, end, reasons in ambiguous_entries
    ]
    combined = sorted([*mapped, *ambiguous_segments], key=lambda segment: segment.canonical_start)
    result: list[CanonicalTextSegmentV1] = []
    cursor = 0
    for segment in combined:
        if segment.canonical_start > cursor:
            result.append(_inserted_segment(document_id, cursor, segment.canonical_start))
        result.append(segment)
        cursor = segment.canonical_end
    if cursor < len(reading_text):
        result.append(_inserted_segment(document_id, cursor, len(reading_text)))
    return result


def _inserted_segment(document_id: str, start: int, end: int) -> CanonicalTextSegmentV1:
    return CanonicalTextSegmentV1(
        segment_id=_segment_id(document_id, start, end, None),
        canonical_start=start,
        canonical_end=end,
        source_range=None,
        segment_role="derived",
        mapping_status="inserted",
        reason_codes=[_REASON_GAP],
    )


def _summary(
    reading_text: str, segments: Sequence[CanonicalTextSegmentV1]
) -> ReadingTextGeometryProjectionSummary:
    mapped = [segment for segment in segments if segment.mapping_status == "exact"]
    ambiguous = [segment for segment in segments if segment.mapping_status == "ambiguous"]
    inserted = [segment for segment in segments if segment.mapping_status == "inserted"]
    mapped_chars = sum(segment.canonical_end - segment.canonical_start for segment in mapped)
    total = len(reading_text)
    return ReadingTextGeometryProjectionSummary(
        lineage_source="geometry_projection",
        total_segments=len(segments),
        mapped_segments=len(mapped),
        ambiguous_segments=len(ambiguous),
        inserted_segments=len(inserted),
        canonical_char_count=total,
        mapped_canonical_char_count=mapped_chars,
        coverage_ratio=round(mapped_chars / total, 6) if total else 0.0,
        reason_codes=[_REASON_EXACT],
    )


def _page_bases(pages: Sequence[TextPageResult]) -> dict[int, int]:
    """Document-level base offset of each page (pages joined by ``\\n\\n`` in the raw text)."""
    bases: dict[int, int] = {}
    base = 0
    for page in pages:
        bases[page.page_number] = base
        base += len(page.text) + 2
    return bases


def _normalize(text: str) -> str:
    return _SPACE_RUN_RE.sub(" ", text.strip())


def _segment_id(
    document_id: str, canonical_start: int, canonical_end: int, raw_span: tuple[int, int] | None
) -> str:
    raw_part = f"{raw_span[0]}\x00{raw_span[1]}" if raw_span is not None else "none"
    material = f"{document_id}\x00{canonical_start}\x00{canonical_end}\x00{raw_part}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]
