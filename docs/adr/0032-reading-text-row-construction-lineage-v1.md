# ADR-0032: Reading-text row construction lineage v1 (Phase 1, partial)

## Status

Accepted — 2026-07-10. Builds on [ADR-0016](0016-engine-maturity-levels-0-19.md),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md),
[ADR-0027](0027-ocr-output-contract-v1-strategy.md), and
[ADR-0031](0031-text-identity-anchor-lineage-architecture.md). Delivers a genuine, but partial,
slice of the "Phase 1 — construction-time lineage" gap identified in
[`text-anchor-architecture-feasibility-audit.md`](../engine/text-anchor-architecture-feasibility-audit.md)
and left open by the **Geometry-backed Reading Projection v1** corrective hardening pass.

## Context

Every existing raw↔canonical lineage mechanism before this change was **post-hoc**: it ran strictly
after `reading_text.py`'s builder already returned a finished string, then re-derived
correspondence by searching that finished string (`reading_text_map` at unique-token granularity,
`reading_text_geometry_projection.py` at full-line granularity). The feasibility audit named this
the architecture's biggest remaining structural gap: `reading_text.py`'s own `ReadingRow`/
`ReadingCell` primitives — which the builder already holds while rendering — carry no raw offsets at
all, so genuine construction-time lineage (the builder itself emitting `raw_span → reading_span`
while rendering, not a later search) remained unimplemented. A first attempt at this
(`anchor-first-text-package-v2`) was found by a contradiction audit to still be a post-render
projection in disguise; that attempt was reclassified and hardened as Geometry-backed Reading
Projection v1 instead.

`reading_text.py` (1,400+ lines) is a deterministic reordering transform: its entire value is taking
raw, sometimes visually-scrambled text (interleaved columns, tables, forms) and rendering it in human
reading order. That reordering is exactly why real construction-time lineage cannot be a thin
wrapper — it requires the builder's own row/cell objects to carry known raw offsets, and every
rendering path that merges, splits, or redistributes those objects to either preserve that knowledge
correctly or explicitly decline rather than mis-attribute it.

## Decision

Deliver construction-time lineage for the rendering paths where it can be attached and threaded
**without guessing**, and explicitly decline everywhere else, rather than attempt full-document
coverage in one step:

- **`ReadingRow` gains an optional `source_range: tuple[int, int] | None`** — a page-local, half-open
  raw offset span into `TextPageResult.text`. It is attached once, at collection time, before any
  rendering happens:
  - From persisted L10 span geometry (`_rows_from_geometry`), the range is already known exactly
    (`TextLineGeometry.page_start`/`page_end`) — no matching needed.
  - From the primary transient pypdf-visitor path (`collect_pdf_reading_rows`), a new
    `_match_row_source_ranges` pass matches each row's whitespace-collapsed text against the page's
    own raw lines (`text_geometry.segment_page_lines`/`collapse_line`, promoted to shared helpers),
    requiring **global uniqueness on both sides** — the row's text must be unique among this page's
    collected rows, its raw match must be the only raw line sharing that exact text, and no other row
    may claim the same raw line. Any ambiguity declines (`source_range` stays `None`) instead of
    picking by processing order — the same discipline the geometry projection hardening pass already
    established.
- **Only the plain-paragraph/body rendering path threads this lineage through** —
  `_join_continuations_with_flags` (reused by `_plain_blocks_with_flags`/`_body_blocks`'s fallback
  branch). A single untouched row passes its own range straight through; a wrap-continuation or
  adjacent label/value merge unions contributing rows' ranges **only when every row has one and raw
  order stays non-decreasing** (a visual merge of raw-reordered rows declines, so a merged envelope
  can never silently swallow an unrelated row's own range). Party columns, tables (keyword-header and
  generic), multi-column reconstruction, metadata rendering, and post-table rendering all
  redistribute or reformat cells and **always decline** (`None`) in this step — including the parts
  of those functions that reuse `_plain_blocks_with_flags` internally (e.g. a generic table's plain
  prefix before the detected table still gets real lineage; the table body and anything after it does
  not).
