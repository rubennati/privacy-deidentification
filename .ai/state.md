# Current State

> If this file conflicts with the current branch or commits, trust git.

- Current phase: **OCR structured-content foundation / PII grouping**.
- Current objective: complete OCR/Text L11 table/form reconstruction while preserving the completed
  L10.5 canonical-reading foundation and the raw-text-only PII boundary; PII L11 entity grouping
  remains the next planned engine step.
- Branch policy: feature and documentation PRs target `dev`; `main` is the curated user-stable
  branch. Windows install/update tooling always follows `main`.

## Product snapshot

- Docker Compose runs a React/Vite SPA behind nginx and a private FastAPI backend.
- The product supports upload, document listing/deletion, Audit, OCR/Text, detection-only PII, and
  lineage-safe manual inspection. It does not redact, anonymize, or pseudonymize documents.
- Originals, metadata, and immutable derived artifacts use separate validated storage boundaries.
- OCR/Text routes each PDF page between a usable text layer and the adapter-bound PaddleOCR runtime;
  OCR pages store additive engine-reported page/line confidence metrics on `text_result`, and every
  successful OCR/Text run appends a metrics-only `quality_report` linked to the exact
  original/audit/text artifacts. DOCX extraction includes paragraphs, tables, headers, and footers.
  OCR/Text artifacts may also carry optional span-backed L11 tables, fields, and sections.
- PII uses Presidio/spaCy behind an adapter, named profiles, AT/DE and domain recognizers, candidate
  validation, and reproducible engine settings.
- The local private benchmark measures routing and PII quality from existing artifacts. Its
  committed test suite uses synthetic data; private corpus data remains under git-ignored volumes.

## Engine maturity snapshot (0–19)

- **OCR/Text: L11 done (built on the required L10.5 step).** Each successful PDF/image/DOCX OCR/Text
  run now stores additive views beside immutable technical raw `text_result.text`: canonical
  `reading_text` (L10.5), `readable_text` (L8), `layout_text_result` (L9 slice), and
  `pii_input_text` (internal L9 slice). The existing
  metrics-only `quality_report` continues to carry source mix, audit-quality counts, confidence,
  coverage, and exact original/audit/text lineage. Reruns preserve old artifacts; the benchmark
  prefers a lineage-matching report and falls back for legacy data. Technical raw text, routing, and
  active PII input remain unchanged. OCR L9/L10/L10.5 additionally deliver:
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
  - `structured_content` (L11) — optional versioned per-page tables/cells, label/value fields, and
    heading-bound sections. Table cells and field values reference canonical/page spans rather than
    duplicating raw content; short labels/headings, source, confidence, flags, and optional L10 line
    bounds preserve semantic context. Conservative deterministic heuristics cover delimiter/aligned
    tables and common German/English form labels across PDF text-layer, OCR/image, and one logical
    DOCX page. Partial structures are flagged rather than invented. It supports future
    context-preserving pseudonymization but does not perform placeholder generation, mapping,
    pseudonymization, redaction, export, or any PII-input switch. Benchmark loaders ignore it.
- **PII/Sensitive-Data: L9 done; L10 partial.** Dev-only human-feedback capture exists; grouping
  (L11), overlap resolution (L12), and binding review (L13) remain open.
- **Review/Human-Feedback: L2 production; L3–L5 dev-only.** Grouping (L6) and a lineage-bound
  `review_result` overlay (L8) remain open.
- **Benchmark/Regression: L8 done; out-of-order L10 OCR confidence/coverage slice delivered.** L9
  per-profile reporting in one run is next.
- **Redaction/De-Identification: L0 by design.** It remains blocked on mature OCR, PII, and review
  foundations.

See [`docs/engine/`](../docs/engine/README.md),
[ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md), and
[ADR-0017](../docs/adr/0017-entity-taxonomy-and-risk-classes.md).

## Dev feedback boundary

- When `ENABLE_DEV_ENGINE_SETTINGS=true`, per-entity feedback is appended locally to
  `volumes/document-data/<document_id>/feedback/pii_feedback.jsonl`.
- New writes must match an entity in the referenced `pii_result` by type, offsets, and recognizer;
  summaries ignore historical lines that do not match that artifact.
- This is a gated analysis side-channel, not a learning system and not the binding review artifact.
- The structured fingerprint excludes raw document/entity text and optional `text_hash` is limited
  to a SHA-256 digest. Comments are short reviewer notes and must not contain copied document text,
  OCR text, or raw PII; the file still belongs inside the protected document-data boundary.

## Governance checkpoint

- Core OCR, NER, redaction, and pseudonymization intelligence comes from established tools behind
  adapters.
- Adapter-bound Presidio pattern recognizers, context rules, candidate validation, domain
  recognizers, and small deterministic heuristics are permitted only when documented, tested,
  benchmarkable, reviewable, and auditable.
- Major architecture/dependency changes, large opaque rule systems, or ad-hoc intelligence require
  human approval before implementation.

## Immediate next steps

The binding OCR/PII sequence, cadence, and next-12-PR list live in
[`docs/engine/ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md)
([ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md)). **Current priority after OCR L11:
PII/Sensitive-Data L11 entity grouping**, now that structured content builds on the L10.5
canonical-reading/raw-text contract, L10 span geometry, L9 layout-aware blocks, readable text (L8),
confidence capture (L6), and `quality_report` (L7).

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

The checkpoint leaves OCR/Text at L11 (built on the L10.5 prerequisite), PII L10 partial, and
Redaction L0; after reconfirming the next-three cadence, the plan is:

1. Interleave PII **L11 — entity grouping + occurrences** without changing detection.
2. Advance PII **L12 — overlap resolution** once grouping is in place.
3. Add the immutable, lineage-bound **Review L8 `review_result`** foundation before binding review
   decisions; keep `pii_result` immutable.

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

**Latest reading-text regression checkpoint:** OCR/Text remains at L11. Canonical reading-text
heuristics now recognize conservative 3+ column tables, keep multiline descriptions with their
rows, preserve ordinal right-aligned values, separate bounded invoice party/detail columns, and
filter repeated page-margin/page-number rules. Closely spaced long prose rows after tables now join
conservatively while label/value rows and larger paragraph gaps remain boundaries. Synthetic
positive and must-not-trigger regressions cover flat facts, offer metadata, party columns,
tables/totals, paragraph boundaries, and repeated margins. Raw text, PII input, routing,
dependencies, artifact versions, and the next engine cadence are unchanged.

**Checkpoint loop:** after every engine PR, record which level changed, confirm OCR/Text is still
sufficiently ahead of PII/Redaction, check for benchmark/feedback-driven re-prioritisation and
config/artifact drift, and update state/docs; after every third PR, re-confirm or adjust the next
three PRs (see the plan's checkpoint loop).

## Dev maintenance

- Safe Docker cleanup targets exist: `make docker-df`, `make docker-prune`,
  `make docker-prune-project`, `make dev-rebuild`. None of them delete volumes, uploads, or
  document data.

## Active constraints

- Docker-first; no host-local application toolchain is required.
- Keep changes focused and `.ai/` files concise.
- Do not read or commit private material under `volumes/`.
- Follow the approval, branch, and PR rules in [`AGENTS.md`](../AGENTS.md).
