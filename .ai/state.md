# Current State

> If this file conflicts with the current branch or commits, trust git.

- Current phase: **Text Identity Phase C — Anchor-bound PII Entity Model v1**.
- Current objective: ADR-0031 Phase C is now delivered additively. OCR/Text still owns the derived
  **Text Anchor Graph v1**; PII now consumes the matching graph through
  `backend/app/services/pii_anchor_binding.py` and normalizes offset-based detections into
  anchor-bound domain entities exposed by `GET /api/documents/{document_id}/pii/entity-contract`.
  The contract uses `AnchorBoundPiiEntityV1` / `ReviewReadyAnchorBoundPiiEntity` with
  `PiiEntityAnchorSet`, `PiiEntityAnchorRef`, `PiiSourceObservation`, and
  `PiiAnchorBindingSummary`: exact/partial bindings use anchor identity, missing/ambiguous/no-graph
  cases become explicit evidence-only fallbacks, and duplicate observations for the same anchor set
  + entity type merge provenance. Raw/canonical ranges remain evidence/display fields; review state
  still resolves through the existing decision overlay. Anchor and binding diagnostics are now
  stronger: Text Anchor Graph summaries expose raw/canonical/layout coverage counts; PII binding
  summaries expose entities-with-raw/canonical/layout ranges, missing canonical/layout counts,
  binding reason counts, and top-level warning codes; exact anchor-bound entities propagate safe
  canonical/layout display ranges from complete anchor refs; missing ranges are attributed to stable
  reason codes such as `canonical_range_missing`, `reading_text_mapping_missing`,
  `layout_range_missing`, `layout_mapping_unavailable`, `text_anchor_graph_missing`, and
  `repeated_token_ambiguity`. No detection input switch, SQLite migration, OCR extraction behavior
  change, pseudonymization, redaction, reconstruction, export, runtime/job change, dependency, or
  private-corpus fixture is introduced. Frontend PII highlights now consume that server entity
  contract as their source of truth and derive raw/canonical/layout view ranges from the same
  anchor-bound entity identity; missing canonical/layout ranges remain visible reason-coded states,
  never frontend guesses. Formal Review L8 `review_result` is now delivered (ADR-0034, see the
  "Latest checkpoint" entries below). PII L14 / Review L10 (manual add of missed entities) is now
  **delivered** (ADR-0035, `pii-l14-manual-add-v1`): a new `manual_addition` record layered on the
  existing decision log, deliberately kept out of `pii_result` and the anchor-bound entity contract
  because both structurally assume a detector-originated span. Re-run the checkpoint loop for the
  next engine priority.
- Branch policy: feature and documentation PRs target `dev`; `main` is the curated user-stable
  branch. Windows install/update tooling always follows `main`.

## Product snapshot

- Docker Compose runs a React/Vite SPA behind nginx, a private FastAPI `api`, and a private
  `ocr-worker`.
- The product supports upload, document listing/deletion, Audit, OCR/Text, detection-only PII, and
  lineage-safe manual inspection. OCR/PII job state is durably tracked in SQLite and exposed through
  safe status endpoints. It does not redact, anonymize, or pseudonymize documents.
- Originals, metadata, and immutable derived artifacts use separate validated storage boundaries.
- OCR/Text routes each PDF page between a usable text layer and the adapter-bound PaddleOCR runtime;
  OCR pages store additive engine-reported page/line confidence metrics on `text_result`, and every
  successful OCR/Text run appends a metrics-only `quality_report` linked to the exact
  original/audit/text artifacts. DOCX extraction includes paragraphs, tables, headers, and footers.
  OCR/Text artifacts may also carry optional span-backed L11 tables, fields, and sections; L12
  improves the derived canonical reading order for confident multi-column/dense layouts, and L13
  improves table and label/value reconstruction quality on top of that stabilized order. The
  additive Document Text Package v1 endpoint packages the latest `text_result` layers under
  `contract_version = "1.0"` and a `valid`/`degraded`/`invalid` status without changing existing
  OCR endpoints; the derived Text Anchor Graph v1 endpoint exposes text-free raw/canonical/layout
  anchor identity ranges for future consumers.
- PII uses Presidio/spaCy behind an adapter, named profiles, AT/DE and domain recognizers, candidate
  validation, reproducible engine settings, deterministic overlap resolution, and a derived
  anchor-bound review entity contract over OCR/Text anchors. Raw text remains the only active
  detection input.
- The local private benchmark measures routing and PII quality from existing artifacts. Its
  committed test suite uses synthetic data; private corpus data remains under git-ignored volumes.

## Engine maturity snapshot (0–19)

- **OCR/Text: L15 done (built on the required L10.5 step).** Each successful PDF/image/DOCX OCR/Text
  run now stores additive views beside immutable technical raw `text_result.text`: canonical
  `reading_text` (L10.5), `readable_text` (L8), `layout_text_result` (L9 slice), and
  `pii_input_text` (internal L9 slice). The existing
  metrics-only `quality_report` continues to carry source mix, audit-quality counts, confidence,
  coverage, and exact original/audit/text lineage. Reruns preserve old artifacts; the benchmark
  prefers a lineage-matching report and falls back for legacy data. Technical raw text, routing, and
  active PII input remain unchanged. OCR L9/L10/L10.5/L12/L13 additionally deliver:
  - `readable_text` — optional field on `text_result`; deterministic human-readable normalization
    (line-ending cleanup, conservative paragraph joining, simple de-hyphenation, visible page
    boundaries between canonical pages) for any non-empty canonical text. Display-only; no offset
    or lineage claims; PII still ignores it.
  - `layout_text_result` — optional field on `text_result`; pypdf layout mode, PDF text-layer pages;
    OCR/DOCX/image → `null`. Display-only; the Review UI can optionally show it as unhighlighted
    plain text, with technical raw text remaining the only highlighted/offset-bearing view.
  - `pii_input_text` — a second optional field on `text_result`; internal/experimental semantic
    reading-order text (left/right block grouping, row-wise table reconstruction) for PDF
    text-layer pages, built from pypdf text-position data. **Not** the active PII input; no UI.
  - `layout_blocks` — optional versioned ordered/typed review blocks with coarse normalized 0..1
    bounds, derived from existing pypdf positions or transient PaddleOCR polygons. Missing geometry
    degrades to an explicit fallback block. The bounds are not canonical offsets, reusable
    line/word boxes, lineage mapping, or redaction-ready geometry.
  - `text_geometry` (L10) — optional versioned field on `text_result`; per page it maps canonical
    line spans (`canonical_start`/`canonical_end` into `text`, `page_start`/`page_end` into
    `pages[].text`) to page-local `x0/y0/x1/y1` line boxes in the page's `coordinate_unit`
    (`pdf_points` for text-layer, `image_pixels` for OCR), with per-page `status` and overall
    `coverage`/`flags`. Offsets are matched against the immutable canonical text, so canonical/page
    text stays byte-stable; pages without safe geometry degrade to `partial`/`unsupported` and DOCX
    has none. It carries no raw line text; the internal `resolve_span_geometry` helper resolves a
    canonical span to intersecting boxes. This provides line-level source anchoring and
    traceability for review/debug, and a foundation for future placeholder mapping toward AI-ready
    pseudonymized document generation — it does **not** perform pseudonymization, placeholder
    mapping, document export, or pixel-perfect visual redaction, and is **not** the PII input.
  - `reading_text` (L10.5) — optional versioned canonical reading text with explicit
    `heuristic`/`fallback` status and non-sensitive strategy flags. It prefers transient/L10
    geometry, then L9 blocks, layout text, and safe raw order; simple party columns, offer metadata,
    line-item rows, totals, and split prose render deterministically. User View defaults to
    **Kanonischer Lesetext**; Dev View exposes it beside **Technischer Rohtext** and **Layout-Text**.
    Technical raw/page text and counts remain byte-stable, and PII still uses raw text only.
  - `reading_text` L12 reconstruction — additive logic inside the existing versioned reading-text
    layer detects confident prose columns from x-position clusters and overlapping vertical ranges,
    renders page-local columns in reading order, reconstructs fused table headers only when
    following rows provide safe positions, and pairs adjacent labels/values only when geometry is
    unambiguous. Non-sensitive flags include `multi_column_reconstruction`,
    `dense_table_reconstruction`, and `label_value_pairing`; low-confidence layouts keep existing
    row order.
  - `reading_text`/`structured_content` L13 reconstruction v2 — a shared row-alignment helper backs
    both the keyword-header table renderer and a new geometry-only table detector, so a maximal run
    of 3+ rows sharing 3+ aligned columns renders row-wise with no recognized header vocabulary; a
    1- or 2-cell fused header recovers from the same marker-based split already used for a single
    fused cell; adjacent-row label/value pairing extends across further rows that stay in the same
    column, at normal spacing, and do not themselves look like a new label/heading/inline fact;
    `structured_content` field detection gained the equivalent multiline continuation. New flags:
    `generic_table_reconstruction`/`multiline_value_pairing` on `reading_text`, `multiline_value` on
    `StructuredField.flags`. See [ADR-0024](../docs/adr/0024-ocr-l13-table-form-reconstruction-v2.md).
  - `reading_text_map` (non-level review bridge) — optional versioned offset-only segments map only
    unambiguous reading fragments to technical raw spans. PII artifacts add optional
    exact/partial/unmapped projection status; only exact projections highlight in Canonical Reading
    Text. Unmapped entities get a second conservative in-memory unique-value match for exact,
    whitespace-normalized, phone, IBAN, and known ID formatting variants; duplicates stay raw-only.
    Raw offsets/input remain authoritative and no matched text is added to mapping metadata.
  - `structured_content` (L11, L13) — optional versioned per-page tables/cells, label/value fields,
    and heading-bound sections. Table cells and field values reference canonical/page spans rather
    than duplicating raw content; short labels/headings, source, confidence, flags, and optional L10
    line bounds preserve semantic context. Conservative deterministic heuristics cover
    delimiter/aligned tables and common German/English form labels across PDF text-layer, OCR/image,
    and one logical DOCX page; L13 adds multiline value continuation for both inline and next-line
    label/value fields. Partial structures are flagged rather than invented. It supports future
    context-preserving pseudonymization but does not perform placeholder generation, mapping,
    pseudonymization, redaction, export, or any PII-input switch. Benchmark loaders ignore it.
  - `quality_evidence` (L14) — optional versioned additive field on `text_result` carrying
    deterministic, metrics-only quality evidence and lineage coverage. A `ocr_quality.py` builder
    derives evidence items (source_text, pdf_text_layer, ocr_engine, positioned_rows, page_geometry,
    conservative page zones, reading_order, the reconstruction/fallback strategies, structured_content,
    reading_text_map, lineage_coverage, projection_lineage) plus a summary with a
    `QualityLineageCoverage` block (mapped/unmapped reading chars, mapping coverage ratio,
    exact/partial/unmapped span counts, source-geometry coverage, structured references). It explains
    where text came from and how well reading text maps back to technical raw text, using offsets,
    counts, flags, page zones, coarse bounds, and stable reason codes — `details` is `dict[str, int]`
    so no raw text is stored. Page zones are evidence only (never delete/reorder text). It changes no
    text layer, active PII input, or PII decision; benchmark loaders ignore it. See
    [ADR-0025](../docs/adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md).
  - `quality_evidence` (L15) — the same list gains deterministic noise/token artifact *evidence*
    from a dedicated `ocr_noise.py` builder: symbol/glyph runs, suspicious token shapes, O/0, I/l/1,
    and rn/m character-confusion candidates (plus a general letter↔digit alternation-based
    `mixed_alnum_confusion`), and spacing candidates (single-letter-token runs; long letters-only
    tokens with one internal case transition), scanned from technical raw per-page text only —
    never `reading_text` or `structured_content`. Findings reuse the existing L14 page-zone
    classification, and a document-level `ocr_noise_summary` item is always present, even when
    clean. Structured-identifier- and IBAN-shaped tokens are exempted, as are intentional
    divider/bullet/leader runs, and trailing sentence punctuation is stripped before shape analysis.
    It is evidence, not correction — nothing is ever rewritten, removed, or reordered, and no
    dictionary/lexicon, second OCR engine, or local LLM is used. `details` remains
    `dict[str, int]`; no raw token text is stored. See
    [ADR-0026](../docs/adr/0026-ocr-l15-noise-token-artifact-evidence.md).