- **Canonical offsets are computed by walking the same block/line join arithmetic the text was
  assembled with** (`_join_blocks_with_lineage`, a byte-identical parallel to the existing
  `_join_blocks`) — never by searching the finished string. `build_reading_text` only keeps the
  resulting `row_lineage` when the exact per-page strings it was computed against are still the ones
  being joined into the final text (an equality check against a pre-filter snapshot); repeated-margin
  filtering, the whole-document layout-text fallback, or the raw-order fallback each discard row
  lineage entirely rather than risk offsets that no longer match a since-changed string.
- **New schema `ReadingTextRowLineageMap`** (`CanonicalTextLineageSource` gains `"row_construction"`)
  mirrors `ReadingTextGeometryProjectionMap`'s shape but is intentionally sparse and always
  `mapping_status="exact"`/`confidence=1.0` — there is no `ambiguous`/`inserted` state, because an
  uncertain path simply contributes no segment. `reading_text_row_lineage.py` converts the builder's
  `RowLineageSegment`s (page-local) into the schema's document-level raw offsets, with a defensive
  overlap skip (mirroring the existing pattern in `reading_text_geometry_projection.py`) so a
  document this module has never seen cannot crash artifact creation even if some edge case the
  collection-time uniqueness discipline missed produces a conflicting claim.
- **Preference order, most-trusted first:** `row_construction` (real, but sparse) →
  `geometry_projection` (fuller coverage, post-render) → `fallback_text_match`
  (`reading_text_map`) → `unavailable`. This applies to `DocumentTextPackageLineageSummary.lineage_source`,
  the Text Anchor Graph's per-token projection (`_project_canonical_range`, new
  `canonical_row_construction` flag/count), and `TextContent`/`DocumentTextPackageV1`'s new
  `reading_text_row_lineage_map[_version]` fields. Preferring `row_construction` never implies it
  alone covers the document — consumers needing full coverage still fall back to the weaker
  mechanisms for the spans this one leaves unattributed.

## Consequences

- Genuinely construction-time for the paths it covers: a row's raw range travels with the
  `ReadingRow` object itself from collection through rendering, so there is no possibility of the
  duplicate-value inversion defect class the geometry projection hardening pass had to fix — a
  merged/rendered line's lineage is either known because it was already known, or explicitly absent.
- **Deliberately partial.** Cell-level offsets are out of scope (only row-granularity provenance);
  party columns, tables, multi-column reconstruction, metadata, and post-table rendering carry no
  row-construction lineage at all yet, even though some of those paths (e.g. a keyword-header table's
  aligned body rows) could in principle support it with more work. A document with any repeated page
  margin gets no row-construction lineage at all. None of this is a regression: those spans simply
  fall back to the pre-existing `geometry_projection`/`fallback_text_match` mechanisms, unchanged.
- No detection, recognizer, active-PII-input, routing, `pii_result` schema, review-decision,
  pseudonymization, redaction, export, dependency, or database change. `text_result.text` stays the
  offset-stable authority; `reading_text` bytes are unchanged (proven by the full existing regression
  suite, including every synthetic golden-text fixture, passing byte-identical).
- The full existing test suite (845 tests) passes unchanged; two "simulate a legacy artifact"
  fixtures (`test_document_text_package.py`, `test_ocr.py`) were updated to also strip the two new
  additive field names, matching how every previous additive layer's rollout updated the same
  fixtures.

## Next

Extending real coverage to the table/party/multi-column paths, and eventually cell-level rather than
row-level granularity, remain open — to be re-scoped explicitly, the same way ADR-0022/0024/0025/0026
each re-scoped a level, rather than assumed complete. `pii-binding-quality-suite` and
`review-result-v1` remain the next two recommended branches from the feasibility audit after this
one.
