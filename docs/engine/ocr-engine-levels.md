# OCR / Text Engine — Levels 0–19

The OCR/Text engine turns an uploaded document into the **best possible machine-readable text**,
preserving structure as far as reasonably possible, so the PII engine and human reviewers work on
trustworthy input. It is the first sub-engine in the [north star](README.md#north-star).

The output notions are defined in [`engine-artifacts.md`](engine-artifacts.md):

- **`text_result.text`** — the legacy, offset-stable **technical raw text** used by PII today.
- **`reading_text`** — the **canonical reading text**: deterministic, block-aware product text and
  intended future PII/placeholder candidate once lineage is sufficient.
- **`readable_text`** — a *human-readable* normalization that keeps the same content while making
  prose easier to read; retained as the earlier L8 rendering.
- **`layout_text_result`** — a layout-preserving rendering concerned with visual structure and
  reading order.

Level numbers are cumulative: each level assumes the ones below it. They are **not** comparable to
the PII, Review, Benchmark, or Redaction ladders. This engine uses the **0–19 maturity scale**
([why 0–19](README.md#maturity-scale)); a mapping from the previous 0–10 ladder is in
[Legacy scale mapping](#legacy-scale-mapping-010--019).

**Current standing:** **L14 reached (L0–L10 done plus the required L10.5 contract step, then L11,
L12, L13, and L14).** Each successful OCR/Text run now persists additive readable/layout views, versioned
ordered/typed `layout_blocks` with coarse normalized page bounds, and additive `text_geometry` that
maps technical raw line spans to page-local line boxes (`pdf_points` for text-layer, `image_pixels`
for OCR). L10.5 added versioned `reading_text`, its heuristic/fallback status and non-sensitive
flags, and made it the default product reading view. L11 adds optional versioned
`structured_content` with span-backed tables, fields, and sections for PDF, OCR/image, and DOCX
content. L12 adds deterministic multi-column reading-order reconstruction, fused table-header
handling, and conservative geometry-bound label/value pairing in canonical `reading_text`. L13 adds
table/form reconstruction v2: geometry-only table detection with no header-keyword requirement,
partially fused (not just fully fused) header recovery, and multiline label/value continuation for
both `reading_text` and `structured_content` fields. L14 adds additive, optional, versioned
`quality_evidence`: metrics-only provenance, reconstruction, page-zone, and lineage-coverage evidence
for every run (offsets, counts, flags, page zones, coarse bounds, and stable reason codes — never raw
text), so quality is measurable and regression-safe without changing any text. Technical raw text,
routing, active PII input, PII decisions, public API shape, and the `quality_report` artifact remain
unchanged; L10 geometry provides source anchoring and traceability for review/debug and future
placeholder mapping, and L11/L12/L13 structure supports future context-preserving pseudonymization —
none of them perform pseudonymization, placeholder mapping, document export, or pixel-perfect visual
redaction.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Extraction basics | 0–3 | Store bytes, get embedded text, lineage, OCR runtime |
| Quality routing | 4–7 | Text-layer quality gate, page routing, confidence, `quality_report` |
| Readable & structured | 8–11 | Human-readable text, layout order, bounding boxes, tables/forms |
| Understanding & assist | 12–14 | Layout reconstruction, document understanding, local AI assist |
| De-identification readiness | 15–19 | Redaction-ready geometry, reproducibility, observability, regression gate, production |

---

## Level 0 — Upload only  ✅ *done*

- **Description:** accept and safely store a document; extract nothing.
- **Engine must:** validate type/size/magic bytes, store a byte-identical original, record an
  original artifact + SHA-256.
- **Artifacts:** `document.json`, `original_artifact`.
- **Acceptance:** a valid file is stored once, addressable by id, with a verifiable digest; invalid
  files are rejected with a clean error and no text is produced.
- **Boundary to L1:** L0 stores bytes only; L1 is the first level that produces any text.

## Level 1 — Basic embedded text extraction  ✅ *done*

- **Description:** get the *embedded* text out of text-native documents.
- **Engine must:** extract a PDF text layer (pypdf) and DOCX text (table-aware `docx_extraction.py`),
  producing a single canonical text string per document.
- **Artifacts:** `text_result` (serving as `best_text_result`).
- **Acceptance:** a text-native PDF/DOCX yields deterministic text; Audit and OCR/Text agree on DOCX
  character counts.
- **Boundary to L2:** L1 produces text; L2 makes that text an immutable, lineage-referencing
  artifact with a per-page source.

## Level 2 — Immutable text artifact + source lineage  ✅ *done*

- **Description:** make text a first-class, immutable artifact that records where each part came
  from and what it was derived from.
- **Engine must:** persist `text_result` as an immutable JSON artifact; record per-page `source`
  (`text_layer`/`paddleocr`), an `input_artifact_id` (original) and `input_audit_artifact_id`
  (audit); resolve "latest" by creation time; mark downstream artifacts stale when the input changes.
- **Artifacts:** `text_result` with lineage fields and per-page source.
- **Acceptance:** a re-run creates a new `artifact_id` (never mutates an existing one); every page
  carries a source; a PII/review result bound to an older text artifact is detectably stale.
- **Boundary to L3:** L2 handles text-native input only; L3 adds the OCR runtime for pages that have
  no usable text layer.

## Level 3 — Basic OCR runtime  ✅ *done*

- **Description:** read text off images and scanned pages at all.
- **Engine must:** render PDF pages to raster (pdf2image/Poppler) and run a local OCR engine
  (PaddleOCR) behind an adapter; provision models locally; fail loudly (`503`) when the runtime or
  models are missing instead of downloading at request time.
- **Artifacts:** `text_result` with per-page `source = paddleocr`, `ocr_used = true`.
- **Acceptance:** an image document and a text-layer-free PDF page produce recognised text via the
  provisioned local models; a request that genuinely needs OCR returns `503` when the runtime is
  absent, never garbage.
- **Boundary to L4:** L3 *can* OCR; it does not yet decide *whether* a page needs OCR.

## Level 4 — Text-layer quality gate  ✅ *done*

- **Description:** judge, per page, whether an existing text layer is trustworthy or broken/encoded.
- **Engine must:** assess each PDF page's character/token plausibility with a dependency-free
  heuristic (`text_quality.py`) into `GOOD / LOW_CONFIDENCE / BROKEN / EMPTY`, and record it
  additively on the audit page (`text_quality_status/score/reasons`, `recommended_text_source`,
  `needs_ocr`) — **metrics only, never the page text**.
- **Artifacts:** `audit_result` with per-page quality verdict.
- **Acceptance:** a broken/encoded text layer is classified `BROKEN`; a clean page `GOOD`; a blank
  page `EMPTY`; verdicts are covered by unit tests and contain no page text.
- **Boundary to L5:** L4 *classifies*; L5 *acts* on the classification by routing each page.

## Level 5 — Page-level OCR routing / fallback  ✅ *done — current baseline*

- **Description:** per page, choose text layer vs OCR — never OCR a good page, never trust a broken
  one.
- **Engine must:** route each PDF page independently on the audit's `needs_ocr`
  (`GOOD`/`LOW_CONFIDENCE` keep the text layer; `BROKEN`/`EMPTY` use OCR); mark a document `pdf_mixed`
  when it mixes both; fall back to the `has_text_layer` rule for audits predating the gate; return
  `503` (never garbage) when a page needs OCR and the runtime is missing.
- **Artifacts:** `text_result` with per-page routed source; `audit_result` routing verdicts.
- **Acceptance:** a clean text PDF never renders a page or initialises OCR; a mixed PDF OCRs only the
  broken/empty pages; a broken layer with no OCR runtime returns `503`.
- **Boundary to L6:** L5 chooses a source but does not report *how confident* the OCR of a page is.

## Level 6 — OCR confidence capture  ✅ *done*

- **Description:** report per-page OCR confidence so quality is measurable and regressions are
  visible.
- **Engine must:** capture valid `rec_scores` from the PaddleOCR payload, preserve the recognized
  text byte-for-byte, and surface an arithmetic mean per OCR page plus per-line metrics where
  reported. Missing or invalid scores degrade to `null`/an empty list rather than failing OCR.
- **Artifacts:** additive `ocr_confidence` and `ocr_line_confidences` fields on
  `text_result.pages[]`. Line metrics contain only line index, confidence, and character count — no
  duplicate raw line text. Existing immutable `audit_result` artifacts are not mutated or extended
  after routing.
- **Acceptance:** OCR-routed PDF pages and image pages carry numeric confidence when PaddleOCR
  reports valid scores; text-layer pages carry no invented confidence; the benchmark reads and
  aggregates the metrics without copying raw text.
- **Boundary to L7:** L6 produces per-page confidence numbers; L7 aggregates them into a
  document-level `quality_report` that combines audit routing/quality data with text OCR confidence.

## Level 7 — `quality_report` artifact  ✅ *done*

- **Description:** a first-class per-document quality summary so text quality can be tracked and
  gated over time.
- **Engine must:** emit an immutable `quality_report` after every successful OCR/Text run, with
  source mix, page coverage, audit quality counts, and OCR confidence summary, linked to the exact
  original, `audit_result`, and `text_result` — **counts/statuses only, no page text**.
- **Artifacts:** `quality_report` (see [`engine-artifacts.md`](engine-artifacts.md)).
- **Acceptance:** PDF, image, and DOCX runs create lineage-bound reports; reruns append new reports
  without mutating old artifacts; the benchmark prefers a lineage-matching report and retains a
  legacy audit/text fallback without copying raw text.
- **Boundary to L8:** L0–L7 concern the *canonical* text and its quality; L8 introduces a separate
  *human-readable* rendering.

## Level 8 — Human-readable text output  ✅ *done*

- **Description:** produce text a human can actually *read* — stable paragraphs, sensible line
  breaks, de-hyphenation — distinct from the raw canonical string.
- **Engine must:** post-process the canonical text into a readable rendering (paragraph joins,
  hyphenation repair, whitespace normalisation) **without** mutating `best_text_result`; keep both.
- **Artifacts:** unchanged `best_text_result` **plus** a first `readable_text` (human-readable
  rendering). The layout-preserving `layout_text_result` follows at L9. Field names and invariants are
  fixed by the [OCR/Layout text contract](ocr-layout-text-contract.md).
- **Acceptance:** a readable rendering exists alongside a byte-stable canonical text; PII offsets
  still reference the canonical text.
- **Delivered:** `readable_text` is an additive optional field on `text_result`. It deterministically
  normalizes line endings, trims trailing whitespace, joins paragraph lines conservatively, repairs
  simple line-break hyphenation, and inserts visible page markers between canonical pages. Empty
  text degrades to `null`; DOCX/image/OCR/mixed-PDF runs participate without changing canonical text
  or page text.
- **Boundary to L9:** L8 reflows text heuristically; L9 orders text by real block/line geometry.

## Level 9 — Layout-aware text  ✅ *done*

- **Description:** preserve reading order and block structure (columns, headings, paragraphs) so text
  reflects the page, not a top-to-bottom character dump.
- **Engine must:** obtain block/line geometry (e.g. PyMuPDF for PDFs, OCR block boxes for scans) and
  order text by layout; annotate blocks with type (heading/body/caption).
- **Artifacts:** unchanged `layout_text_result` plus `layout_blocks_version = "1"` and additive
  `layout_blocks` with page/order, conservative type, text, extraction source, and coarse normalized
  bounds. These bounds are display/ordering regions, not L10 geometry.
- **Acceptance:** multi-column and header/footer pages produce human-sensible reading order; the
  canonical text remains the PII input.
- **Delivered:** all L9 additions leave `text_result.text` byte-stable with PII still running on
  canonical text:
  - `readable_text` — an optional field on `text_result`, produced for any non-empty canonical text
    with conservative normalization and visible page boundaries between canonical pages.
  - `layout_text_result` — an optional field on `text_result`, pypdf `extraction_mode="layout"`,
    PDF text-layer pages only; OCR/DOCX/image → `null`.
  - `pii_input_text` — a second optional field on `text_result`: an internal, experimental,
    detection-optimised reading-order reconstruction for PDF text-layer pages (left/right block
    grouping, row-wise table rows from a known header line), built from pypdf's own text-position
    data (`visitor_operand_before`, no new dependency). **Not** the active PII input — see
    [`ocr-layout-text-contract.md`](ocr-layout-text-contract.md).
  - `layout_blocks` — optional versioned typed blocks built deterministically from existing pypdf
    positions or transient PaddleOCR polygons. Blocks use page-relative 0..1 coarse bounds, source,
    and OCR confidence when available; missing/invalid geometry degrades to an explicit fallback
    block. Heading/body/caption/header/footer typing is conservative and positional/typographic.
  A `text_lineage_map`, precise line/word geometry, canonical-offset lookup, and a general table
  detector remain open at L10/L11. The existing layout string and Review UI behavior are unchanged.
- **Boundary to L10:** L9 knows block order; L10 persists per-line coordinates mapped to canonical
  spans as reusable geometry.

## Level 10 — Bounding boxes / span geometry  ✅ *done*

- **Description:** persist per-line coordinates and link canonical-text offsets to page geometry.
- **Engine must:** store page-local line boxes for OCR (PaddleOCR polygons) and, where available,
  text-layer pages (pypdf text positions); expose a lookup from a canonical text offset range to the
  page boxes that produced it.
- **Artifacts:** additive `text_geometry_version = "1"` and `text_geometry` on `text_result`.
  `text_geometry` carries per-page line boxes (`TextLineGeometry`) that map a canonical span
  (`canonical_start`/`canonical_end` into `text_result.text`) and the matching page span
  (`page_start`/`page_end` into `pages[].text`) to page-local `x0/y0/x1/y1` bounds in the page's
  `coordinate_unit` (`pdf_points` for text-layer, `image_pixels` for OCR). Each page reports a
  `status` (`complete`/`partial`/`unsupported`) and the geometry reports overall `coverage` and
  `flags`. Line geometry carries no raw line text.
- **Delivered:** offsets are derived by matching page-local text segments against the immutable
  canonical page text — canonical `text`/`pages[].text` and their char counts stay byte-stable, PII
  still runs on canonical text, and legacy artifacts without geometry remain valid. When precise line
  boxes are not safely derivable, the page degrades to `partial`/`unsupported` with a coverage flag
  rather than guessing. DOCX has no page geometry (`text_geometry` stays `null`). The internal
  `resolve_span_geometry(text_geometry, start, end)` helper returns intersecting line boxes for a
  canonical span and never returns raw text.
- **Acceptance:** a canonical offset range resolves to one or more page boxes with correct page and
  coordinates on text-layer and OCR pages; mixed PDFs combine per-page geometry with partial coverage.
- **Boundary to L11:** L10 gives *where text is* (line level); L11 reconstructs *structured regions*
  (tables/forms) from it.
- **Product framing:** L10 provides line-level source anchoring for review/debug and traceability,
  and a foundation for future placeholder mapping toward AI-ready pseudonymized document generation.
  It does not perform pseudonymization, placeholder mapping, document export, or pixel-perfect
  visual redaction.

## Intermediate L10.5 — Canonical reading text / raw-text contract  ✅ *done*

- **Description:** separate the legacy technical extraction and offset coordinate system from the
  useful, deterministic main document text before L11 adds structured content.
- **Engine must:** preserve `text_result.text`, `text_char_count`, and `pages[].text` byte-for-byte as
  **technical raw text**; add optional versioned `reading_text` built in priority order from
  positioned/L10 geometry, L9 layout blocks, layout text, then safe raw-order fallback; keep major
  blocks, paired party columns, offer metadata, simple line-item rows, totals, and conservative
  paragraph joins readable without inventing or changing values.
- **Artifacts:** additive `reading_text_version = "1"`, `reading_text`, `reading_text_status`
  (`heuristic`/`fallback`), and non-sensitive `reading_text_flags` on `text_result`.
- **Acceptance:** the synthetic quote fixture produces the specified block-aware, pipe-delimited
  reading text; legacy artifacts validate; the Review User View defaults to **Kanonischer
  Lesetext**, while Dev View can inspect **Technischer Rohtext**, **Kanonischer Lesetext**, and
  **Layout-Text** separately.
- **Boundary:** this does not switch PII input, provide reading↔raw offset lineage, create
  `structured_content`, pseudonymize, map placeholders, redact, or export. PII and its highlights
  still use technical raw text until a tested lineage map makes a switch safe.
- **Boundary to L11:** L10.5 makes a useful plain-text document view; L11 emits explicit tables,
  fields, and sections as structured JSON rather than relying on text rendering heuristics.

## Level 11 — Table / form reconstruction  ✅ *done*

- **Description:** reconstruct tables and structured regions (invoices, cost breakdowns, forms) as
  structure, not a flattened run.
- **Engine must:** detect tables/forms and emit rows/cells and label/value pairs; keep a structured
  representation separate from canonical text.
- **Artifacts:** optional `structured_content_version = "1"` and `structured_content` on
  `text_result`, containing per-page tables/cells, label/value fields, and sections plus metrics-only
  counts/flags. Cells and values use canonical/page spans; raw table contents and field values are
  not duplicated. Short labels/headings remain inside the sensitive text artifact.
- **Delivered:** conservative deterministic delimiter/alignment and label/value heuristics use
  canonical page text and enrich results with L10 line bounds or L9 heading blocks when available.
  Uncertain tables are flagged partial/low-confidence rather than normalised into invented rows.
  DOCX uses one logical structured page while retaining its established pageless canonical model.
- **Acceptance:** representative tables round-trip into rows/cells usable downstream without
  corrupting canonical text; legacy artifacts validate, benchmark summaries ignore the structured
  payload, and PII still receives canonical text only.
- **Boundary to L12:** L11 reconstructs explicit tables/forms; L12 improves the document-level
  reading order that feeds those display and structure layers without changing the raw-text contract.

## Level 12 — Multi-column layout reconstruction  ✅ *done*

- **Description:** improve canonical reading order for complex multi-column and dense-layout
  documents before any PII, review, pseudonymization, or export use.
- **Engine must:** use existing row/line geometry to detect confident 2+ column prose regions,
  render each page-local column top-to-bottom, avoid treating ordinary tables or party/header blocks
  as prose columns, handle fused table headers only when following rows provide safe column
  positions, and pair form labels/values only when adjacent geometry is safe.
- **Artifacts:** no new artifact or schema version. Existing `reading_text` remains version `1` and
  gains non-sensitive flags such as `multi_column_reconstruction`, `dense_table_reconstruction`,
  and `label_value_pairing` when those deterministic paths run. `structured_content` remains the L11
  span-backed structure layer and stays compatible with the canonical/raw text model.
- **Delivered:** bounded heuristics cluster normalized x positions, require overlapping vertical
  ranges and prose-like density before column ordering, skip table-owned and party-heading-owned
  regions, split generic fused table headers only with real row positions, and keep low-confidence
  layouts in existing row order. Repeated margin cleanup remains document-level and additive.
- **Quality philosophy:** L12 is stability-first. Improvements must combine multiple weak signals,
  remain confidence-aware, and fall back rather than silently discard source information. A private
  corpus improvement is not acceptable when it risks unrelated document types; such gaps should be
  classified with the missing evidence documented for a later quality signal.
- **Acceptance:** synthetic tests cover two-column AGB/prose ordering, ordinary two-column tables
  that must not become prose columns, low-confidence fallback, fused table headers, adjacent
  label/value pairing, existing party columns, line-item tables, filename lists, and margin cleanup.
  Technical raw text, page text, active PII input, PII projection, review decisions,
  pseudonymization, redaction, export, dependencies, and public APIs remain unchanged.
- **Future evidence:** dictionary/lexicon checks, domain vocabulary, PDF-text-layer versus OCR
  comparison, second-engine agreement, OCR and layout confidence, document-type hints, review
  feedback, and benchmark gates are deferred additive signals. They should increase or decrease
  confidence, not make downstream PII/review/pseudonymization depend on unstable OCR guesses.
- **Boundary to L13:** L12 improves geometric reading order; L13 improves table/form reconstruction
  quality on top of that stabilized order.

> Migration note: earlier planning placeholders described OCR/Text L12 as multi-engine benchmark /
> selection. That capability is deferred to a later OCR-quality/benchmark spike. L12 now means the
> deterministic multi-column layout reconstruction described here; this avoids mixing the older
> placeholder meaning with the active 0–19 engine level.

## Level 13 — Table / form reconstruction v2  ✅ *done*

- **Description:** improve table and form/label-value reconstruction in canonical `reading_text` and
  `structured_content` after L12 reading-order stabilization, without regressing any L11/L12 safeguard.
- **Engine must:** detect repeated row structures from geometry/x-position alignment alone (no header
  keyword required), recover headers that are fused across more than one text fragment when following
  rows provide safe column evidence, keep multiline table descriptions and multiline label/value
  values attached to their owning row/field, and fall back to the existing safe behavior whenever
  evidence is not strong enough — never inventing columns, cells, or structure.
- **Artifacts:** no new artifact or schema version. Existing `reading_text` remains version `1` and
  gains non-sensitive flags `generic_table_reconstruction` and `multiline_value_pairing` alongside
  the existing L12 flags. `structured_content` remains version `1`; `StructuredField.flags` gains
  `multiline_value` for a value spanning more than one line. Both changes are additive and backward
  compatible — legacy artifacts without these flags remain valid.
- **Delivered:** a shared row-alignment helper extends both the keyword-header table renderer and a
  new geometry-only table detector, so a maximal run of 3+ consecutive rows sharing 3+ aligned
  columns is rendered row-wise even with no recognized header vocabulary; a 1- or 2-cell fused header
  is recovered from concatenated cell text using the same marker-based split already used for a
  single fused cell; an adjacent-row label/value pairing extends across following rows that stay in
  the same column, at normal line spacing, and do not themselves look like a new label, heading, or
  inline "label: value" fact; `structured_content` field detection gained the equivalent multiline
  continuation for both the inline and next-line label/value shapes.
- **Quality philosophy:** L13 keeps L12's stability-first bar. A private-corpus validation pass (see
  [`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md)) found and fixed one real
  regression risk before merge: an unrelated inline "Label: value" fact directly following a paired
  value, in the same column, was being absorbed as a value continuation. The fix adds an explicit
  stop condition (the same "starts a new label/value fact" check already used elsewhere in the
  module) and is covered by a synthetic regression test. After the fix, the full available private
  corpus (all documents pypdf could open; one encrypted document could not be opened, unrelated to
  this change) produces byte-identical `reading_text` before and after L13 — the new geometry-only
  table and multiline-continuation paths did not fire elsewhere in that corpus, which is expected:
  L13 does not force a capability to fire just to show a corpus improvement, and remains available,
  tested, for future documents matching those patterns.
- **Acceptance:** synthetic tests cover a header-keyword-free table detected from geometry alone, a
  partially fused (2-cell) header recovered from row evidence, a multiline table description staying
  attached to its row, totals/subtotals staying grouped after a geometry-only table, numeric rows not
  collapsing into prose, a multiline adjacent-row label/value value, must-not-trigger coverage for a
  short run below the row minimum, three-column prose staying on the L12 prose path instead of being
  reclassified as a table, an inline label/value line correctly stopping value continuation, and
  `structured_content` multiline field values for both inline and next-line label shapes plus a
  must-not-trigger case where a following recognizable field is not absorbed. All existing L11/L12
  regression tests continue to pass unmodified. Technical raw text, page text, active PII input, PII
  projection, review decisions, pseudonymization, redaction, export, dependencies, and public APIs
  remain unchanged.
- **Known limitation / deferred:** a page whose positioned-row extraction fails the existing
  raw-coverage safety check still falls back to plain raw order, and no version of table
  reconstruction (v1 or v2) can apply there — this is a pre-existing L10/L12 row-geometry-collection
  gap on some dense/complex table pages, not a table/form-reconstruction-logic gap, and remains open
  for a future OCR/Text level. Document-type/zone classification (the earlier placeholder meaning of
  this level) remains open and is not part of this L13 scope; see the migration note below.
- **Boundary to L14:** L13 improves table/form structure quality; L14 makes that quality — and the
  whole extraction chain's provenance and lineage — *measurable and explainable* without changing it.

> Migration note: earlier planning placeholders described OCR/Text L13 as document understanding
> (document type/section/zone classification). That capability remains open and is deferred to a
> later level once a private-corpus or product need justifies it; L13 now means the table/form
> reconstruction v2 described here, mirroring how ADR-0022 previously re-scoped L12. See
> [ADR-0024](../adr/0024-ocr-l13-table-form-reconstruction-v2.md).

## Level 14 — Quality evidence and lineage coverage  ✅ *done*

- **Description:** make OCR/Text quality *measurable, auditable, and regression-safe* by recording
  conservative quality evidence, provenance, and lineage coverage — **evidence before correction**,
  not automatic correction.
- **Engine must:** attach additive, optional, versioned `quality_evidence` to every new
  `text_result` that answers, from the artifact alone, where the text came from (PDF text layer,
  OCR, or fallback), whether page position/geometry and page zone were known, which parts were
  confidently reconstructed (table/form/multi-column) versus fell back, and how much of canonical
  reading text maps back to technical raw text and source geometry — using offsets, counts, flags,
  page zones, coarse bounds, and stable reason codes only, **never raw text**.
- **Artifacts:** additive `quality_evidence_version = "1"` and `quality_evidence` on `text_result`.
  It is a flat list of `QualityEvidenceItem`s (each with `evidence_id`, `level`, `type`, `status`,
  optional bounded `confidence`, stable `reason_code`, optional ranges/page/zone/bounds/related
  artifact, `flags`, and an integer-only `details` map) plus a `QualityEvidenceSummary`
  (`overall_status`, advisory `overall_score`, status/type counts, `warnings`, `blockers`,
  `reconstruction_summary`, `fallback_summary`, and a `QualityLineageCoverage` block). Legacy
  artifacts without it remain valid.
- **Delivered:** a deterministic builder (`ocr_quality.py`) derives evidence from already-computed
  inputs (source, pages, the reading result and its strategy flags, the reading↔raw map, span
  geometry, and structured content). Page zones (`header`/`footer`/`left_margin`/`right_margin`/
  `body`/`unknown`) are classified conservatively from existing geometry and are evidence only — they
  never delete, reorder, or reclassify text. Lineage coverage measures mapped/unmapped reading-text
  chars, mapping coverage ratio, exact/partial/unmapped span counts, source-geometry coverage, and
  structured-content references. `details` is `dict[str, int]` so no snippet or PII value can be
  stored by construction, and the schema validates that offsets stay inside the actual raw/reading
  text. Technical raw text, active PII input, PII projection/decisions, the `quality_report`
  artifact, benchmark payloads, dependencies, and public API shape are unchanged.
- **Acceptance:** synthetic tests cover normal/empty/fallback artifacts, table/form/multi-column
  reconstruction evidence, structured-content summaries, conservative header/footer/body/margin page
  zones, bounded confidence, stable reason codes, determinism, a no-raw-text guard, and lineage
  exact/partial/unmapped/coverage cases; a local metrics-only private-corpus pass confirmed coherent,
  leak-free evidence with byte-identical reading text.
- **Future evidence sources (deferred, additive):** dictionary/lexicon OCR-quality checks, multi-OCR
  agreement, and a local LLM for document-type/section/structure/quality-explanation hints are
  **evidence, not truth** — they may raise or lower confidence but must never silently rewrite
  OCR/Text or change PII decisions. See [ADR-0025](../adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md).
- **Boundary to L15:** L0–L14 produce, understand, and now *explain* text; L15 makes text+geometry
  *redaction-ready*.

> Migration note: earlier planning placeholders described OCR/Text L14 as local AI assist for hard
> pages (a local vision/OCR model behind an adapter; see the
> [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding)).
> That capability is deferred to a later level once a concrete need justifies it; L14 now means the
> quality evidence and lineage coverage described here, mirroring how ADR-0022/ADR-0024 re-scoped
> L12/L13. See [ADR-0025](../adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md).

## Level 15 — Redaction-ready text/geometry mapping  ⛔ *open*

- **Description:** provide the stable text↔geometry mapping that de-identification will build on.
- **Engine must:** guarantee a stable mapping from canonical-text offset ranges to page pixel boxes
  across a document, sufficient for the [Redaction engine](redaction-engine-levels.md) to black out
  or replace a reviewed span in the source rendering.
- **Artifacts:** a documented offset↔box mapping usable by redaction.
- **Acceptance:** for a reviewed span, the engine returns the exact page region(s) covering it, with
  no drift against the canonical offsets.
- **Boundary to L16:** L15 makes results *usable* for redaction; L16 makes them *reproducible* by
  recording engine settings.

## Level 16 — Reproducible OCR engine settings in artifact  ⛔ *open*

- **Description:** make every text result reproducible from recorded, pinned settings.
- **Engine must:** record the effective non-sensitive OCR engine settings (model dir, detection/
  recognition model names, engine versions) in the artifact, mirroring the PII `engine_settings`
  approach; pin model/engine versions.
- **Artifacts:** `engine_settings` on `text_result`/`quality_report`.
- **Acceptance:** two runs with the same inputs and recorded settings produce byte-identical
  canonical text; the settings are visible in the artifact.
- **Boundary to L17:** L16 records *what ran*; L17 measures *how it ran* (runtime/memory/errors).

## Level 17 — Observability & performance budget  ⛔ *open*

- **Description:** make OCR runtime, memory, and error rates observable against a budget.
- **Engine must:** capture per-page/per-document runtime, peak memory, and error rates as metrics
  (no text); define a performance budget.
- **Artifacts:** performance metrics on `quality_report`/`benchmark_result`.
- **Acceptance:** a run reports runtime/memory/error metrics; a page exceeding the budget is
  flagged.
- **Boundary to L18:** L17 measures performance; L18 turns quality/performance into a **gate**.

## Level 18 — Regression-gated OCR quality  ⛔ *open*

- **Description:** fail the build when OCR quality, coverage, or routing regresses.
- **Engine must:** run the benchmark in CI over a (synthetic/private) corpus and block a merge when
  coverage/confidence/routing drops below thresholds.
- **Artifacts:** a CI-gated `benchmark_result` with thresholds.
- **Acceptance:** an intentional quality regression fails the gate; a neutral change passes.
- **Boundary to L19:** L18 gates one dimension in CI; L19 is the whole engine, production-grade.

## Level 19 — Production-grade local OCR/Text engine  ⛔ *open*

- **Description:** reliable, observable, reproducible text extraction across the supported corpus.
- **Engine must:** combine routing, quality, layout, geometry, tables, and (optionally) multi-engine
  selection with monitoring, pinned versions, and regression gates.
- **Artifacts:** all of the above, versioned; stable `quality_report` + `benchmark_result`.
- **Acceptance:** text extraction meets agreed quality/performance thresholds on the benchmark corpus,
  is reproducible from pinned versions, and regressions fail the gate.
- **Boundary:** top of the ladder; further work is tool/accuracy improvement within this envelope.

---

## Engine settings that belong to this ladder

OCR runtime settings are analysed in [`engine-settings.md`](engine-settings.md). In short:

- **Runtime/provisioning (not maturity):** `OCR_MODEL_DIR`, the default runtime image,
  `OCR_EXECUTION_MODE`, `API_MEMORY_LIMIT`, `OCR_WORKER_MEMORY_LIMIT`, Poppler/tmpfs render
  workspace, MKL-DNN-off — operational config, chosen server-side.
- **Reproducibility (maturity — L16):** `OCR_DETECTION_MODEL_NAME`, `OCR_RECOGNITION_MODEL_NAME`
  and pinned engine/model versions determine *which* recognition capability ran and must be recorded
  in the artifact to make a result reproducible and comparable.
- **OCR quality drivers:** the model pair (mobile vs server, Latin vs default recognizer) and the
  quality-gate thresholds (`text_quality.py`) drive extraction quality and routing; the gate
  thresholds are code-level (unit-tested), not env-tunable, by design.

---

## Where the project stands (OCR/Text)

| Level | State | Evidence |
| --- | --- | --- |
| 0 Upload only | ✅ done | upload/core, `original_artifact` |
| 1 Basic text extraction | ✅ done | pypdf + table-aware python-docx |
| 2 Immutable artifact + lineage | ✅ done | immutable `text_result`, `input_*_artifact_id`, per-page source |
| 3 Basic OCR runtime | ✅ done | PaddleOCR adapter, model provisioning, `ocr-smoke` |
| 4 Text-layer quality gate | ✅ done | `text_quality.py` GOOD/LOW/BROKEN/EMPTY verdicts |
| 5 Page-level routing | ✅ done | per-page `needs_ocr` routing, `pdf_mixed`, `503`-not-garbage |
| 6 OCR confidence | ✅ done | additive page mean + metric-only line scores on `text_result`; benchmark summaries |
| 7 `quality_report` artifact | ✅ done | immutable metrics-only artifact with original/audit/text lineage; benchmark consumption |
| 8 Human-readable text | ✅ done | additive deterministic `readable_text`; canonical unchanged |
| 9 Layout-aware text | ✅ done | ordered typed `layout_blocks` with coarse normalized bounds; existing layout string preserved |
| 10 Bounding boxes / geometry | ✅ done | additive `text_geometry` line boxes mapping canonical spans to page-local bounds; `resolve_span_geometry` lookup; canonical unchanged |
| 11 Table / form reconstruction | ✅ done | optional span-backed `structured_content` for tables, fields, and sections; canonical/PII input unchanged |
| 12 Multi-column layout reconstruction | ✅ done | safe column ordering, fused table headers, and geometry-bound label/value pairing in `reading_text`; raw/PII input unchanged |
| 13 Table / form reconstruction v2 | ✅ done | geometry-only table detection, partially fused header recovery, and multiline label/value continuation in `reading_text` and `structured_content`; raw/PII input unchanged |
| 14 Quality evidence & lineage coverage | ✅ done | additive metrics-only `quality_evidence` (provenance, reconstruction, page zones, lineage coverage); no raw text; raw/PII input, `quality_report`, and benchmark unchanged |
| 15 Redaction-ready geometry | ⛔ open | prerequisite for [Redaction](redaction-engine-levels.md) |
| 16 Reproducible settings | ⛔ open | OCR `engine_settings` not recorded yet |
| 17 Observability / budget | ⛔ open | — |
| 18 Regression gate | ⛔ open | benchmark exists but is not a CI gate |
| 19 Production-grade | ⛔ open | — |

**What is achieved:** robust per-page routing that never OCRs a good page and never trusts a broken
text layer. On the local benchmark corpus, routing matched the expected category on 10 of 12
documents; the 2 "mismatches" were the gate routing *all* pages of a bad scan to OCR where a partial
fallback was expected — i.e. more conservative, not wrong.

**What is missing for the next level (L15 and beyond):**

1. Redaction-ready text↔pixel geometry (L15), reproducible OCR engine settings (L16), observability
   budgets (L17), a regression gate (L18), and production hardening (L19). Local AI assist for hard
   pages (the earlier placeholder meaning of L14, now deferred — see the migration note under L14),
   document type/section/zone classification (the earlier placeholder meaning of L13, deferred),
   word-level/redaction-ready geometry, placeholder mapping, export, dictionary/lexicon OCR-quality
   checks, and multi-OCR stay open at later levels/spikes, and are additive **evidence, not truth**.

See the [current sequence](roadmap.md#current-sequence) and
[later engine work](roadmap.md#later-engine-work) for the sequencing.

---

## Legacy scale mapping (0–10 → 0–19)

The engine previously used a 0–10 ladder. Historical citations can be translated with this table.

| Old (0–10) | Meaning | New (0–19) |
| --- | --- | --- |
| L0 Upload only | store bytes | **L0** |
| L1 Basic text extraction | embedded text | **L1** (+ **L2** lineage split out) |
| L2 Basic OCR runtime | PaddleOCR runtime | **L3** |
| L3 Page-level routing | quality gate + routing | **L4** (gate) + **L5** (routing) |
| L4 Quality report | confidence + `quality_report` | **L6** (confidence) + **L7** (report) |
| L5 Human-readable text | readable rendering | **L8** |
| L6 Layout-aware text | reading order/blocks | **L9** (+ **L10** geometry) |
| L7 Table reconstruction | tables/forms | **L11** |
| L8 Multi-engine selection | engine comparison | deferred later OCR-quality/benchmark spike; no longer active **L12** |
| L9 Local AI assist | hard-page assist | deferred later spike; no longer active **L14** (now quality evidence & lineage coverage) |
| L10 Production-grade | production | **L19** (+ **L15–L18** readiness/observability/gate) |
