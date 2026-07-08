# ADR-0025: OCR L14 is quality evidence and lineage coverage

## Status

Accepted — 2026-07-08. Builds on [ADR-0016](0016-engine-maturity-levels-0-19.md),
[ADR-0018](0018-ocr-pii-implementation-plan.md),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md),
[ADR-0022](0022-ocr-l12-multi-column-layout-reconstruction.md), and
[ADR-0024](0024-ocr-l13-table-form-reconstruction-v2.md), which re-scoped L12 and L13 the same way
this ADR re-scopes L14.

## Context

OCR/Text reached L13: technical raw text, canonical `reading_text` with multi-column and table/form
reconstruction, `text_geometry`, `structured_content`, and a conservative `reading_text_map` all
exist. What is missing is a way to *measure and explain* that chain. For any given artifact we could
not answer, from the artifact alone:

- Where did this text come from — PDF text layer, OCR, or fallback?
- Was page position/geometry known? Was a region header/footer/body/margin-like?
- Which parts were confidently reconstructed (table/form/multi-column) and which fell back?
- How much of the canonical reading text maps back to technical raw text and to source geometry?
- Which ranges can (or cannot yet) safely support PII projection?

The metrics-only `quality_report` (L7) answers *routing/confidence* questions (source mix, audit
quality counts, OCR confidence) but says nothing about reading-text reconstruction or lineage
coverage, and it is lineage-bound and consumed by the benchmark, so widening it would risk
benchmark-payload drift.

The older planning placeholder described OCR/Text L14 as "local AI assist for hard pages" — a local
vision/OCR model behind an adapter. That is a materially larger capability (a dependency, a model,
an assist-promotion workflow) with no immediate product or benchmark signal justifying it yet, while
the quality/observability gap above is bounded, additive, and directly needed before any correction,
multi-OCR, dictionary, or local-LLM work can be prioritized on evidence rather than guesswork.

## Decision

- Re-scope OCR/Text L14 to **quality evidence and lineage coverage**, mirroring how ADR-0022 and
  ADR-0024 re-scoped L12/L13. Local AI assist is deferred to a later level, to be re-scoped
  explicitly when a concrete need justifies it.
- Add an additive, optional, versioned `quality_evidence` field (and `quality_evidence_version`) on
  `text_result.content` (Option A — the same additive shape as `reading_text`, `text_geometry`, and
  `structured_content`). No new artifact, no `quality_report` change, no benchmark-payload change.
  Legacy artifacts without the field remain valid.
- The model is a flat list of `QualityEvidenceItem`s plus a `QualityEvidenceSummary`:
  - each item has a stable `evidence_id`, a `level`, a `type`, a `status`, an optional bounded
    `confidence`, a stable `reason_code`, optional offset ranges / page number / page zone / coarse
    bounds / `related_artifact`, non-sensitive `flags`, and a **`details: dict[str, int]`** map;
  - the summary rolls up `overall_status`, an advisory `overall_score`, status/type counts,
    `warnings`, `blockers`, `reconstruction_summary`, `fallback_summary`, and a
    `QualityLineageCoverage` block (reading-text length, mapped/unmapped chars, mapping coverage
    ratio, exact/partial/unmapped span counts, source-geometry coverage, structured-content
    reference count).
- Build it deterministically from already-computed inputs (source, pages, reading result and its
  flags, the reading↔raw map, span geometry, and structured content). It re-runs nothing and guesses
  nothing: absent signals are classified `unavailable`/`not_applicable`, not invented.
- **Privacy by construction:** no evidence field carries raw document text. Locators are offsets,
  counts, flags, page zones, coarse bounds, and stable reason codes; `details` is integer-only so a
  snippet or PII value cannot be stored there even by mistake. The schema validates that evidence
  offsets stay within the actual raw/reading text and that summary counts match the items.
- **Page zones** (`header`/`footer`/`left_margin`/`right_margin`/`body`/`unknown`) are derived
  conservatively from existing geometry and are **evidence only**: they never delete, reorder, or
  reclassify text, and never encode a document-specific layout.
- Preserve every ADR-0019 boundary: technical raw `text_result.text` and `pages[].text` stay
  byte-stable, PII still runs only on technical raw text, PII projection/decisions are unchanged, and
  no pseudonymization, redaction, reconstruction/export, dictionary, multi-OCR, or LLM behavior is
  added. Evidence signals never change PII decisions.

## Future evidence sources

The model is designed so later signals plug in as additional evidence items without changing the
schema or any text layer. All are **evidence, not truth** — they may raise or lower confidence but
must never silently rewrite OCR/Text or change PII decisions:

- **Dictionary / lexicon:** an OCR-quality signal for suspicious non-word tokens and common OCR
  confusions (O/0, I/1/l, broken spacing). Not a hard correction, not a name/person truth source,
  not used to remove text, and separate from any PII lexicon.
- **Multi-OCR:** only worthwhile once current error classes are measured — useful if
  character-recognition errors dominate, not if the real problems are layout/mapping/tables/geometry.
  An agreement score is one evidence signal, not a decision.
- **Local LLM:** an optional helper for document type, section labels, structure suggestions, or a
  human-readable quality explanation. Never a source of truth, never allowed to silently rewrite OCR
  text, and never required for the local deterministic pipeline.
- Per-token OCR confidence, PDF-text-layer-versus-OCR comparison, and review feedback are further
  additive evidence signals.

## Validation

Synthetic unit tests cover normal, empty, fallback, table, form, multi-column, structured-content,
page-zone (header/footer/body/margins, conservative), determinism, offset/coverage bounds, and a
"no raw text in metadata" guard, plus lineage tests for exact/partial/unmapped ranges, coverage
ratio, source-geometry coverage, and synthetic/derived text never counting as source-mapped. A
local, metrics-only private-corpus pass (never committed; `.local` outputs only) confirmed that
every text-layer document produced coherent evidence with no genuine text leak, and that
`reading_text`/`structured_content`/technical raw text are byte-identical to before (L14 touches no
text builder). Scanned/image documents with no text layer are correctly reported as `unavailable`
pending the OCR runtime — a pre-existing limitation, not an L14 regression.

## Consequences

- Every new OCR/Text artifact can explain its own provenance, reconstruction, and lineage coverage,
  and stable documents can be regression-checked on measurable signals rather than eyeballed diffs.
- The `quality_report` artifact and the benchmark are untouched; the benchmark loader continues to
  ignore text-artifact payload it does not read.
- Local AI assist for hard pages remains explicitly open and deferred, avoiding the
  placeholder-mixing risk ADR-0022/ADR-0024 called out for L12/L13.

> Migration note: earlier planning placeholders described OCR/Text L14 as local AI assist for hard
> pages. That capability is deferred to a later level once a concrete need justifies it. L14 now
> means the quality evidence and lineage coverage described here; this avoids mixing the older
> placeholder meaning with the active 0–19 engine level.
