# ADR-0040: Construction-time canonical lineage v3 — cell identity, extraction offsets, honest statuses

## Status

Accepted — 2026-07-12. Builds on [ADR-0031](0031-text-identity-anchor-lineage-architecture.md),
[ADR-0032](0032-reading-text-row-construction-lineage-v1.md) (Phase 1: row-granularity lineage on
the plain-paragraph/body path), and
[ADR-0036](0036-reading-text-row-construction-lineage-v2.md) (Phase 2: row-granularity coverage of
party columns, tables, metadata, post-table totals, `inserted` synthetic headings). ADR-0036's own
"Next" section named the remaining gaps explicitly: *"Cell-level granularity (rather than
row-level) and genuine construction-time lineage for multi-column prose remain open and must be
re-scoped explicitly."* This ADR re-scopes and delivers that step (branch
`anchor-first-text-package-v2`), making construction-time lineage the preferred identity boundary
of the Canonical Reading Text product rather than a partial optimization over post-hoc search.

## Context

After ADR-0036, three structural weaknesses remained:

1. **Cell identity was discarded at collection time.** `_group_fragments` unioned per-fragment raw
   ranges into a row-level `ReadingRow.source_range` and threw the per-fragment ranges away, so
   every rendering step that divides a row (in-row label/value splits, fused metadata fields,
   multi-column cell redistribution, party cells split across columns) had provably no identity to
   attribute and declined.
2. **The primary pypdf path depended on text uniqueness.** The visitor collector never learned raw
   offsets, so `_match_row_source_ranges` attached row ranges by globally-unique text matching —
   meaning a *repeated* value (the same company line in header and body) lost construction identity
   merely because its text was not unique, exactly the failure class the whole anchor architecture
   exists to eliminate.
3. **`exact` was a length claim, not a byte claim.** `_join_blocks_with_lineage` inferred `exact`
   from length equality; a bullet substitution (`"• "` → `"- "`) preserves length while changing
   bytes, quietly overstating identity precision.

## Decision

### 1. Cell-level source identity, attached at collection time

`ReadingCell` gains an optional page-local `source_range`, populated before any rendering:

- **pypdf text-layer pages — extraction-offset capture.** pypdf's extracted page text *is* the
  in-order concatenation of the text chunks the extraction visitor receives. The row collector now
  accumulates a cursor over every visitor chunk, giving each fragment its exact raw offset **from
  the extraction process itself** — no text search and no uniqueness requirement, so repeated
  values keep distinct identities. Because the stored raw text came from a separate
  `extract_text()` call, the concatenation is **byte-verified** against it before any offset is
  trusted; on mismatch (e.g. future pypdf drift) every extraction offset is discarded and the old
  globally-unique row matching remains as the explicit fallback (which now also refuses to claim a
  raw line already covered by another row's extraction offsets).
- **Geometry pages (OCR/persisted L10).** Each fragment keeps its own geometry line's span
  (whitespace-stripped) on its cell instead of only contributing to the row union.

`ReadingRow.source_range` stays the union of its fragments (unchanged semantics).

### 2. Previously-declining rendering paths now attribute honestly

- **In-row label/value splits** (`_paired_cell_lines`): each output line owns the union of exactly
  its two cells' ranges; if any cell lacks a range or the sibling unions are not strictly
  raw-ordered, *all* of the row's lines decline together (deterministically, never by position).
- **Party columns**: a row whose cells split across both sides (the shared two-party heading row)
  or contribute several cells to one side attributes each rendered line exactly its own cell.
- **Fused metadata rows** (`_split_paired_labels`): when every split-part boundary coincides with a
  cell boundary — established by walking the same cell-join arithmetic the row text was built with —
  each part owns its cells; a boundary inside one fused cell still declines all parts.
- **Multi-column prose**: a synthesized column row carries the union of exactly its own
  contributing cells' ranges (never the whole source row's range), so redistributed cell runs and
  their wrap merges attribute like any other line.
- **Raw-order fallback** (`_render_fallback_text` path, used for DOCX and other minimal inputs):
  the builder walks the raw string itself while rendering one output line per raw line, so every
  fallback line — including repeated ones — gets construction lineage from plain cursor
  arithmetic. (The whole-document and layout-text fallbacks still emit none: the former is guarded
  by the existing "pages changed after lineage was computed" invalidation, the latter renders a
  different string than raw.)

Fused table headers (regex-split sub-cell labels) and the layout-block path still decline —
explicit, documented gaps that fall through to the post-hoc fallbacks.

### 3. Byte-verified statuses, including `split`

At the single point where text and offsets join, each attributed line is compared byte-for-byte
against the raw span it claims (verification of a known correspondence, never a search for one):
`exact` now means byte-identical; a whole-row rendering with changed bytes is `normalized`; a
sub-row (cells) attribution with changed bytes is the new **`split`** status; a multi-row union
stays `merged`. `ReadingTextRowLineageMap` bumps to `map_version: "2"` (legacy `"1"` maps stay
readable; `TextContent` cross-checks that the version fields agree), the map summary gains additive
per-status counts, and split segments carry an `in_row_split` reason code.

### 4. Deterministic, symmetric overlap sweep

Reading order can interleave sources (multi-column prose): a wrap-merge envelope inside one column
can legitimately contain raw text the other column maps precisely. A document-level sweep
(`_resolve_raw_overlaps`) drops every conflicted `merged` envelope first (precise claims win), then
drops both sides of any remaining precise-vs-precise conflict — set-based, independent of
processing order, so the same input always resolves to the same survivors. Cursor order is never
identity evidence, matching the discipline ADR-0032/the geometry-projection rewrite established.

### 5. Fallbacks are explicitly demoted, not removed

The Text Anchor Graph already preferred `row_construction` over `geometry_projection` over
`fallback_text_match` per token; that preference now rides on far broader construction coverage,
and module/schema documentation states plainly that the post-hoc mechanisms are degraded fallback
identity for exactly the spans construction declines. Per-anchor flags
(`canonical_row_construction` / `canonical_geometry_projection` / `canonical_map_lineage`) keep the
mechanisms unconfusable; the anchor adapter maps only byte-verified `exact` segments to the exact
status that permits sub-token arithmetic projection.

## Consequences

- Repeated values, repeated suffixes, in-row label/value fields, fused two-cell metadata rows,
  multi-column prose, and minimal (DOCX-style) inputs now carry construction-time canonical
  identity end to end — package → anchor graph → PII binding → entity contract — without any
  string matching, and the `text_match` display fallback's retirement condition named by the
  feasibility audit is met for these spans.
- `reading_text` output bytes are unchanged on every path (proven by the untouched golden-text
  suite); this branch changes identity metadata only.
- Privacy is unchanged by construction: lineage segments carry offsets, statuses, reason codes,
  counts, and page numbers — never document text (leak-tested including the new statuses).
- The overlap sweep means an interleaved-column wrap merge loses lineage rather than lying; those
  spans keep resolving through the explicit fallbacks.
- No detection, active-PII-input, routing, recognizer, pseudonymization, redaction, export, or
  dependency change. PII detection semantics are untouched; the entity contract benefits purely
  through stronger anchors.

## Next

Fused-table-header sub-cell attribution and layout-block-path lineage remain open and must be
re-scoped explicitly if ever needed; the post-hoc mechanisms stay in place as their fallback. Any
retirement of the unique-token `reading_text_map` should be measured against real coverage data
first (it still serves legacy artifacts and the declined spans above).
