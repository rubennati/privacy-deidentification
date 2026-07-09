# Engine Roadmap

OCR/Text and PII/Sensitive-Data are the product core. Review, benchmark, storage, and later
redaction support those engines. All current planning uses the cumulative **0–19 maturity scale**;
historical level numbers remain only in ADRs and the legacy mapping sections of the per-engine
documents.

## Current standing

| Engine | Current level | Delivered | Next |
| --- | --- | --- | --- |
| OCR / Text | **L15 (built on the required L10.5 step) + output-contract stabilization** | L10 geometry, versioned canonical `reading_text` with L12 multi-column reconstruction plus L13 table/form reconstruction v2 (legacy `text` remains technical raw/PII offset basis), additive span-backed `structured_content` tables/fields/sections, L14 additive metrics-only `quality_evidence` (provenance, reconstruction, page zones, lineage coverage), L15 additive noise/token artifact evidence in the same list, and Document Text Package v1 (`contract_version = "1.0"`, `valid`/`degraded`/`invalid`) | PII L12 overlap resolution downstream; future OCR capabilities plug into the contract |
| PII / Sensitive-Data | **L12; L10 partial** | profiles, Presidio/spaCy integration, AT/DE and domain recognizers, benchmark, candidate validation, context hardening, address/contact-line coverage, reproducible settings; dev-only feedback capture; derived entity grouping + a review-decision overlay; **consumes the OCR Output Contract v1 package via the `pii_input` adapter + deterministic overlap resolution** ([ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md)); **anchor-bound entity contract** (Text Anchor Graph binding where available, explicit evidence-only fallback, source observations, display model) plus frontend highlight rendering from that contract ([ADR-0029](../adr/0029-pii-review-ready-entity-contract.md), [ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md)) | formal Review L8 `review_result` |
| Review / Human-Feedback | **L2 production; L3–L5 dev-only; L6 done; L7–L9 partial** | read-only review and lineage-safe highlights; gated review aids, run settings, per-entity feedback capture; grouped occurrences + a lineage-bound decision overlay ([ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) | formal `review_result` artifact, stale-decision flag, manual add (L10) |
| Benchmark / Regression | **L8; L10 slice out of order** | coverage, routing, PII P/R/F1, privacy guard, determinism, validation counts, OCR confidence/coverage columns | L9 per-profile metrics |
| Redaction / De-Identification | **L0** | detection-only by design | blocked on stable PII, binding review, and OCR geometry |

## Delivered foundation

- OCR L0–L15 (built on the required L10.5 step): upload, technical raw extraction/lineage, OCR
  runtime, quality routing/fallback, additive OCR confidence, an immutable metrics-only
  `quality_report` for every successful run, additive readable/layout views plus deterministic typed
  layout blocks for PDF and OCR content, and additive `text_geometry` line boxes mapping raw offset
  spans to page-local geometry (source anchoring and traceability for review/debug, and a foundation
  for future placeholder mapping toward AI-ready pseudonymized document generation — it does not
  perform pseudonymization, placeholder mapping, document export, or pixel-perfect visual
  redaction), plus canonical `reading_text` as the deterministic block-aware main document view,
  L12 safe multi-column layout reconstruction/fused table-header rendering/label-value pairing, L13
  table/form reconstruction v2 (geometry-only table detection, partially fused header recovery,
  multiline label/value continuation), conservative span-backed tables, label/value fields, and
  sections in optional `structured_content`, L14 additive metrics-only `quality_evidence`
  (provenance, reconstruction, page zones, and reading↔raw lineage coverage; no raw text), and L15
  additive noise/token artifact evidence (glyph artifacts, suspicious token shapes,
  character-confusion candidates, spacing candidates) in that same list — evidence, never
  correction — plus the additive OCR Output Contract v1 / Document Text Package boundary. The
  package is built on request from existing `text_result` artifacts, keeps raw text authoritative,
  treats canonical text as derived/contextual, treats `structured_content` as semantic hints, treats
  quality/noise evidence as trust/uncertainty metadata, and now feeds the derived Text Anchor Graph
  v1 endpoint (`GET …/text-anchors`) for raw/canonical/layout identity ranges. PII still uses raw
  text and does not bind to anchors yet.
- PII L0–L9: structured and model-backed detection, named profiles, AT/DE/domain coverage,
  benchmark measurement, candidate validation, context hardening, address/contact-line coverage,
  and reproducible run settings.
- PII L10 / Review L5 partial: gated, append-only per-entity feedback capture for local analysis.
  This is not a binding `review_result` and does not alter detection.
- PII L11 / Review L6: conservative, derived entity grouping (`pii_grouping.py`, no schema change to
  `pii_result`) plus a lineage-bound review-decision overlay (every entity defaults to
  `pseudonymize`; a reviewer opts one out via `keep`/`false_positive`, at group or occurrence
  scope), covering much of Review L8/L9's practical intent without yet being the formal
  `review_result` artifact model. See
  [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).
- PII L12: PII consumes the OCR Output Contract v1 Document Text Package via the `pii_input` intake
  adapter and resolves duplicate/nested/overlapping candidates deterministically, with additive
  optional provenance/summary fields on `pii_result` (no raw text). Technical raw text remains the
  active detection input. See [ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md).
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

### OCR L12 — multi-column layout reconstruction — delivered

Canonical `reading_text` now uses a bounded layout reconstruction pass for complex dense pages:
confident prose columns are detected from x-position clusters and overlapping vertical ranges, then
rendered left-to-right and top-to-bottom. Normal tables, table-owned regions, party/header blocks,
and low-confidence layouts stay on existing conservative paths. Fused table headers render row-wise
only when following rows provide safe column positions, and adjacent label/value pairs are joined
only when geometry makes the relationship unambiguous. This is additive to `reading_text_version =
"1"` and records non-sensitive flags; it does not change technical raw text, active PII input,
`structured_content` schema, projection semantics, review decisions, pseudonymization, redaction, or
export.

### OCR L13 — table/form reconstruction v2 — delivered

Builds on L12's row-alignment primitives to close two conservative gaps: a table with no recognized
header vocabulary is still detected from a maximal run of 3+ rows sharing 3+ aligned columns, and a
header fused across one *or two* text fragments (not just one) recovers when following rows provide
safe column positions. Adjacent-row label/value pairing now extends across further rows that stay in
the same column at normal spacing and do not themselves look like a new label, heading, or inline
fact — closing a gap a private-corpus validation pass found (an unrelated fact being absorbed as a
continuation) before merge. `structured_content` field detection gained the equivalent multiline
continuation for both label/value shapes. New non-sensitive flags: `generic_table_reconstruction`
and `multiline_value_pairing` on `reading_text`; `multiline_value` on `StructuredField.flags`. No new
artifact or schema version; technical raw text, active PII input, review decisions,
pseudonymization, redaction, export, dependencies, and public APIs are unchanged. Document-type/zone
classification (L13's earlier placeholder meaning) remains open and deferred — see
[ADR-0024](../adr/0024-ocr-l13-table-form-reconstruction-v2.md).

### OCR L14 — quality evidence and lineage coverage — delivered

Every new `text_result` now carries additive, optional, versioned `quality_evidence`: a deterministic
`ocr_quality.py` builder derives metrics-only evidence items (provenance — text layer / OCR /
fallback; positioned rows; page geometry; conservative page zones; reading order; the
reconstruction/fallback strategies; structured content; and reading↔raw map coverage) plus a summary
with lineage coverage (mapped/unmapped reading chars, mapping coverage ratio, exact/partial/unmapped
span counts, source-geometry coverage, structured-content references). It answers, from the artifact
alone, where the text came from, which parts were confidently reconstructed versus fell back, and how
well the derived reading text maps back to technical raw text — **evidence before correction**. It
carries no raw text (`details` is `dict[str, int]`), classifies missing signals rather than inventing
them, and changes no text layer, active PII input, PII decision, the `quality_report` artifact,
benchmark payload, dependency, or public API. Dictionary/lexicon checks, multi-OCR, and a local LLM
are deferred additive *evidence, not truth*, and local AI assist (L14's earlier placeholder meaning)
is deferred — see [ADR-0025](../adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md).

### OCR L15 — noise/token artifact evidence — delivered

The same `quality_evidence` list gains deterministic, additive noise/token artifact evidence from a
dedicated `ocr_noise.py` builder: symbol/glyph runs, suspicious token shapes, O/0, I/l/1, and rn/m
character-confusion candidates (plus a general letter↔digit *alternation*-based
`mixed_alnum_confusion`), and spacing candidates (single-letter-token runs; long letters-only tokens
with one internal case transition), all scanned from technical raw per-page text only. Findings reuse
the existing L14 page-zone classification, and a document-level `ocr_noise_summary` item is always
present, even when clean. Structured-identifier- and IBAN-shaped tokens are exempted, as are
intentional divider/bullet/leader character runs, and trailing sentence punctuation is stripped
before shape analysis. It is **evidence before correction**: nothing is ever rewritten, removed, or
reordered, and no dictionary/lexicon, second OCR engine, or local LLM is used. A local private-corpus
validation pass found and fixed four generic (non-corpus-specific) over-flagging patterns —
superscript measurement units, incidental characters beside intentional divider/blank-field runs,
hyphenated compound words, and abbreviations followed by sentence punctuation — each covered by a
synthetic regression test, diagnosed via a privacy-safe character-class-only signature tool that
never printed or persisted real text. It carries no raw token text (`details` remains
`dict[str, int]`), and changes no text layer, active PII input, PII decision, the `quality_report`
artifact, benchmark payload, dependency, or public API. Redaction-ready text/geometry mapping (L15's
earlier placeholder meaning) is deferred — see
[ADR-0026](../adr/0026-ocr-l15-noise-token-artifact-evidence.md).

### OCR Output Contract v1 — Document Text Package (cross-cutting stabilization) — delivered

**Sequencing:** L15 complete → **OCR Output Contract v1 / Stable Document Text Package delivered
additively** → PII continuation (L12 overlap resolution and beyond) downstream, as a consumer of the
contract → future OCR capabilities plug into the contract.

This stabilization step exposes the engine's output as an independent, reusable module with a
**stable, versioned output contract**. The **OCR Output Contract v1 / Document Text Package**
packages the already-produced layers together so consumers depend on the contract, not OCR
internals (pypdf/PaddleOCR provenance, reading-order heuristics, worker details):

- **raw** = authoritative offset-stable source text (`text_result.text`); **canonical** =
  human-readable derived `reading_text`; **layout** = visual/debug `layout_text_result`;
  **structured** = `structured_content` semantic hints; **evidence** = `quality_evidence`
  (L14 provenance/lineage + L15 noise/token), all under `contract_version = "1.0"` and a
  `contract_status` (`valid`/`degraded`/`invalid`) with warnings/blockers/missing capabilities.
- External OCR/PDF tool output is **normalized before crossing the contract boundary**, so adding
  or swapping an engine stays an OCR-internal concern.
- **PII becomes a consumer of the contract, not of OCR internals**: it may use raw as its primary
  source, canonical/structured as secondary/hint layers, and evidence to adjust confidence or
  review flags; it must not assume canonical is authoritative and must not break if optional
  evidence is absent. Switching PII's active input away from raw still requires the tested
  `text_lineage_map` separation gate.
- The package is computed on request by `GET /api/documents/{document_id}/text-package`; existing
  `GET/POST .../ocr` endpoints remain backward-compatible, and runtime/worker behavior is
  unchanged.

This is a **cross-cutting stabilization milestone, not a numbered engine level** — the 0–19 scale
([ADR-0016](../adr/0016-engine-maturity-levels-0-19.md)) is unchanged. PII is **not migrated yet**;
it still uses technical raw text. See [ADR-0027](../adr/0027-ocr-output-contract-v1-strategy.md).
Future additive-evidence work —
dictionary/lexicon checks, correction *suggestions*, multi-OCR/source agreement, and a
feedback-driven improvement loop — **plugs into this contract and `quality_evidence`** and must
never change how PII (or any consumer) receives text. Where those themes land on the formal ladder
(vs. the current L16–L19 reproducibility/observability/regression-gate/production readiness levels)
is decided when each level is planned; the strategy above is independent of that numbering.

### PII L11 — entity grouping — delivered

Groups repeated same-type occurrences under a stable presentation key without changing or dropping
detections; each occurrence keeps its offsets and jump-to-text behaviour. Delivered as a pure,
derived view (`pii_grouping.group_pii_entities`) recomputed from the latest `pii_result` on every
request — `pii_result`'s schema is unchanged. See
[ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).

### PII L12 — overlap resolution (downstream) — delivered

PII now consumes the OCR Output Contract v1 Document Text Package through the `pii_input` intake
adapter (`PiiInputDocumentV1`) instead of reaching into `TextContent` internals: technical raw text
stays the primary/only active detection input, canonical reading text is contextual, structured
content is a hint layer, and quality/noise evidence is trust/uncertainty context. A structurally
invalid package is rejected with a controlled `422`, empty raw text stays the benign empty-result
path, and a degraded package with raw text still processes. `pii_overlap.resolve_pii_overlaps` then
applies auditable engine-level precedence for duplicate, nested, and overlapping candidates: exact
and same-type/nested spans merge or drop to a single strongest survivor (recording superseded ids),
while different-type overlaps are preserved and flagged for review rather than dropped. The outcome
is recorded in additive optional `pii_result` fields (`PiiEntity.provenance`,
`PiiContent.input_contract`, `PiiContent.overlap_resolution`) — reason codes, counts, and ids only,
no raw text. The active detection input is unchanged (still technical raw text; the `text_lineage_map`
separation gate is not bypassed), and existing PII API/frontend behavior is unchanged. A specific
cross-type auto-suppression precedence table (structured id > generic id, `ADDRESS` > `LOCATION`) is
deferred in favour of flag-for-review. See
[ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md).

### Anchor-bound PII entity contract (additive stabilization) — delivered

On top of L12 and ADR-0031 Phase B, a pure derived view (`pii_anchor_binding.py`,
`pii_entity_contract.py`, `GET …/pii/entity-contract`) packages the resolved entities review-ready:
anchor-derived identity where the matching Text Anchor Graph binds, explicit evidence-only fallback
when binding is missing/ambiguous/not applicable, detector source observations, raw + optional
canonical display ranges, canonical `mapping_status`, overlap provenance, resolved review state, and
a text-free display model. Missing/partial/ambiguous anchor or canonical mapping never drops an
entity. It mutates nothing, adds no detection, and keeps technical raw text as the active PII input.
This is a cross-cutting stabilization milestone (like the OCR Output Contract), **not** a level bump
and **not** the formal binding `review_result` — it is the stable review-ready read model that model
will build on. See [ADR-0029](../adr/0029-pii-review-ready-entity-contract.md) and
[ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md).

### Review L6 — grouped occurrences — delivered

Mirrors PII L11: the `PiiReviewGroupList` panel shows one row per entity group (type, occurrence
count, reading-text projection coverage, current decision) with an expandable per-occurrence list.

### Review L8–L9 — binding review — partially delivered

A lineage-bound, file-based decision overlay now exists (`GET/POST …/pii/review[/decisions]`,
append-only JSONL under `document-store/<id>/review/`, scoped to the exact current `pii_result.id` so
a re-run never silently reapplies a stale decision). Every detected entity defaults to
`pseudonymize` (no separate "pending" state, unlike a plain confirm/reject); a reviewer opts one out
via `keep` or `false_positive`, at group or occurrence scope with occurrence-level override. This is
a lighter persistence shape than the
formal single-artifact `review_result` model L8 originally described — that remains open, along
with an explicit stale-decision indicator (L7), manual add (L10), and reason/comment metadata (L11).
Dev feedback JSONL remains a separate, dev-gated analysis input. See
[ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).

### Benchmark L9–L10

Add per-profile PII metrics in one invocation at L9. The L10 OCR confidence/coverage columns are
already delivered out of order using L7 `quality_report` with a legacy artifact fallback; cumulative
benchmark maturity remains L8 until L9 lands.

### Text identity / anchor lineage — Phases B-C delivered, frontend consistency next

[ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md) frames the stable **text
anchor** identity layer: raw/canonical/layout/structured are *views* of one document, married by an
OCR/Text-owned anchor graph (`text_lineage_map` made concrete). Phase B is now implemented
additively as Text Anchor Graph v1 (`document_text_anchors.py`, `GET …/text-anchors`): raw anchors
are primary, canonical ranges attach through `reading_text_map`, layout ranges attach only when
safely byte-aligned in v1, and missing/partial/ambiguous states are explicit. Phase C is now
implemented additively as PII anchor binding (`pii_anchor_binding.py`,
`GET …/pii/entity-contract`): detections bind to anchors where available, otherwise degrade to
explicit evidence-only identity. Frontend highlights now consume that contract as the source of
truth for raw/canonical/layout view ranges, making missing/partial/ambiguous mappings visible rather
than guessed. It stores no copied binding text, adds no DB, and does not change the active PII
detection input. Pseudonymization and reconstruction remain later phases.

### Redaction remains blocked

Redaction stays at L0 until reviewed decisions, stable/resolved PII spans, and OCR text-to-geometry
mapping exist. No masking, pseudonymisation, or de-identified export is implemented today.

### Runtime architecture (cross-cutting, not an engine level)

[ADR-0023](../adr/0023-runtime-worker-architecture.md) stages the move from in-process OCR/PII to
isolated worker containers. **Phases 1–3.6 are implemented**: OCR/PII run through a job seam that
writes durable metadata-only job rows, and OCR is isolated by default in an `ocr-worker` container
via `OCR_EXECUTION_MODE=worker` — the API enqueues OCR jobs (`202`) that the worker claims (atomic
SQLite `UPDATE … RETURNING`, no Redis/broker) and runs out-of-process, so an OCR OOM/crash cannot
take the API down. The default Compose stack is `frontend`, `api`, `ocr-worker`; sync mode remains a
dev/test fallback. PII stays synchronous. The PII worker split, concurrency/timeout/retry controls,
an optional Redis/RQ queue, and quality/LLM workers remain proposed and must stay aligned with — not
ahead of — the OCR/PII engine prerequisites above.

**Runtime Job UX / in-app notifications v1** ([ADR-0030](../adr/0030-runtime-job-ux-notifications-v1.md))
is the product-facing presentation layer on top of the job contract above: a frontend
`jobActivityStore` tracks job status, persists active job ids to `localStorage` for reload recovery,
and polls through a single-owner try-lock; one additive backend `is_terminal` field is the only
schema change. Polling + `localStorage` is v1 — no Redis/RQ/Celery, no WebSocket/SSE/push
notifications yet.

## Legacy work-package cross-reference

Older documents and ADRs may refer to `Engine-0` through `Engine-9`. Those names are historical
work-package identifiers, not maturity levels. Delivered packages covered the capability model,
benchmark foundation, AT/DE/domain recognizers, and candidate validation. Planned package contents
are superseded by the level-specific sequence above.