- **PII/Sensitive-Data: L14 done; L10 partial.** Dev-only human-feedback capture exists. Conservative
  entity grouping (L11) is delivered as a derived view (`pii_grouping.py`) over `pii_result`, paired
  with a lineage-bound review-decision overlay: every detected entity defaults to `pseudonymize`
  (no separate "pending" state), and a reviewer opts an entity out via `keep` or `false_positive` —
  see [ADR-0021](../docs/adr/0021-pii-entity-grouping-and-review-decisions.md). **Overlap resolution
  (L12)** is now delivered: PII consumes the OCR Output Contract v1 Document Text Package through the
  `pii_input` intake adapter (`PiiInputDocumentV1`) — raw stays the primary/only active detection
  input — and `pii_overlap` deterministically merges duplicate/nested/same-type spans and flags
  cross-type overlaps for review, recording additive optional provenance/summary fields on
  `pii_result` (no raw text). See
  [ADR-0028](../docs/adr/0028-pii-intake-document-text-package-v1.md). On top of L12 and ADR-0031
  Phase B, the derived **anchor-bound review entity contract v1** (`pii_anchor_binding.py`,
  `pii_entity_contract.py`, `GET …/pii/entity-contract`) packages each resolved entity as
  `AnchorBoundPiiEntityV1` / `ReviewReadyAnchorBoundPiiEntity`: entity identity is anchor-derived
  when binding is exact or partial, evidence-only when binding is missing/ambiguous/not applicable;
  `source_observations` carry detector evidence; raw + optional canonical ranges remain
  view-specific display/evidence; provenance and review state are preserved; metadata stays
  text-free. Review decisions now carry direct PII + Text artifact lineage in both new JSONL records
  and immutable snapshots, completing binding confirm/reject at PII L13. **Manual add (L14)** is
  now delivered: a reviewer adds a span the engine missed as a distinct `manual_addition`, captured
  against canonical `reading_text` offsets with a best-effort raw-span reverse projection reusing
  the Text Anchor Graph's existing raw↔canonical pairing — never merged into `pii_result` or the
  anchor-bound entity contract, since both structurally assume a detector origin. See
  [ADR-0035](../docs/adr/0035-pii-l14-review-l10-manual-add-scope.md).
- **Review/Human-Feedback: L2 production; L3–L5 dev-only; L6–L10 done.** Grouped
  occurrences and the lineage-bound JSONL decision log now produce an immutable `review_result`
  snapshot after every decision. Superseded decisions are explicitly surfaced as stale and never
  reapplied; direct text-artifact lineage completes confirm/reject semantics at Review L9/PII L13.
  **Manual add (L10)** is now delivered alongside PII L14 above — a human-added span rejects,
  keeps, or gets pseudonymized through the existing decision endpoint, and staleness for it keys off
  the text artifact rather than the PII artifact.
- **Benchmark/Regression: L10 done.** L9 compares the newest available immutable PII artifact for
  every configured profile in one read-only invocation and reports missing profile coverage;
  the previously delivered OCR confidence/coverage columns complete cumulative L10.
- **Redaction/De-Identification: L0 by design.** It remains blocked on mature OCR, PII, and review
  foundations.

See [`docs/engine/`](../docs/engine/README.md),
[ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md), and
[ADR-0017](../docs/adr/0017-entity-taxonomy-and-risk-classes.md).

## Dev feedback boundary

- When `ENABLE_DEV_ENGINE_SETTINGS=true`, per-entity feedback is appended locally to
  `volumes/document-store/<document_id>/feedback/pii_feedback.jsonl`.
- New writes must match an entity in the referenced `pii_result` by type, offsets, and recognizer;
  summaries ignore historical lines that do not match that artifact.
- This is a gated analysis side-channel, not a learning system and not the binding review artifact.
- The structured fingerprint excludes raw document/entity text and optional `text_hash` is limited
  to a SHA-256 digest. Comments are short reviewer notes and must not contain copied document text,
  OCR text, or raw PII; the file still belongs inside the protected document-store boundary.

## Governance checkpoint

- Core OCR, NER, redaction, and pseudonymization intelligence comes from established tools behind
  adapters.
- Adapter-bound Presidio pattern recognizers, context rules, candidate validation, domain
  recognizers, and small deterministic heuristics are permitted only when documented, tested,
  benchmarkable, reviewable, and auditable.
- Major architecture/dependency changes, large opaque rule systems, or ad-hoc intelligence require
  human approval before implementation.

## Immediate next steps

