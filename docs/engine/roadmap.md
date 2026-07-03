# Engine Roadmap

OCR/Text and PII/Sensitive-Data are the product core. Review, benchmark, storage, and later
redaction support those engines. All current planning uses the cumulative **0–19 maturity scale**;
historical level numbers remain only in ADRs and the legacy mapping sections of the per-engine
documents.

## Current standing

| Engine | Current level | Delivered | Next |
| --- | --- | --- | --- |
| OCR / Text | **L11 (built on the required L10.5 step)** | L10 geometry, versioned canonical `reading_text` (legacy `text` remains technical raw/PII offset basis), plus additive span-backed `structured_content` tables, fields, and sections | PII L12 overlap resolution |
| PII / Sensitive-Data | **L11; L10 partial** | profiles, Presidio/spaCy integration, AT/DE and domain recognizers, benchmark, candidate validation, context hardening, address/contact-line coverage, reproducible settings; dev-only feedback capture; derived entity grouping + a review-decision overlay | L12 overlap resolution |
| Review / Human-Feedback | **L2 production; L3–L5 dev-only; L6 done; L7–L9 partial** | read-only review and lineage-safe highlights; gated review aids, run settings, per-entity feedback capture; grouped occurrences + a lineage-bound decision overlay ([ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) | formal `review_result` artifact, stale-decision flag, manual add (L10) |
| Benchmark / Regression | **L8; L10 slice out of order** | coverage, routing, PII P/R/F1, privacy guard, determinism, validation counts, OCR confidence/coverage columns | L9 per-profile metrics |
| Redaction / De-Identification | **L0** | detection-only by design | blocked on stable PII, binding review, and OCR geometry |

## Delivered foundation

- OCR L0–L11 (built on the required L10.5 step): upload, technical raw extraction/lineage, OCR
  runtime, quality routing/fallback, additive OCR confidence, an immutable metrics-only
  `quality_report` for every successful run, additive readable/layout views plus deterministic typed
  layout blocks for PDF and OCR content, and additive `text_geometry` line boxes mapping raw offset
  spans to page-local geometry (source anchoring and traceability for review/debug, and a foundation
  for future placeholder mapping toward AI-ready pseudonymized document generation — it does not
  perform pseudonymization, placeholder mapping, document export, or pixel-perfect visual
  redaction), plus canonical `reading_text` as the deterministic block-aware main document view and
  conservative span-backed tables, label/value fields, and sections in optional
  `structured_content`. PII still uses raw text.
- PII L0–L9: structured and model-backed detection, named profiles, AT/DE/domain coverage,
  benchmark measurement, candidate validation, context hardening, address/contact-line coverage,
  and reproducible run settings.
- PII L10 / Review L5 partial: gated, append-only per-entity feedback capture for local analysis.
  This is not a binding `review_result` and does not alter detection.
- PII L11 / Review L6: conservative, derived entity grouping (`pii_grouping.py`, no schema change to
  `pii_result`) plus a lineage-bound review-decision overlay (`pseudonymize/keep/ignore/false_positive`
  at group or occurrence scope), covering much of Review L8/L9's practical intent without yet being
  the formal `review_result` artifact model. See
  [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).
- Benchmark L0–L8 plus an out-of-order L10 slice: private inputs, artifact matching, routing and PII
  metrics, privacy guarding, deterministic output, validation-stage aggregates, and safe
  lineage-matched OCR confidence/coverage columns.

## Current sequence

### 1. Repository foundation cleanup — documentation only

- **Goal:** make the 0–19 model, repository state, API/storage documentation, and next-step ordering
  consistent before further engine work.
- **Maturity change:** none.
- **Non-scope:** runtime behaviour, dependencies, recognizers, feedback logic, benchmark logic, and
  redaction.

### 2. Feedback integrity hardening — no new level

- **Goal:** make the existing dev-only PII L10 / Review L5 capture reliable before building on its
  data.
- **Scope:** validate submitted entity fingerprints against the referenced `pii_result`, preserve
  exact lineage, and verify feedback restore/lock behaviour in the UI.
- **Non-scope:** binding review decisions, learning, global rules, or a `review_result`.

### 3. OCR/PII implementation plan — planning checkpoint

- **Goal:** define the small PR sequence and acceptance fixtures for OCR L6/L7 and later PII
  L11/L12 work.
- **Required outputs:** artifact fields, privacy boundaries, adapter contracts, benchmark changes,
  and tests for each level.
- **Maturity change:** none.

### 4. OCR L6 — confidence capture — delivered

- **Goal:** capture engine-reported OCR confidence per OCR page and, where available, per line.
- **Scope:** PaddleOCR adapter output, additive text-page metrics, benchmark consumption, and
  synthetic tests.
- **Non-scope:** routing changes, `quality_report`, text reflow, geometry, tables, or a new OCR tool.
- **Dependency:** none; confidence is already present in the PaddleOCR payload.
- **Acceptance:** every OCR page carries a documented confidence value; canonical text and routing
  remain unchanged; benchmark output can aggregate the metric without reading raw text.
- **Delivered:** valid PaddleOCR `rec_scores` are stored as metric-only line entries and an
  arithmetic page mean on `text_result.pages[]`; missing scores are tolerated and `audit_result`
  remains immutable.

### 5. OCR L7 — `quality_report` — delivered

- **Goal:** persist a metrics-only document summary for OCR/text quality.
- **Scope:** source mix, page coverage, low-confidence counts, confidence summary, explicit lineage,
  and benchmark loading.
- **Non-scope:** readable text, layout, geometry, tables, or redaction.
- **Acceptance:** each completed OCR/Text run has an immutable `quality_report` containing no page
  text or raw PII.
- **Delivered:** each report carries exact original/audit/text lineage plus source mix, audit quality
  counts, confidence, and coverage; benchmark loading prefers matching reports and preserves legacy
  fallback behavior.

## Later engine work

### OCR L8 — human-readable text — delivered

`readable_text` now exists as an additive, deterministic human-readable rendering on `text_result`
while canonical `best_text_result` stays byte-stable. PII offsets continue to reference only
canonical text.

### OCR L9 — layout-aware text — delivered

`layout_text_result` remains the Review UI string, while versioned `layout_blocks` add deterministic
page-local order, conservative types, extraction source, optional OCR confidence, and coarse
normalized page bounds. PDF positions and transient PaddleOCR polygons are used without adding a
dependency. Canonical/page text, readable text, quality reporting, and active PII input are
unchanged. L11 structure is delivered separately from these display-oriented blocks.

### OCR L10 — span geometry — delivered

Additive `text_geometry` (`text_geometry_version = "1"`) maps canonical line spans to page-local
line boxes: each `TextLineGeometry` links `canonical_start`/`canonical_end` (into `text_result.text`)
and `page_start`/`page_end` (into `pages[].text`) to `x0/y0/x1/y1` bounds in the page's
`coordinate_unit` (`pdf_points` for text-layer, `image_pixels` for OCR). Offsets are matched against
the immutable canonical text — never regenerated — so canonical/page text and char counts stay
byte-stable and PII still runs on canonical text. Pages without safely derivable geometry degrade to
`partial`/`unsupported` with a coverage flag rather than guessing; DOCX has no geometry. The internal
`resolve_span_geometry` helper resolves a canonical span to intersecting line boxes and never returns
raw text. This provides line-level source anchoring and traceability for review/debug, and a
foundation for future placeholder mapping toward AI-ready pseudonymized document generation — it does
not perform pseudonymization, placeholder mapping, document export, or pixel-perfect visual
redaction. Word-level/redaction-ready geometry remains open at later levels.

### OCR L10.5 — canonical reading text / raw-text contract — delivered prerequisite

New text artifacts retain `text_result.text`, `text_char_count`, and `pages[].text` unchanged as
technical raw extraction and the current PII offset coordinate system. Optional versioned
`reading_text` is the product-facing canonical reading text. Its deterministic builder prefers
position/geometry, then layout blocks, layout text, and raw-order fallback; it groups simple party
columns, offer metadata, line-item rows, totals, and conservatively split prose. Status and flags
make heuristic/fallback output explicit without copying text into metrics. User View defaults to
reading text; Dev View can inspect reading, raw, and layout separately. No PII switch, lineage map,
structured-content JSON, placeholder mapping, pseudonymization, redaction, or export is included.

### OCR L11 — table/form reconstruction — delivered

Optional versioned `structured_content` on `text_result` contains per-page tables/cells,
label/value fields, and heading-bound sections. Cells and values reference immutable canonical/page
spans instead of duplicating raw content; short labels/headings, optional L10 bounds, source,
confidence, and partial-quality flags preserve useful context. Deterministic delimiter/alignment and
common German/English field heuristics run for PDF text-layer, OCR/image, and DOCX outputs without a
new dependency. Canonical/page text, active PII input, `quality_report`, benchmark summaries, and UI
remain unchanged. This supports future context-preserving pseudonymization but does not implement
placeholders, mappings, pseudonymized output, redaction, or export.

### PII L11 — entity grouping — delivered

Groups repeated same-type occurrences under a stable presentation key without changing or dropping
detections; each occurrence keeps its offsets and jump-to-text behaviour. Delivered as a pure,
derived view (`pii_grouping.group_pii_entities`) recomputed from the latest `pii_result` on every
request — `pii_result`'s schema is unchanged. See
[ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).

### PII L12 — overlap resolution

Define and apply auditable engine-level precedence for duplicate, nested, and overlapping candidates.
The current display-only highlight resolver is not engine-level entity resolution.

### Review L6 — grouped occurrences — delivered

Mirrors PII L11: the `PiiReviewGroupList` panel shows one row per entity group (type, occurrence
count, reading-text projection coverage, current decision) with an expandable per-occurrence list.

### Review L8–L9 — binding review — partially delivered

A lineage-bound, file-based decision overlay now exists (`GET/POST …/pii/review[/decisions]`,
append-only JSONL under `document-data/<id>/review/`, scoped to the exact current `pii_result.id` so
a re-run never silently reapplies a stale decision) with a broader
`pseudonymize/keep/ignore/false_positive` vocabulary than plain confirm/reject, at group or
occurrence scope with occurrence-level override. This is a lighter persistence shape than the
formal single-artifact `review_result` model L8 originally described — that remains open, along
with an explicit stale-decision indicator (L7), manual add (L10), and reason/comment metadata (L11).
Dev feedback JSONL remains a separate, dev-gated analysis input. See
[ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).

### Benchmark L9–L10

Add per-profile PII metrics in one invocation at L9. The L10 OCR confidence/coverage columns are
already delivered out of order using L7 `quality_report` with a legacy artifact fallback; cumulative
benchmark maturity remains L8 until L9 lands.

### Redaction remains blocked

Redaction stays at L0 until reviewed decisions, stable/resolved PII spans, and OCR text-to-geometry
mapping exist. No masking, pseudonymisation, or de-identified export is implemented today.

## Legacy work-package cross-reference

Older documents and ADRs may refer to `Engine-0` through `Engine-9`. Those names are historical
work-package identifiers, not maturity levels. Delivered packages covered the capability model,
benchmark foundation, AT/DE/domain recognizers, and candidate validation. Planned package contents
are superseded by the level-specific sequence above.
