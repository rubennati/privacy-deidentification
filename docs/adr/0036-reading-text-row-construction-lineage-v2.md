# ADR-0036: Reading-text row construction lineage v2 (Phase 2 — anchor-first text package)

## Status

Accepted — 2026-07-11. Builds on [ADR-0031](0031-text-identity-anchor-lineage-architecture.md) and
[ADR-0032](0032-reading-text-row-construction-lineage-v1.md), which delivered "Phase 1, partial":
genuine, builder-emitted (not post-render) raw↔canonical lineage, but only for the
plain-paragraph/body rendering path. ADR-0032's own "Next" section named the remaining rendering
paths explicitly: *"Extending real coverage to table cells, party/multi-column paths, metadata, and
joined post-table prose ... remains open and must be re-scoped explicitly rather than assumed
complete."* This ADR re-scopes and delivers that extension (branch
`anchor-first-text-package-v2`).

## Context

Phase 1 proved the concept — a raw span attached to a `ReadingRow` at collection time, threaded
through rendering, never searched for afterward — but the plain-paragraph/body path is only one of
several rendering strategies in `reading_text.py`. Every other path (party/two-column heading
grouping, keyword-header and generic geometric tables, metadata/offer-field rendering, multi-column
prose reconstruction, in-row label/value splitting) still contributed no lineage at all, leaving
most real-world business documents — which use these structures constantly — dependent on the
post-hoc `reading_text_geometry_projection.py`/`reading_text_map` fallback tiers for their canonical
highlights. The recently-fixed cross-view highlight bug for a multi-word organisation containing a
repeated interior token (`pii-canonical-highlight-consistency-fix`) was itself a symptom of relying
on those fallback tiers' weaker, value-based reasoning; construction-time lineage sidesteps the
problem at its root by knowing a row's provenance from position, not text content.

## Decision

Extend builder-emitted row lineage to every rendering path where a resulting canonical line's
provenance is honestly knowable, and make the schema and downstream layers honestly distinguish
*how* it is known, rather than collapsing everything to `"exact"`:

- **`RowLineageSegment` gains a `status: "exact" | "normalized" | "merged"`**, computed purely from
  already-known lengths (never by comparing text content) at the one place text and offsets are
  joined (`_join_blocks_with_lineage`): a single untouched row whose rendered line is byte-identical
  to its raw span is `"exact"`; a single row reformatted into different-length output (e.g. `"col |
  col | col"` table syntax) is `"normalized"`; a wrap continuation or adjacent label/value pairing
  that unions *more than one* row's own range is `"merged"`.
- **Party/two-column heading grouping** (`_party_columns`) now preserves a reordered row's own
  range when a row's cells land wholly on one side (a genuine whole-row reorder); a row whose cells
  split across both sides (e.g. a shared two-party heading row) still declines, since attributing
  either resulting fragment would require guessing a sub-row raw boundary.
- **Keyword-header and generic geometric tables** (`_render_table`, `_generic_table_blocks`, shared
  via `_extend_aligned_table_rows`) now attribute row-granularity lineage per rendered table line: a
  non-fused header and each non-continuation body row keep their own row's range (`"normalized"`,
  since `" | "` separators change length); a multiline continuation row unions with its owning row's
  range (`"merged"`). A *fused* header (1–2 raw cells regex-split into 3+ labels) still declines —
  no single label owns a specific raw sub-span.
- **Metadata/offer-field rendering** (`_render_metadata`) now attributes lineage to a row that
  renders as exactly one line; a row `_split_paired_labels` splits into several fused `"Label:
  value"` fields still declines for all of them (a genuine in-row split, same reasoning as the
  table's fused header).
- **Synthetic section headings** (`"ANGEBOT"`/`"LEISTUNGEN"`/`"SUMMEN"` — the closed, enumerable set
  of literal strings this module itself inserts, shared as `reading_text.SYNTHETIC_HEADINGS`) are
  now recognized as explicit `"inserted"` segments (no source range) by
  `reading_text_row_lineage.py`, when a canonical gap's stripped text is *exactly* one of them. This
  is not a text search over unknown content — it checks a fixed, code-owned vocabulary — so it stays
  inside the "no guessing" discipline while making an intentional non-source span explicit instead
  of an unexplained gap.
- **Multi-column prose reconstruction and in-row label/value splitting** (`_multi_column_blocks`,
  `_paired_cell_lines`) remain deliberately fallback-only and are now documented as such rather than
  simply unimplemented: multi-column reconstruction can split a single source row's cells across
  *different* synthesized column rows (not just reorder whole rows), so no synthesized row can
  safely inherit a whole row's range without risking a double-claim; an in-row label/value split has
  the same unknowable-sub-row-boundary problem as a fused table header or metadata field.
- **`ReadingTextRowLineageMap`'s validator** now accepts `exact`/`normalized`/`merged`/`inserted`
  (previously only `exact`) — an inserted segment must carry no source range, every other status
  still requires one, and non-overlapping-raw-range ordering is unchanged.
- **`document_text_anchors.py`'s row-lineage adapter** no longer hardcodes `mapping_status="exact"`
  regardless of a segment's real status (a latent bug Phase 1 left as dead code, since every segment
  really was `"exact"` until this PR) — it now honestly maps `"exact"` to `"exact"` and anything else
  to `"normalized"`, mirroring the existing geometry-projection adapter's convention exactly
  (`ReadingTextMapSegment` has no separate `"merged"` state).

An unexpected but welcome consequence: because a fully attributed, exact-length table/metadata/party
row now supplies genuine per-token arithmetic projection (via the existing
`document_text_anchors.py` single-relevant-segment fast path), a multi-word entity whose row is
covered by construction-time lineage no longer needs the boundary-bridging fallback the previous PR
added for the post-hoc mechanisms at all — the repeated-interior-token problem simply does not arise
when identity comes from position rather than value search. The boundary-bridging fix remains
necessary and unchanged for content that still falls through to the post-hoc tiers.

## Consequences

- Table/party/metadata rendering — extremely common in real business documents — now gets genuine
  construction-time canonical ranges instead of depending on post-render search.
- Still deliberately partial: multi-column prose reconstruction, in-row label/value/table-header
  splits, and any document where repeated-page-margin filtering or a whole-document fallback
  invalidates row lineage (unchanged from Phase 1) keep falling back to
  `geometry_projection`/`fallback_text_match`, unchanged.
- Cell-level granularity remains out of scope; this is still row-granularity provenance.
- No detection, active-PII-input, routing, schema-breaking, pseudonymization, redaction, export, or
  dependency change. `reading_text` bytes are unchanged — proven byte-identical across the full
  existing regression suite (907 backend tests passing, including every synthetic golden-text
  fixture).
- PII detection semantics and frontend string handling required no changes: the entity contract
  benefits automatically because anchors now receive reliable canonical ranges from a lower layer.

## Next

Cell-level granularity (rather than row-level) and genuine construction-time lineage for
multi-column prose remain open and must be re-scoped explicitly, matching how this ADR re-scoped
Phase 1's own "Next" section rather than assuming it complete.
