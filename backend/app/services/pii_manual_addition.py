"""Reverse canonical-to-raw span projection for manual PII additions (PII L14, ADR-0035).

Every existing projection in this codebase is raw-indexed: it takes a raw span and reads off a
canonical range (``pii_anchor_binding.py``, ``reading_text_projection.py``). A reviewer adding a
missed entity selects a span in the canonical reading-text view instead, so the direction needed is
canonical-in / raw-out — no such function existed before this module (confirmed during ADR-0035's
scoping audit).

This is deliberately *not* a new matching heuristic. The Text Anchor Graph (ADR-0031 Phase B)
already pairs a raw range and a canonical range together on the same anchor whenever both sides
were resolved at graph-construction time (preferring row-construction lineage, then geometry
projection, then the older ``reading_text_map`` — see ``document_text_anchors.py``). This module
only filters that existing pairing by the canonical side instead of the raw side, mirroring the
exact ``next(r for r in anchor.source_ranges if r.source_name == ...)`` pattern
``pii_anchor_binding.py`` already uses for the forward direction.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from app.schemas import DocumentTextAnchorGraphV1, DocumentTextAnchorSourceName, TextArtifact
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package

_RAW_SOURCE: DocumentTextAnchorSourceName = "technical_raw_text"
_CANONICAL_SOURCE: DocumentTextAnchorSourceName = "canonical_reading_text"

RawProjectionStatus = Literal["exact", "partial", "unmapped"]


def resolve_canonical_span_to_raw(
    text_artifact: TextArtifact, canonical_start: int, canonical_end: int
) -> tuple[tuple[int, int] | None, RawProjectionStatus]:
    """Best-effort reverse projection: canonical offsets in, a raw offset range out.

    Builds the same Text Anchor Graph the forward (raw-to-canonical) binding path already builds per
    request (``pii_entity_contract.py``'s ``_anchor_graph``) — no caching, consistent with that
    existing per-request cost, not a new performance pattern.
    """
    package = build_document_text_package(text_artifact)
    graph = build_document_text_anchor_graph(package)
    return _resolve_from_graph(graph, canonical_start, canonical_end)


def _resolve_from_graph(
    graph: DocumentTextAnchorGraphV1, canonical_start: int, canonical_end: int
) -> tuple[tuple[int, int] | None, RawProjectionStatus]:
    overlapping: list[tuple[int, int, int, int]] = []
    for anchor in graph.anchors:
        canonical_range = next(
            (r for r in anchor.source_ranges if r.source_name == _CANONICAL_SOURCE), None
        )
        if canonical_range is None:
            continue
        if canonical_range.start >= canonical_end or canonical_range.end <= canonical_start:
            continue
        raw_range = next((r for r in anchor.source_ranges if r.source_name == _RAW_SOURCE), None)
        if raw_range is None:
            continue
        overlapping.append(
            (canonical_range.start, canonical_range.end, raw_range.start, raw_range.end)
        )

    if not overlapping:
        return None, "unmapped"

    overlapping.sort(key=lambda item: item[0])
    cursor = canonical_start
    canonical_gap = False
    for canon_start, canon_end, _raw_start, _raw_end in overlapping:
        if canon_start > cursor:
            canonical_gap = True
            break
        cursor = max(cursor, canon_end)
    covers_canonical = not canonical_gap and cursor >= canonical_end

    raw_sorted = sorted(overlapping, key=lambda item: item[2])
    raw_gap = any(current[2] > previous[3] for previous, current in pairwise(raw_sorted))

    raw_start = min(item[2] for item in overlapping)
    raw_end = max(item[3] for item in overlapping)

    if covers_canonical and not raw_gap:
        return (raw_start, raw_end), "exact"
    return (raw_start, raw_end), "partial"