The binding OCR/PII sequence, cadence, and next-PR list live in
[`docs/engine/ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md)
([ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md)). The **OCR Output Contract v1 /
Stable Document Text Package** ([ADR-0027](../docs/adr/0027-ocr-output-contract-v1-strategy.md)) is
now implemented additively as the OCR/Text output boundary before further engine work. It builds on
entity grouping and the review-decision overlay, L12/L13 reading and structure order, the L10.5
canonical-reading/raw-text contract, L10 span geometry, L9 layout-aware blocks, readable text (L8),
confidence capture (L6), `quality_report` (L7), L14 quality-evidence/lineage-coverage
observability, and L15 noise/token artifact evidence. **PII L12 overlap resolution is now delivered**
as the first downstream consumer step: PII consumes the contract through the `pii_input` adapter and
resolves overlaps deterministically ([ADR-0028](../docs/adr/0028-pii-intake-document-text-package-v1.md)).
On top of that, the **anchor-bound PII entity model v1** is delivered additively — the derived
`GET …/pii/entity-contract` view now binds detections to Text Anchor Graph v1 where available,
keeps detection evidence in `source_observations`, exposes explicit binding status/summary, and
degrades to evidence-only identity when anchors are unavailable or ambiguous. This remains a
stabilization milestone, not the binding `review_result`
([ADR-0029](../docs/adr/0029-pii-review-ready-entity-contract.md),
[ADR-0031](../docs/adr/0031-text-identity-anchor-lineage-architecture.md)). PII still detects on
technical raw text only. Frontend highlight rendering now uses the server entity contract as the
single PII highlight source of truth: raw/canonical/layout views render only the view-specific
ranges the contract provides, and missing/partial/ambiguous or evidence-only states are visible
instead of guessed. Formal Review L8 `review_result` and the **PII validation transparency report**
are now delivered. The next documented independent engine priority is **Benchmark L9 per-profile
reporting**, followed by a checkpoint before PII advances beyond L12.

**Strategic direction (OCR/Text as an independent module).** The **OCR Output Contract v1 /
Document Text Package** stabilizes OCR/Text output as a versioned package of
raw/canonical/layout/structured/evidence layers with `contract_version = "1.0"` and a
`contract_status` (`valid`/`degraded`/`invalid`), so PII (and future consumers — Review,
pseudonymization, document analysis, export, local AI) can depend on the contract, not OCR internals
(PaddleOCR, PDF parsing, reading-order heuristics, worker details). Raw text remains authoritative;
canonical text is derived/contextual; `structured_content` is semantic hints; and quality/noise
evidence is trust/uncertainty metadata. Existing OCR endpoints remain backward-compatible, external
OCR/PDF tool output is normalized before crossing the boundary, and deferred additive-evidence work
(dictionary/lexicon, correction *suggestions*, multi-OCR/source agreement, feedback-driven
improvement) plugs into the contract and `quality_evidence` without changing how PII receives text.

The OCR L8/L9 text-layer work is contract-first: the output model and invariants are fixed in
[`docs/engine/ocr-layout-text-contract.md`](../docs/engine/ocr-layout-text-contract.md). Technical raw
`text_result.text` remains the offset authority and active PII input; canonical `reading_text` is
the product-facing main view beside internal `pii_input_text`, legacy `readable_text`, and
`layout_text_result`, all to be tied by a future `text_lineage_map`.
`readable_text`, `layout_text_result`, `pii_input_text`, `layout_blocks`, `text_geometry`, and
`structured_content` are delivered additively (see above); `text_lineage_map` remains open. There
must be **no two unconnected source-of-truth texts**: reading text is a derived view, current
blocks carry extraction source labels only, and the future map must connect every view back to raw
offsets/source before any
detection-input switch. `pii_input_text` may become the
**active PII detection input** only with a tested `text_lineage_map` (the separation gate) — PII
runs exclusively on technical raw text today, regardless of other views. The reading/readable/
layout/PII-input layers are additive and never a standalone PII input.

The checkpoint leaves OCR/Text at L15 (built on the L10.5 prerequisite), PII at L12 done/L10
partial, and Redaction L0; after reconfirming the next-three cadence, the plan is:

1. Re-scope the next real construction-time OCR lineage coverage path; keep the existing partial
   row-construction boundary explicit and do not claim full-document lineage.
2. Re-run the prerequisite checkpoint before completing PII L13 / Review L9 semantics or advancing
   PII further; the active-input separation gate remains closed.
3. Keep Redaction at L0 until stable reviewed PII and redaction-ready mapping prerequisites are met.

PII **L12 — overlap resolution** (deterministic engine-level precedence for duplicate/nested/
overlapping candidates) is now delivered as downstream consumer work
([ADR-0028](../docs/adr/0028-pii-intake-document-text-package-v1.md)).

**Previous checkpoint (OCR L10.5 intermediate):** OCR/Text retained formal L10 maturity and completed
the canonical-reading-text/raw-text prerequisite before L11. Versioned `reading_text` is additive
and deterministic, while `text_result.text` remains technical raw and the active PII input. The
reading layer introduced no routing, raw/page-text, active-PII-input, dependency, quality-report, or
benchmark-privacy drift, and legacy artifacts stayed valid. Line geometry stopped at the L10
source-anchoring/traceability boundary.

**Latest checkpoint (OCR L11):** OCR/Text advanced from L10.5 to L11 with additive, optional
span-backed tables, fields, and sections. OCR remains sufficiently ahead of PII/Redaction; no
benchmark or feedback signal changes the priority. The PR introduces no dependency, engine setting,
routing, raw/page-text, active-PII-input, `quality_report`, or benchmark-report drift; schema
change is versioned and legacy compatible. Structured values/table contents remain canonical/raw
spans, benchmark loaders ignore the payload, and placeholder generation, pseudonymization,
redaction, export, word-level/pixel-perfect geometry, and `text_lineage_map` remain open. The next
three steps are PII L11, PII L12, then the Review L8 artifact foundation.

**Latest reading-text regression checkpoint:** OCR/Text advanced to L12. Canonical reading-text
heuristics now recognize conservative 3+ column tables, keep multiline descriptions with their
rows, preserve ordinal right-aligned values, separate bounded invoice party/detail columns, filter
repeated page-margin/page-number rules, reconstruct confident multi-column prose left-to-right and
top-to-bottom, render fused table headers only when following rows provide safe positions, and join
adjacent label/value pairs only when geometry is unambiguous. Synthetic positive and
must-not-trigger regressions cover flat facts, offer metadata, party columns, AGB/prose columns,
tables/totals, fused headers, paragraph boundaries, labels/values, and repeated margins. Raw text,
PII input, routing, dependencies, artifact versions, and the next engine cadence are unchanged.

**Latest reading-text projection checkpoint:** OCR/Text is now L12 and PII remains L11 done/L10
partial. The safe display bridge adds no recognizer, detection-input, dependency, routing,
benchmark-payload, pseudonymization, redaction, or export change. It is not the full lineage map and
does not satisfy the PII-input separation gate. A unique in-memory text-match fallback now improves
coverage for otherwise-unmapped exact/format-normalized values without guessing duplicates or
storing/logging copied text.

**Latest checkpoint (PII L11 entity grouping + review-decision overlay):** PII/Sensitive-Data
advances from L9 done/L10 partial to **L11 done**. `pii_grouping.py` groups repeated same-type,
same-normalized-value occurrences (conservative per-type normalization: exact lowercase email,
whitespace/case IBAN, digit/`+`-only phone, whitespace-stripped ID-like types, exact
whitespace-normalized text otherwise — never fuzzy, never cross-type) as a pure derived view; it
changes nothing about detection or the `pii_result` schema. A paired, lineage-bound
review-decision overlay (`GET/POST …/pii/review[/decisions]`, JSONL under
`document-store/<id>/review/`) assumes every detected entity is `pseudonymize`-bound by default (no
separate "pending" state); a reviewer opts an entity out via `keep` or `false_positive` at group or
occurrence scope (occurrence overrides win), resolving to a coarse `accepted/kept/rejected` status
— `rejected` suppresses the Review UI highlight in both raw and reading-text modes, `kept` stays
highlighted but visually distinguishable, and the default/`accepted` case looks like a normal
highlight. Decisions are scoped to the exact current PII artifact id so a re-run never silently
reapplies a stale one, but there is no explicit stale-UI flag and this is a lighter persistence
shape than the
formal single-artifact `review_result` model — see
[ADR-0021](../docs/adr/0021-pii-entity-grouping-and-review-decisions.md) for the exact scope and
what remains open. This PR introduces no dependency, recognizer, detection, routing, or
benchmark-payload change; `GET/POST …/pii` stay byte-for-byte backward compatible. At that time,
OCR/Text (L11) and PII (now L11) were level-equal, which was acceptable since entity grouping is an
interleaving-eligible step needing no new OCR capability. Next: **PII L12 overlap resolution**,
then formalizing the **Review L8 `review_result`** artifact model, then the **PII validation
transparency report**.

**Latest checkpoint (OCR L12 multi-column layout reconstruction):** OCR/Text advances from L11 to
**L12 done** with additive canonical-reading-text improvements only. The PR introduces no
dependency, OCR routing, technical raw/page text, active PII input, public API, review-decision,
`quality_report`, benchmark-payload, pseudonymization, redaction, or export change. The older
multi-engine-selection placeholder for OCR L12 is explicitly deferred; L12 now means deterministic
multi-column layout reconstruction (see
[ADR-0022](../docs/adr/0022-ocr-l12-multi-column-layout-reconstruction.md)). Its quality bar is
stability-first: confidence-aware layout improvements must combine conservative evidence, preserve
fallback/raw views, and classify missing evidence rather than encode private-corpus-specific guesses.
OCR/Text is ahead of
PII L11/Redaction L0 again; before advancing PII beyond L12, re-run the checkpoint loop for missing
OCR lineage/geometry prerequisites. Next: **PII L12 overlap resolution**, formal **Review L8
`review_result`**, then the **PII validation transparency report**, unless benchmark/private-corpus
evidence reprioritizes OCR L13 document understanding.

**Latest stabilization checkpoint (OCR L12 PR-readiness audit):** A local private-corpus audit found
and fixed one release-blocking L12 regression: form-style aligned label/value rows could be
misclassified as prose columns, separating labels from their values in canonical reading text. The
stabilization adds a generic form-column confidence guard and synthetic regression coverage; it does
not change technical raw text, active PII input, review decisions, pseudonymization, redaction,
export, dependencies, or public APIs.

**Latest checkpoint (OCR L13 table/form reconstruction v2):** OCR/Text advances from L12 to **L13
done** with additive `reading_text`/`structured_content` improvements only. A shared row-alignment
helper backs a new geometry-only table detector (no header keyword required) and recovers headers
fused across one *or two* text fragments; adjacent-row label/value pairing now spans multiple
following rows for a multiline value; `structured_content` field detection gained the equivalent
multiline continuation. The older document-understanding placeholder for OCR L13 is explicitly
deferred; L13 now means table/form reconstruction v2 (see
[ADR-0024](../docs/adr/0024-ocr-l13-table-form-reconstruction-v2.md)), mirroring how ADR-0022
re-scoped L12. A local private-corpus validation pass found and fixed one regression risk before
merge (an unrelated inline `Label: value` fact was being absorbed as a value continuation); after the
fix, every corpus document a standard pypdf extraction could open produced byte-identical
`reading_text` before and after this change (one encrypted document has an unrelated, pre-existing
`pypdf`/`cryptography` dependency gap that predates this PR). The PR introduces no dependency, OCR
routing, technical raw/page text, active PII input, public API, review-decision, `quality_report`,
benchmark-payload, pseudonymization, redaction, or export change. OCR/Text is now 2 levels ahead of
PII (L11) again; before advancing PII beyond L12, re-run the checkpoint loop for missing OCR
lineage/geometry prerequisites. Next: **PII L12 overlap resolution**, formal **Review L8
`review_result`**, then the **PII validation transparency report**, unless benchmark/private-corpus
evidence reprioritizes further OCR work.

**Latest checkpoint (OCR L14 quality evidence and lineage coverage):** OCR/Text advances from L13 to
**L14 done** with additive, metrics-only `quality_evidence` on `text_result`. The older
document-understanding/local-AI-assist placeholder for OCR L14 is explicitly deferred; L14 now means
quality evidence and lineage coverage (see
[ADR-0025](../docs/adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md)), mirroring how
ADR-0022/ADR-0024 re-scoped L12/L13. A deterministic `ocr_quality.py` builder derives, from
already-computed inputs, provenance/reconstruction/page-zone/reading-order evidence plus a
`QualityLineageCoverage` block, and classifies missing signals as `unavailable`/`not_applicable`
rather than inventing them. Privacy is by construction: `details` is `dict[str, int]`, all locators
are offsets/counts/flags/zones/reason codes, and the schema validates evidence offsets stay inside the
actual raw/reading text. A local metrics-only private-corpus pass (never committed; `.local` outputs)
confirmed coherent, leak-free evidence for every text-layer document with byte-identical reading text;
scanned/image documents with no text layer are correctly reported `unavailable` pending the OCR
runtime (a pre-existing limitation, not an L14 regression). The PR introduces no dependency, OCR
routing, technical raw/page text, active PII input, PII projection/decision, public API,
review-decision, `quality_report`, benchmark-payload, pseudonymization, redaction, or export change.
Dictionary/lexicon checks, multi-OCR, and a local LLM remain deferred additive *evidence, not truth*.
Next: **PII L12 overlap resolution**, formal **Review L8 `review_result`**, then the **PII validation
transparency report**.

**Latest checkpoint (Runtime Architecture Phase 2 — SQLite job state/status API):** Implements
[ADR-0023](../docs/adr/0023-runtime-worker-architecture.md) Phase 2 on top of Phase 1. OCR
(`POST …/ocr`) and PII (`POST …/pii`) still execute *through* the in-process `SyncJobRunner`, but the
FastAPI runner provider now persists each job lifecycle to SQLite
(`backend/app/services/job_store.py`, default `DOCUMENT_DATA_DIR/jobs.sqlite3`) before/during/after
the synchronous station call. New safe status endpoints (`GET /api/jobs/{job_id}`,
`GET /api/documents/{document_id}/jobs`) return metadata only, and successful OCR/PII responses add
an `X-Job-Id` header without changing their existing artifact response bodies. This is a runtime
architecture step — **no engine level changes**. There is still **no worker container, no queue, no
Redis/Celery/RQ, no background task, no OCR/PII algorithm or model change, no pseudonymization, no
redaction, no export, and no frontend workflow change**; heavy OCR still fate-shares with the backend
until Phase 3. Job rows carry only ids, statuses, execution mode, timestamps, attempt counts,
sanitized error code/message, produced artifact id/type, and tiny string metadata — never raw document
text, OCR text, canonical reading text, PII values, artifact JSON, stack traces, or raw exception
messages — and are deleted with their document boundary. Next runtime step: **Phase 3 (`ocr-worker`
isolation)**, kept aligned with — not ahead of — the OCR/PII engine sequence below.

**Latest checkpoint (Runtime Architecture Phase 3 — isolated OCR worker, opt-in):** Implements
[ADR-0023](../docs/adr/0023-runtime-worker-architecture.md) Phase 3, the first real runtime isolation
step. A new `OCR_EXECUTION_MODE` setting (default `sync`) gates behavior: `sync` keeps Phase 2 exactly
(OCR runs in-process through `SyncJobRunner`, `201` with the `text_result` body), while `worker` makes
`POST …/ocr` enqueue a `pending` OCR job and return `202` with safe job status. An isolated
`ocr-worker` container (`backend/app/ocr_worker.py`, `python -m app.ocr_worker`, behind the `worker`
Compose profile; `make up-ocr-worker`/`up-full-worker`) polls the shared SQLite store, **atomically**
claims the oldest pending `ocr_text` job (`JobStore.claim_next_pending_job` — one
`UPDATE … RETURNING` under WAL, so two workers never double-claim), runs the unchanged
`create_text_artifact` station in its own process, and records `succeeded` (artifact id/type) or a
sanitized `failed`. OCR runs **outside** the short claim transaction; the worker gets its own 2g
memory ceiling and independent `restart`, so an OCR OOM/crash can no longer take the API down. This is
a runtime step — **no engine level changes**: OCR algorithm, technical raw/canonical text,
`quality_evidence`, PII model/technical-raw input, PII projection, review decisions, benchmark
payloads, and artifact contracts are all unchanged, and PII stays synchronous. Concurrency is bounded
to exactly 1 (higher is rejected, deferred to Phase 4). Known limitations, **deferred to Phase 4**: a
worker crash mid-job leaves the row `running` (no lease/heartbeat reclaim yet), auto-retry (a failed
job is terminal), parallel concurrency >1, the PII worker split, any queue broker (Redis/RQ), and a
slimmer API-vs-worker image split (Phase 3 uses one image for stability). At that time, the frontend
still used the default `sync` mode; Phase 3.6 below closes that worker-mode UI gap. Next runtime step: **Phase 4
(PII worker + concurrency/timeout/retry controls, stale-lease reclaim)**; next *engine* step is the
**OCR Output Contract v1 / Stable Document Text Package**
([ADR-0027](../docs/adr/0027-ocr-output-contract-v1-strategy.md)), with **PII L12 overlap
resolution** downstream as a consumer of that contract.

**Latest hardening checkpoint (Runtime Architecture Phase 3.5 — worker persistence audit):** A
pre-PR audit confirmed the Phase 3 API and `ocr-worker` share the same Compose environment anchors
and bind mounts for uploads, document data, OCR models, and the default SQLite job DB
(`DOCUMENT_DATA_DIR/jobs.sqlite3`; overrideable with a shared `JOB_STORE_DB_PATH`). The job store
uses idempotent schema setup, parent-directory creation, WAL, `busy_timeout`, short transactions, and
an atomic `UPDATE … RETURNING` claim; OCR execution remains outside DB transactions and job status
stores metadata only. Hardening added tests for nested DB parent creation, persistence across store
instances, and WAL/schema-version setup; documentation now makes the default DB path, backup boundary,
same-image worker service, and Phase 3 stale-running limitation explicit. No engine level changed and
no OCR/PII algorithm, artifact contract, PII input, frontend workflow, Redis/Celery/RQ, redaction,
pseudonymization, or export behavior was introduced. Remaining runtime work stays Phase 4:
stale-running lease/heartbeat reclaim, bounded concurrency beyond 1, retry/timeout/cancel controls,
and the PII worker split.

**Latest checkpoint (Runtime Architecture Phase 3.6 — default worker stack + simplification):**
The default runtime is now production-shaped without profiles: `frontend`, `api`, and `ocr-worker`
start with `make up` / `docker compose up -d --build`, `OCR_EXECUTION_MODE` defaults to `worker`,
and `OCR_EXECUTION_MODE=sync` is retained only as a dev/test fallback. The frontend worker-mode gap is
closed: `runOcr()` accepts the API's `202` job response, polls safe job metadata, and fetches the
finished text artifact, so the Review flow works against the worker default. The old
slim/pii/ocr/full Make targets, `INSTALL_OCR`/`INSTALL_PII` build args, and profile-based runtime
fragmentation were removed; the shared API/worker image includes OCR and PII dependencies by default,
with future image splitting documented as an optimization. `.env.example` is reduced to meaningful
runtime/deployment options with a single host `DATA_ROOT` (default `./volumes`): Compose maps its
`uploads`/`document-store`/`job-state`/`pii-feedback-archive`/`ocr-models` subdirectories onto stable
internal container paths, and those internal paths (`UPLOAD_STORAGE_DIR`, `DOCUMENT_DATA_DIR`,
`DATA_JOB_STATE_DIR`, `PII_FEEDBACK_ARCHIVE_DIR`, `OCR_MODEL_DIR`, `JOB_STORE_DB_PATH`) are advanced
overrides only so a deployment cannot silently split API/worker storage. The former `document-data`
root was renamed to `document-store`, and `jobs.sqlite3` moved out of it into a dedicated `job-state`
root (`DATA_JOB_STATE_DIR/jobs.sqlite3` by default) so durable job state never sits beside
per-document artifacts (no automatic migration; see the README migration note). `COMPOSE_PROJECT_NAME`
defaults to `privacy-deidentification` and service naming is `frontend`/`api`/`ocr-worker`. The `.ai`
quality gates now require API/frontend contract tests for new response shapes, job-flow coverage,
Compose build/start smoke on runtime-file changes, no duplicate shared-image builds, and an explicit
acceptance gate before flipping a runtime default. This is a runtime/infra step — **no engine level
changed** and no OCR
algorithm, PII algorithm, `reading_text`, `quality_evidence`, artifact contract, PII input, Redis/
Celery/RQ, Kubernetes, local LLM, dictionary/multi-OCR, pseudonymization, redaction, or export
behavior was introduced. Remaining runtime work stays Phase 4: stale-running lease/heartbeat
reclaim, bounded concurrency beyond 1, retry/timeout/cancel controls, and the PII worker split.

**Latest checkpoint (OCR L15 noise/token artifact evidence):** OCR/Text advances from L14 to **L15
done** with additive, deterministic noise/token-artifact evidence folded into the same
`quality_evidence` list — no new artifact, no new schema version. The older redaction-ready-geometry
placeholder for OCR L15 is explicitly deferred; L15 now means noise/token artifact evidence (see
[ADR-0026](../docs/adr/0026-ocr-l15-noise-token-artifact-evidence.md)), mirroring how
ADR-0022/ADR-0024/ADR-0025 re-scoped L12/L13/L14. A dedicated `ocr_noise.py` builder scans technical
raw per-page text only (never `reading_text` or `structured_content`) for symbol/glyph runs,
suspicious token shapes, O/0, I/l/1, and rn/m character-confusion candidates (plus a general
letter↔digit alternation-based `mixed_alnum_confusion`), and spacing candidates, reuses the existing
L14 page-zone classification, and always emits a document-level `ocr_noise_summary`. It is evidence
before correction: nothing is ever rewritten, removed, or reordered, and there is still no
dictionary/lexicon, second OCR engine, or local LLM. A local, metrics-only private-corpus validation
pass (never committed; `.local` outputs) found and fixed four generic, non-corpus-specific
over-flagging patterns — superscript measurement units (`m²`/`m³`) misread as digit confusion,
incidental characters beside intentional divider/blank-field runs disqualifying the whole run from
its structural exemption, hyphenated compound words miscounted as letter/digit confusion, and
abbreviations followed by sentence punctuation over-tripping the symbol-ratio check — each diagnosed
via a privacy-safe character-*class*-only signature tool (never a raw character) and each covered by
a synthetic regression test; every text-layer corpus document then classified
`NOISE_EVIDENCE_USEFUL` with `NO_REGRESSION` (byte-identical `reading_text`/`structured_content`
against the existing L14 baseline) and no raw-text leak. The PR introduces no dependency, OCR
routing, technical raw/page text, active PII input, PII projection/decision, public API,
review-decision, `quality_report`, benchmark-payload, pseudonymization, redaction, or export change.
Dictionary/lexicon checks, multi-OCR, a local LLM, and correction *suggestions* (a later, explicitly
separate level) remain deferred additive *evidence, not truth*.

**Latest checkpoint (OCR Output Contract v1 / Document Text Package):** The OCR/Text stabilization
step after L15 is implemented additively, without changing the 0–19 level. New
`DocumentTextPackageV1`/`DocumentTextSourceV1`/`DocumentTextPackageValidationSummary` schemas and a
builder/validator package existing `text_result` layers under `contract_version = "1.0"` and
`contract_status` (`valid`/`degraded`/`invalid`): raw text is authoritative, canonical text is
derived/contextual, `structured_content` is semantic hints, and `quality_evidence`/noise evidence is
trust/uncertainty metadata. `GET /api/documents/{document_id}/text-package` exposes the derived
package for the newest text artifact; existing OCR endpoints remain backward-compatible. PII is not
migrated yet and still uses technical raw text. The package is not persisted as its own artifact,
and there is no runtime/worker, PII, benchmark-payload, pseudonymization, redaction, export,
dictionary/lexicon, multi-OCR, or local-LLM change. Next: **PII L12 overlap resolution**, formal
**Review L8 `review_result`**, and the **PII validation transparency report** downstream as
consumers of the contract.

**Latest checkpoint (PII L12 — intake adapter + overlap resolution):** PII/Sensitive-Data advances
from **L11 done to L12 done** as the **first downstream consumer** of the OCR Output Contract v1
Document Text Package. PII now consumes `DocumentTextPackageV1` through a dedicated intake adapter
(`pii_input.py`, internal `PiiInputDocumentV1`) instead of reaching into `TextContent` internals:
`pii_service._analyze_text` reads only the adapter's model. Technical raw text stays the **primary
and only active detection input**; canonical reading text is contextual, `structured_content` a hint
layer, and quality/noise evidence trust context — none applied to silently suppress an entity. A
**structurally invalid** package (unsupported version, malformed source roles, unresolvable id) is
rejected with a controlled `422`; a package invalid **only** because raw text is empty stays the
existing benign empty-result path; a **degraded** package with raw text still processes.
Deterministic overlap resolution (`pii_overlap.py`) runs after candidate validation and before
reading-text projection: exact duplicates merge (recording recognizers + superseded ids), same-type
overlaps/nesting keep the strongest span and drop the rest (recorded, never silent), and
different-type overlaps are preserved and flagged for review (`ambiguous_overlap_review_required`) —
a specific cross-type auto-suppression precedence table is deferred. Additive optional `pii_result`
fields carry the outcome (`PiiEntity.provenance`, `PiiContent.input_contract`,
`PiiContent.overlap_resolution`) as reason-codes/counts/ids only, never raw text; legacy artifacts
stay valid. Baseline raw-text detection is byte-identical (existing PII tests unchanged apart from
the new additive fields), the active-input `text_lineage_map` separation gate is not bypassed, and
there is no change to detection, recognizers, the `DocumentTextPackageV1` schema, OCR extraction,
review/feedback flows, runtime/worker behavior, benchmark payloads, pseudonymization, redaction, or
export. Existing PII API routes and the frontend review flow are unchanged (only additive optional
TS types were added). See
[ADR-0028](../docs/adr/0028-pii-intake-document-text-package-v1.md). Next: formal **Review L8
`review_result`**, then the **PII validation transparency report**.

**Latest checkpoint (Anchor-bound PII entity model v1):** ADR-0029's derived review-facing contract
is extended by ADR-0031 Phase C. `pii_entity_contract.py` still builds `PiiEntityContractV1` from the
latest `pii_result`, but it now uses `pii_anchor_binding.py` to bind detections to the matching Text
Anchor Graph where available. Each `ReviewReadyAnchorBoundPiiEntity` carries an anchor-derived
`entity_id` for exact/partial bindings, explicit evidence-only identity for
missing/ambiguous/no-graph binding, `anchor_set`/`anchor_refs`, detector `source_observations`,
raw/canonical display ranges, canonical `mapping_status`, overlap provenance, resolved review
state, and a text-free display model. Missing/partial/ambiguous anchor or canonical mapping never
drops an entity; value remains confined to the entity value field already mirrored from
`GET …/pii`, and no surrounding text snippet is copied. It mutates nothing, adds no detection, keeps
technical raw text the primary/only active input, and leaves `GET …/pii` and `GET …/pii/review`
unchanged; the frontend now consumes the entity contract for review highlights. This is **not** the
formal binding `review_result` (still open). See
[ADR-0029](../docs/adr/0029-pii-review-ready-entity-contract.md) and
[ADR-0031](../docs/adr/0031-text-identity-anchor-lineage-architecture.md). Frontend highlight
consistency via anchors is now wired through the entity contract; next is formal **Review L8
`review_result`** and the **PII validation transparency report**.

**Latest checkpoint (Anchor-first PII highlight conformance fix):** A root-cause fix for the residual
raw-vs-canonical highlight divergence, not a diagnostics/UI patch and no engine level change. The
Text Anchor Graph tokenizer's phone pattern (`document_text_anchors._PHONE_RE`) matched across
`\s` — including `\n` — so a line-ending date fused with the next line's leading number into one
bogus multi-line anchor whose canonical range spanned unrelated reading text; the two clean values
then bound `partial` and silently lost their canonical highlights. Constraining the phone pattern to
horizontal whitespace (`[ \t]`) makes anchors per-line identity units again, so clean unique values
present in both views now propagate a canonical (and, when the layout view is byte-aligned, layout)
display range through the *same* anchor-bound `entity_id` — Raw and Canonical no longer diverge for
values with anchor lineage. Genuinely repeated values (a header+footer company name under reordering)
remain canonical-missing **with** an explicit `repeated_token_ambiguity`/`canonical_range_missing`
reason, never silently. New `backend/tests/test_anchor_bound_pii_e2e_conformance.py` proves the full
`DocumentTextPackageV1 → anchor graph → binding → entity contract` path end to end (and fails without
the fix); anchor line-boundary integrity is guarded in `test_document_text_anchors.py`. No detection,
recognizer, `pii_result` schema, active-input, frontend guessing, pseudonymization, redaction, or DB
change; frontend still renders only contract-supplied ranges. See the anchor gates in
[`quality-gates.md`](quality-gates.md).

**Latest checkpoint (Text anchor architecture feasibility audit — docs only):** A deep architecture
and conformance audit of the anchor approach is recorded in
[`docs/engine/text-anchor-architecture-feasibility-audit.md`](../docs/engine/text-anchor-architecture-feasibility-audit.md).
Verdict: keep the architecture; current v1 is a sound **anchor-derived** transitional layer
(consumption is contract-enforced and honest), not yet anchor-first — anchor ids are offset-minted
and canonical lineage rests on the post-hoc unique-token `reading_text_map`. Key constraints it
adds: anchor ids are stable only per (text-artifact bytes × graph-builder version), so no durable
state may store anchor ids before the graph (or a builder version pin) is persisted with them; the
`text_match` display fallback should retire once construction-time lineage lands. Recommended next
three branches: `anchor-first-text-package-v2` (builder-emitted construction-time lineage),
`pii-binding-quality-suite` (hard-case regression corpus + frontend contract-failure notice), then
`review-result-v1` (occurrence-id-primary keys). No code, detection, schema, or runtime change.

**Latest checkpoint (Geometry-backed reading projection v1 — post-render, NOT construction-time
lineage):** A contradiction audit of an initial `anchor-first-text-package-v2` attempt found it did
**not** implement construction-time lineage despite its naming: `reading_text.py` (the actual
reading-text builder) was provably unchanged (0 diff), the new mechanism was called strictly *after*
`build_reading_text(...)` already returned a finished string, and its core operation was `str.find`
over that completed string — a post-hoc reconstruction, exactly like the pre-existing unique-token
`reading_text_map`, just at full-line granularity. Worse, the audit reproduced a concrete
duplicate-value identity defect: two textually-identical full raw lines could be bound to *inverted*
canonical occurrences (both confidently labeled `exact`, `confidence=1.0`) depending only on the
order geometry lines happened to be processed in — determinism, not identity proof. This checkpoint
is the corrective hardening pass, reclassified as **Geometry-backed Reading Projection v1**.
Renamed throughout: `ReadingTextConstructionMap`→`ReadingTextGeometryProjectionMap`,
`ReadingTextConstructionSummary`→`ReadingTextGeometryProjectionSummary`,
`reading_text_construction_map[_version]`→`reading_text_geometry_projection_map[_version]`,
anchor flag `canonical_construction_lineage`→`canonical_geometry_projection`, summary field
`canonical_construction_count`→`canonical_geometry_projection_count`, lineage-source literal
`construction`→`geometry_projection`; the module moved from `reading_text_lineage.py` to
`reading_text_geometry_projection.py` (`build_reading_text_geometry_projection_map`). The identity
defect is fixed with a global-uniqueness + line-boundary discipline: a source line may be projected
as `exact` only when its exact text occurs exactly once among the collected verbatim source lines
**and** exactly once (delimited by `\n`/string edges, so a short line like `"Wien"` cannot falsely
match inside a longer line like `"1010 Wien"`) in the canonical text; every other candidate
occurrence of a non-unique value becomes an explicit `ambiguous` segment (`source_range=None`,
`confidence=None`, reason codes `duplicate_source_value`/`multiple_canonical_candidates`/
`identity_ambiguous`/`relative_order_not_identity_proof` — never the duplicated value itself).
Verified by construction: the same raw/canonical text projected with reversed geometry-line encounter
order now yields *identical* (still-ambiguous) output instead of two mutually-inverted `exact`
claims. `DocumentTextPackageV1`'s `lineage_summary` now names `geometry_projection` /
`fallback_text_match` / `unavailable` and carries a `geometry_projection_ambiguous_count`; the Text
Anchor Graph prefers geometry-projection segments over the older `reading_text_map` only when they
resolve a raw token unambiguously, and flags which post-hoc mechanism won per anchor — **neither is
authoritative construction identity**. The useful case survives: two genuinely distinct company
names sharing a repeated `GmbH` suffix in a reordered document still keep their full canonical
highlight, because each is a globally-unique whole line; a genuinely duplicated full-line/label value
(same value twice, or the same value repeated across pages) is now explicitly declined end-to-end
through anchor binding (`canonical_range_missing` + `repeated_token_ambiguity`), never silently
guessed. **`reading_text.py` (the actual reading-text builder) is unchanged and still discards its
own per-fragment source knowledge** (`ReadingRow`/`ReadingCell` carry no raw offsets); genuine
builder-emitted construction-time lineage remains **unimplemented** — Phase 1 of the feasibility
audit's recommendation is **not** complete, and a real `anchor-first-text-package-v2` remains a
separate, future branch. No change to PII detection semantics/input, recognizers, reading-text
output bytes, runtime, or the DB. Metadata stays text-free (leak-tested, including reason codes).
Covered by `backend/tests/test_reading_text_geometry_projection.py` (renamed from
`test_anchor_first_text_package_v2.py`) plus updated anchor-graph, package, and E2E-conformance
suites. Next: thread real raw offsets through `reading_text.py`'s own `ReadingRow`/`ReadingCell` path
for genuine construction-time lineage (delivered as a partial first slice — see the "Reading-text row
construction lineage v1" checkpoint below), then `pii-binding-quality-suite`, then `review-result-v1`.

**Latest checkpoint (Runtime Job UX / in-app notifications v1):** Cross-cutting runtime/UX step, not
an engine level change. On top of ADR-0023's job model/status API, the product-facing presentation
layer is delivered: `JobStatusResponse` gains one additive `is_terminal: bool` field
(`backend/app/schemas.py`/`backend/app/api/jobs.py`); no other backend change — the existing
`GET /api/jobs/{job_id}` and `GET /api/documents/{document_id}/jobs` (already newest-first,
document-scoped, bounded) already carried enough safe metadata for this UX. The frontend gains a
small, framework-agnostic `jobActivityStore` (`frontend/src/lib/jobActivity.ts`): it records job
status, persists active (non-terminal) jobs to `localStorage` for reload recovery, and serializes
polling per job id through a single-owner try-lock (`beginPolling`/`endPolling` +
`pollJobUntilTerminal`) so a live `runOcr()` call and a reload-recovery resume can never double-poll
the same job. `runOcr()` now records into and polls through this shared store instead of its own
private loop, with its external artifact-or-throw contract and existing fetch-call-count tests
unchanged. `resumeActiveJobs()` rehydrates a document's tracked jobs from `localStorage` and
falls back to `GET /api/documents/{id}/jobs` if the id was not available locally (cleared storage,
different browser/tab). A small `JobStatusBanner` (`frontend/src/components/JobStatusBanner.tsx`,
text in `frontend/src/lib/jobDisplay.ts`) shows accepted/running/succeeded/failed/canceled for a
recovered job on the document detail page, only while nothing on the page is already showing its
own live-run progress UI. A recovered `succeeded` job refreshes the OCR artifact (showing a
controlled message if that refetch itself fails); a recovered `failed`/`canceled` job shows the
backend's sanitized `error_message`, never raw text. This is explicitly **polling + `localStorage`,
v1** — no Redis/RQ/Celery, no WebSocket/SSE, no browser/OS/email push; a future push transport can
replace *how* the store learns about updates without changing the job contract, `JobStatus` shape,
or any component reading from the store. No OCR/PII detection, artifact contract, `OCR_EXECUTION_MODE`
semantics, Docker/Compose, or Makefile change. See
[ADR-0030](../docs/adr/0030-runtime-job-ux-notifications-v1.md).

**Latest checkpoint (Reading-text row construction lineage v1 — Phase 1, partial):** The first
genuinely builder-emitted (not post-render) raw↔canonical lineage mechanism. `reading_text.py`'s
`ReadingRow` gains an optional page-local `source_range`, attached once at collection time — exact
from persisted L10 geometry, or via a global-uniqueness match of a row's own text against the page's
raw lines for the primary pypdf-visitor path (reusing `text_geometry.py`'s exact-match discipline,
now shared as `segment_page_lines`/`collapse_line`) — and threaded only through the
plain-paragraph/body rendering path (`_join_continuations_with_flags`); a merge of rows unions their
ranges only when every contributing row has one and raw order stays non-decreasing, so a visual
(reading-order) merge of raw-reordered rows declines instead of risking a swallowed unrelated range.
Canonical offsets are computed by walking the same block/line join arithmetic the text was already
assembled with (`_join_blocks_with_lineage`, byte-identical to the existing `_join_blocks`), never by
searching the finished string — and `build_reading_text` only keeps the result when the exact
per-page strings it was computed against are still the ones being joined (an equality check),
discarding it entirely if repeated-margin filtering or a whole-document fallback later changes that
text. New `ReadingTextRowLineageMap` (`lineage_source: row_construction`) is preferred over
`geometry_projection` over `fallback_text_match` in `DocumentTextPackageLineageSummary` and the Text
Anchor Graph's per-token projection (new `canonical_row_construction` flag/count). This is
deliberately partial, not a claim of full coverage: party columns, tables, multi-column
reconstruction, metadata, and post-table rendering always decline row-construction lineage (those
spans keep falling back to the pre-existing post-hoc mechanisms, unchanged), and cell-level
granularity remains out of scope. No detection, active-PII-input, routing, schema-breaking,
pseudonymization, redaction, export, or dependency change; `reading_text` bytes are unchanged, proven
byte-identical across the full existing regression suite. See
[ADR-0032](../docs/adr/0032-reading-text-row-construction-lineage-v1.md) and the "Phase 1" gap
in [`text-anchor-architecture-feasibility-audit.md`](../docs/engine/text-anchor-architecture-feasibility-audit.md).
Next: extend real coverage to more rendering paths (re-scoped explicitly, not assumed), then the
feasibility audit's remaining two recommended branches, **`pii-binding-quality-suite`** and
**`review-result-v1`**.

**Latest checkpoint (PII binding quality suite — Phase 2):** Not an engine level change. Delivers
the feasibility audit's Phase 2: `PiiAnchorBindingSummary` gains additive
`anchor_bound_ratio`/`exact_bound_ratio` coverage metrics; a new synthetic regression corpus
(`backend/tests/test_pii_binding_quality_suite.py`) covers the audit's previously-untested hard
cases (adjacent same-line date+phone tokenizer fusion, a punctuation/character-swallowing
recognizer span, table-column canonical-range cross-contamination, a DOCX/no-geometry document)
plus a coverage-ratio floor gate. Scoping the fusion case found a **real, previously-untested
tokenizer edge case** — `document_text_anchors.py`'s phone pattern fuses a date directly adjacent to
a phone number into one raw anchor — intentionally left unfixed (per this phase's "do not tune
recognizers" guardrail) and instead regression-locked as an honest `partial` degrade, never a false
`exact` or a lost/merged entity. A builder-version identity-drift test proves the audit's stated
safety property directly: the anchor-derived `entity_id` is free to drift with the graph builder,
while the underlying occurrence id durable review decisions key on never does, plus a guard test
that neither durable JSONL-writing module (`pii_review_service.py`, `feedback_service.py`)
references an anchor id today. The frontend `fetchPiiEntityContract` now returns a discriminated
`ok`/`not_found`/`error` result instead of `T | null`, so `DocumentDetailPage.tsx` shows a distinct
"PII highlights could not be loaded" notice on a genuine fetch failure instead of rendering
indistinguishably from "no PII yet." No recognizer, detection, tokenizer, active-PII-input, or
binding-algorithm change. See [ADR-0033](../docs/adr/0033-pii-binding-quality-suite.md). Next:
**`review-result-v1`** (Phase 3, Review L8) is the last of the feasibility audit's three
recommended branches.

**Latest checkpoint (Review L8 `review_result` artifact — Phase 3, final audit branch):** Not an
engine level change. Delivers the feasibility audit's Phase 3: a new immutable
`PiiReviewResultArtifact` (same envelope/persistence pattern as `PiiArtifact`/`TextArtifact`),
keyed occurrence-id-primary (never on anchor-derived identity, per the audit's guardrail and
ADR-0033's drift finding). `set_pii_review_decision` still appends its JSONL record exactly as
before, then persists a fresh immutable snapshot after every decision; new
`GET …/pii/review-result` returns the latest one. `PiiReviewResult` gains additive
`stale_decision_count`/`has_stale_decisions`: decisions recorded against a since-superseded
`pii_result` were already never silently reapplied (unchanged) — this makes that fact explicit
instead of looking identical to "nothing was ever reviewed," surfaced in `GET …/pii/review` and a
new `DocumentDetailPage.tsx` notice. The JSONL log remains the append-only write-time source of
truth (migration path documented in the ADR, not executed); no SQLite introduced, no
detection/`pii_result`-schema/active-PII-input/pseudonymization/redaction/export change; existing
`GET …/pii/review`/`POST …/pii/review/decisions` behavior is unchanged except for the two additive
fields. See [ADR-0034](../docs/adr/0034-review-l8-review-result-artifact.md). This was the last of
the feasibility audit's three recommended branches (Phases 1–3); the next engine priority should
re-run the checkpoint loop against this file's current-sequence section rather than continuing that
specific audit's list.

**Latest checkpoint (PII validation transparency report):** No engine level change. The Dev View
renders the already-stored `PiiValidationSummary` from the latest immutable `pii_result` as a
readable report: kept/dropped/score-down counts plus deterministic fixed reason-code counts. Legacy
artifacts without the optional summary and runs with validation disabled remain explicit states.
No metric is recomputed, no candidate/entity/document text is added, and detection, recognizers,
artifact schemas, APIs, dependencies, benchmark logic, active PII input, pseudonymization,
redaction, and export are unchanged. Review L8 and this planned transparency slice are closed.
Next: Benchmark L9 per-profile reporting, then the checkpointed OCR-lineage/PII-L13 choices above.

**Latest checkpoint (Benchmark L9 — per-profile reporting):** Benchmark/Regression advances from
L8 to **L10 cumulative** because L9 is now delivered and the L10 OCR confidence/coverage slice was
already present. One read-only invocation loads the newest immutable `pii_result` per configured
profile and document, then emits side-by-side P/R/F1 and validation aggregates in JSON, Markdown,
console output, and `benchmark_profiles.csv`. Missing profile artifacts are explicit zero-coverage
states and are never generated by the runner. The legacy global/latest-artifact report remains
compatible. No API call, job, detection, private input, dependency, runtime, or artifact change is
introduced; privacy guards still run before report files are written. Next: the scoped
construction-time OCR lineage coverage plan above.

**Latest checkpoint (Construction-time post-table row lineage):** No engine level change. ADR-0032's
partial builder-emitted lineage now covers an additional deliberately narrow path: an unchanged
post-table total or standalone row retains its pre-attached raw range while rendering; the synthetic
`SUMMEN` heading, table cells/rows, metadata, party/multi-column reconstruction, and joined
post-table prose still decline rather than guess. Canonical reading-text bytes, raw offsets, active
PII input, artifacts, APIs, dependencies, detection, review, pseudonymization, redaction, and export
are unchanged. The 0–19 OCR/Text level remains L15; next is the prerequisite checkpoint before PII
L13/Review L9 completion.

**Latest checkpoint (PII L13 / Review L9 direct decision lineage):** PII/Sensitive-Data advances
from L12 to **L13 done** and Review from L8 to **L9 done**. New decision-log records and immutable
`review_result` snapshots carry the direct `text_result` id alongside the exact PII artifact id;
the review API exposes that additive link. Legacy records remain readable. Existing stale behavior
is unchanged: decisions never silently reapply across a new PII artifact, and the stale count stays
explicit. No detection, active input, anchors, SQLite, dependency, pseudonymization, redaction, or
export change. Next: PII L14 / Review L10 manual add of missed entities remains checkpoint-gated.

**Latest checkpoint (PII L14 / Review L10 — manual add scope, docs-only):** Not an engine level
change; PII L14 and Review L10 both remain `⛔ open`. Scopes the architecture for the step named at
the end of the previous entry. An audit of `pii_review_service.py`, `schemas.py`,
`pii_entity_contract.py`, `pii_anchor_binding.py`, and the frontend review components found four
load-bearing constraints a naive implementation would break: `pii_result` stays
immutable/detector-only; `AnchorBoundPiiEntityV1.source_observations` structurally requires a
detector observation (`Field(min_length=1)`) and even its evidence-only fallback identity derives
from a `PiiEntity`'s raw offsets, so a human-added span with no detection has no path into that
model; `PiiReviewResultArtifact`/`PiiReviewResult` are occurrence-id-primary and
`PiiReviewOccurrence.occurrence_id` *is* `PiiEntity.id` (ADR-0033/ADR-0034's deliberate choice); and
no actor/origin field exists anywhere in review persistence today (`PiiReviewDecisionRecord.source`
is a static request-source tag, not a per-record origin marker). The scoped decision: a new
`manual_addition` record variant appended to the existing `pii_review_decisions.jsonl` log, and an
additive `PiiReviewResult.manual_additions` list — never merged into `pii_result` or the anchor-bound
entity contract. Canonical-text (`reading_text`) offsets are captured at add time (matching the
acceptance criterion already stated in `pii-engine-levels.md`/`review-feedback-levels.md`), with a
best-effort raw-span reverse projection reusing the *existing* `reading_text_map`/anchor projection
machinery (exact/partial/unmapped, never a new matching heuristic); staleness keys off
`text_artifact_id` rather than a `pii_result` artifact id, since a manual addition has no originating
detection to key on; the entity-type picker is constrained to the current `pii_result`'s own
`PiiContent.configured_entity_types`; and once created, an addition's own accept/keep/reject
reuses the existing `POST …/pii/review/decisions` endpoint under a new
`target_type: "manual_addition"` rather than a new edit/delete action. The frontend gap is real and
explicitly named: text-selection capture, an entity-type picker, and a visually distinct rendering
for human-added spans are net-new primitives — none exist in `PiiTextViewer.tsx`/
`ReviewTextViewer.tsx`/`PiiReviewGroupList.tsx` today. No detection, `pii_result` schema,
anchor-graph, active-PII-input, pseudonymization, redaction, export, dependency, or code change is
introduced by this checkpoint. See
[ADR-0035](../docs/adr/0035-pii-l14-review-l10-manual-add-scope.md). Next: implement this design as
the `pii-l14-manual-add-v1` branch, then re-run the checkpoint loop.

**Latest checkpoint (PII L14 / Review L10 — manual add v1, implemented):** PII advances from L13 to
**L14 done**; Review advances from L9 to **L10 done**. Implements the design scoped in the previous
entry: `PiiManualAddition`/`PiiManualAdditionRecord`/`PiiManualAdditionRequest`/
`PiiManualAdditionAck` in `schemas.py`; a new `pii_manual_addition.py` module whose
`resolve_canonical_span_to_raw` filters the Text Anchor Graph's existing raw↔canonical anchor
pairing rather than adding a new matching heuristic (no anchors overlap → `unmapped`; full
canonical coverage with a contiguous raw span → `exact`; otherwise a raw envelope, `partial`); and
`add_pii_manual_entity`/`POST …/pii/review/manual-additions` in `pii_review_service.py`/`api/pii.py`.
`_load_latest_decisions`, `_count_stale_decisions`, and `_target_exists` became target-type-aware:
entity-group/occurrence items stay scoped to the exact current `pii_result` artifact id (unchanged
behavior), while manual-addition items scope to `text_artifact_id` instead, since a manual addition
has no detector origin to key on — a PII re-run alone never makes one stale, only a new text
artifact does. Manual additions are never merged into `pii_result` or `AnchorBoundPiiEntityV1`; they
surface only through the additive `PiiReviewResult.manual_additions` list, and an addition's own
accept/keep/reject reuses the existing decision endpoint (`target_type: "manual_addition"`) rather
than a new action. Frontend: `getCharacterOffsetsFromSelection` (`textSelection.ts`, using the
`Range.setEnd` + `toString().length` technique, wired only into the canonical reading-text view);
`buildManualAdditionHighlights` (`piiHighlights.ts`, a display-only merge into the existing
highlight-building pipeline — canonical always, raw only when the reverse projection is exact —
never touching the backend contract); a distinguishing `ring-2 ring-sky-500` highlight plus
"Manuell hinzugefügt" tooltip text for `origin: "human"` spans in `PiiTextViewer.tsx`; a "Manuelle
Ergänzungen" list in `PiiReviewGroupList.tsx` reusing the exact same decision-`<select>` pattern as
groups/occurrences; and a new `AddPiiManualEntity.tsx` panel (selection preview, an entity-type
picker sourced from the run's own `configured_entity_types`, submit) wired into
`DocumentDetailPage.tsx`. `make lint`/`make typecheck`/`make test` pass for both backend (mypy,
Ruff, full pytest suite) and frontend (tsc, ESLint, full Vitest suite); a live `make up` browser
session confirmed the full flow end to end — selecting "2019" in a synthetic DOCX's reading text,
adding it as `DATE_TIME`, an exact raw-span resolution, the distinguishing highlight/tooltip, the
review-list entry, a `false_positive` decision removing the highlight and flipping the status, and
`GET …/pii` / `GET …/pii/entity-contract` staying byte-identical (7/7 entities, the manual addition
absent from both) before and after. No dependency, recognizer, detection, `pii_result` schema,
anchor-graph, active-PII-input, pseudonymization, redaction, or export change. See
[ADR-0035](../docs/adr/0035-pii-l14-review-l10-manual-add-scope.md). Next: re-run the checkpoint
loop against this file's current-sequence section for the next engine priority.

**Latest checkpoint (Unified Dev View entity review cards):** No engine level or contract change.
The Dev View no longer renders detector entities once in `PiiEntityList` and again in the separate
grouped `PiiReviewGroupList`. Each detected-entity card now combines recognizer evidence, dev
feedback, current binding status, and an occurrence-level `pseudonymize`/`keep`/`false_positive`
decision; refreshing that decision still uses the existing review API and keeps text highlights in
sync. Clicking a text highlight scrolls to the same unified card. The grouped review UI remains
unchanged in User View, while Dev View retains a separate section only for human-added entities
that have no detector card. No backend, artifact, detection, review semantics, manual-addition,
dependency, or privacy-boundary change.

**Checkpoint loop:** after every engine PR, record which level changed, confirm OCR/Text is still
sufficiently ahead of PII/Redaction, check for benchmark/feedback-driven re-prioritisation and
config/artifact drift, and update state/docs; after every third PR, re-confirm or adjust the next
three PRs (see the plan's checkpoint loop).

## Dev maintenance

- `make docker-df` remains as a read-only Docker disk-usage check. Prune/cleanup targets were
  removed from the Makefile in Phase 3.6 to keep the default runtime surface small and avoid
  broad Docker cleanup actions in project commands.

## Active constraints

- Docker-first; no host-local application toolchain is required.
- Keep changes focused and `.ai/` files concise.
- Do not read or commit private material under `volumes/`.
- Follow the approval, branch, and PR rules in [`AGENTS.md`](../AGENTS.md).
