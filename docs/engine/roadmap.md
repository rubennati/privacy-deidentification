# Engine Roadmap

OCR/Text and PII/Sensitive-Data are the product core. Review, benchmark, storage, and later
redaction support those engines. All current planning uses the cumulative **0–19 maturity scale**;
historical level numbers remain only in ADRs and the legacy mapping sections of the per-engine
documents.

## Current standing

| Engine | Current level | Delivered | Next |
| --- | --- | --- | --- |
| OCR / Text | **L10 + required L10.5 step** | L10 geometry plus versioned canonical `reading_text`; legacy `text` remains technical raw/PII offset basis | PII L11 grouping, PII L12 overlap, then OCR L11 table/form reconstruction |
| PII / Sensitive-Data | **L9; L10 partial** | profiles, Presidio/spaCy integration, AT/DE and domain recognizers, benchmark, candidate validation, context hardening, address/contact-line coverage, reproducible settings; dev-only feedback capture | L11 entity grouping, then L12 overlap resolution |
| Review / Human-Feedback | **L2 production; L3–L5 dev-only** | read-only review and lineage-safe highlights; gated review aids, run settings, and per-entity feedback capture | L6 grouped occurrences; L8 `review_result` later |
| Benchmark / Regression | **L8; L10 slice out of order** | coverage, routing, PII P/R/F1, privacy guard, determinism, validation counts, OCR confidence/coverage columns | L9 per-profile metrics |
| Redaction / De-Identification | **L0** | detection-only by design | blocked on stable PII, binding review, and OCR geometry |

## Delivered foundation

- OCR L0–L10 plus L10.5: upload, technical raw extraction/lineage, OCR runtime, quality routing/fallback,
  additive OCR confidence, an immutable metrics-only `quality_report` for every successful run,
  additive readable/layout views plus deterministic typed layout blocks for PDF and OCR content, and
  additive `text_geometry` line boxes mapping raw offset spans to page-local geometry (source
  anchoring and traceability for review/debug, and a foundation for future placeholder mapping
  toward AI-ready pseudonymized document generation — it does not perform pseudonymization,
  placeholder mapping, document export, or pixel-perfect visual redaction), plus canonical
  `reading_text` as the deterministic block-aware main document view. PII still uses raw text.
- PII L0–L9: structured and model-backed detection, named profiles, AT/DE/domain coverage,
  benchmark measurement, candidate validation, context hardening, address/contact-line coverage,
  and reproducible run settings.
- PII L10 / Review L5 partial: gated, append-only per-entity feedback capture for local analysis.
  This is not a binding `review_result` and does not alter detection.
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
unchanged. Structured tables and forms remain L11.

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
redaction. Word-level geometry and table/form reconstruction remain L11+.

### OCR L10.5 — canonical reading text / raw-text contract — delivered prerequisite

New text artifacts retain `text_result.text`, `text_char_count`, and `pages[].text` unchanged as
technical raw extraction and the current PII offset coordinate system. Optional versioned
`reading_text` is the product-facing canonical reading text. Its deterministic builder prefers
position/geometry, then layout blocks, layout text, and raw-order fallback; it groups simple party
columns, offer metadata, line-item rows, totals, and conservatively split prose. Status and flags
make heuristic/fallback output explicit without copying text into metrics. User View defaults to
reading text; Dev View can inspect reading, raw, and layout separately. No PII switch, lineage map,
structured-content JSON, placeholder mapping, pseudonymization, redaction, or export is included.

### PII L11 — entity grouping

Group repeated same-type occurrences under a stable presentation key without changing or dropping
detections. Preserve each occurrence's offsets and jump-to-text behaviour.

### PII L12 — overlap resolution

Define and apply auditable engine-level precedence for duplicate, nested, and overlapping candidates.
The current display-only highlight resolver is not engine-level entity resolution.

### Review L8–L9 — binding review

Introduce an immutable, lineage-bound `review_result` before confirm/reject decisions become
authoritative. Dev feedback JSONL remains a separate analysis input.

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
