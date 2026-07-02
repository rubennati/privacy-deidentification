# OCR / Text Engine — Levels 0–19

The OCR/Text engine turns an uploaded document into the **best possible machine-readable text**,
preserving structure as far as reasonably possible, so the PII engine and human reviewers work on
trustworthy input. It is the first sub-engine in the [north star](README.md#north-star).

Three output notions run through the levels and are defined in [`engine-artifacts.md`](engine-artifacts.md):

- **`best_text_result`** — the *canonical* text used by PII and review. Correctness first;
  reading order and layout are secondary.
- **`readable_text`** — a *human-readable* normalization that keeps the same content while making
  prose easier to read.
- **`layout_text_result`** — a layout-preserving rendering concerned with visual structure and
  reading order.

Level numbers are cumulative: each level assumes the ones below it. They are **not** comparable to
the PII, Review, Benchmark, or Redaction ladders. This engine uses the **0–19 maturity scale**
([why 0–19](README.md#maturity-scale)); a mapping from the previous 0–10 ladder is in
[Legacy scale mapping](#legacy-scale-mapping-010--019).

**Current standing:** **L10 reached (L0–L10 done); L11 is next.** Each successful OCR/Text run now
persists additive readable/layout views, versioned ordered/typed `layout_blocks` with coarse
normalized page bounds, and additive `text_geometry` that maps canonical line spans to page-local
line boxes (`pdf_points` for text-layer, `image_pixels` for OCR). Canonical text, routing, active PII
input, and `quality_report` remain unchanged; L10 geometry provides source anchoring and
traceability for review/debug and future placeholder mapping — it does not perform
pseudonymization, placeholder mapping, document export, or pixel-perfect visual redaction.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Extraction basics | 0–3 | Store bytes, get embedded text, lineage, OCR runtime |
| Quality routing | 4–7 | Text-layer quality gate, page routing, confidence, `quality_report` |
| Readable & structured | 8–11 | Human-readable text, layout order, bounding boxes, tables/forms |
| Understanding & assist | 12–14 | Multi-engine selection, document understanding, local AI assist |
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

## Level 11 — Table / form reconstruction  ⛔ *open*

- **Description:** reconstruct tables and structured regions (invoices, cost breakdowns, forms) as
  structure, not a flattened run.
- **Engine must:** detect tables/forms and emit rows/cells and label/value pairs; keep a structured
  representation separate from canonical text.
- **Artifacts:** `structured_document_result` (tables, sections, key-value pairs).
- **Acceptance:** representative tables round-trip into rows/cells usable downstream without
  corrupting the canonical text.
- **Boundary to L12:** L11 reconstructs structure with one engine; L12 compares engines and selects
  the best per page.

## Level 12 — Multi-engine benchmark / selection  ⛔ *open*

- **Description:** compare OCR/extraction engines and pick the best per page/document with evidence.
- **Engine must:** run more than one extraction path (e.g. PaddleOCR vs OCRmyPDF/Tesseract) behind
  the same adapter, score outputs, and select per page; record which engine won and why.
- **Artifacts:** `benchmark_result` (per-engine metrics), engine-selection annotation on pages.
- **Acceptance:** the benchmark shows, per engine, quality/runtime/memory, and the pipeline picks the
  best local engine per page reproducibly.
- **Boundary to L13:** L12 optimises *text quality*; L13 adds *document-level semantics*.

## Level 13 — Document understanding  ⛔ *open*

- **Description:** classify the document and its regions (document type, sections, semantic zones) to
  inform PII, review, and later redaction.
- **Engine must:** derive a document type/section model (deterministic or local-model based) and
  attach it to the artifact chain; assistive, never overwriting canonical text.
- **Artifacts:** document-classification/section annotations.
- **Acceptance:** representative documents receive a plausible type/section labelling that downstream
  stages can consume.
- **Boundary to L14:** L13 is rule/structure driven; L14 introduces a *local model* for the genuinely
  hard pages.

## Level 14 — Local AI assist for hard pages  ⛔ *open, optional*

- **Description:** use a **local** model to help on genuinely hard pages (bad scans, handwriting,
  marginalia) — assistive only.
- **Engine must:** run a local vision/OCR model behind an adapter, mark its output as
  low-confidence/assistive, and **never silently overwrite** canonical text; results are auditable
  and stay local.
- **Artifacts:** assistive text/annotations flagged `assistive = true`.
- **Acceptance:** on a hard-page set, assistive output is offered, clearly labelled, fully local, and
  only promoted to canonical through an explicit (reviewer/rule) decision. See the
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding).
- **Boundary to L15:** L0–L14 produce and understand text; L15 makes text+geometry *redaction-ready*.

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

- **Runtime/provisioning (not maturity):** `OCR_MODEL_DIR`, `INSTALL_OCR`, `BACKEND_MEMORY_LIMIT`,
  Poppler/tmpfs render workspace, MKL-DNN-off — operational config, chosen server-side.
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
| 11 Table / form reconstruction | ⛔ open | — |
| 12 Multi-engine selection | ⛔ open | single engine (PaddleOCR) |
| 13 Document understanding | ⛔ open | — |
| 14 Local AI assist | ⛔ open | — |
| 15 Redaction-ready geometry | ⛔ open | prerequisite for [Redaction](redaction-engine-levels.md) |
| 16 Reproducible settings | ⛔ open | OCR `engine_settings` not recorded yet |
| 17 Observability / budget | ⛔ open | — |
| 18 Regression gate | ⛔ open | benchmark exists but is not a CI gate |
| 19 Production-grade | ⛔ open | — |

**What is achieved:** robust per-page routing that never OCRs a good page and never trusts a broken
text layer. On the local benchmark corpus, routing matched the expected category on 10 of 12
documents; the 2 "mismatches" were the gate routing *all* pages of a bad scan to OCR where a partial
fallback was expected — i.e. more conservative, not wrong.

**What is missing for the next level (L11):**

1. Reconstruct tables and structured regions (rows/cells, key/value pairs) from the L10 line geometry
   as a structured representation kept separate from canonical text. Word-level geometry and
   placeholder-mapping/pixel-perfect coverage also remain open; L10 delivers line-level source
   anchoring only.

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
| L8 Multi-engine selection | engine comparison | **L12** |
| L9 Local AI assist | hard-page assist | **L14** (+ **L13** understanding) |
| L10 Production-grade | production | **L19** (+ **L15–L18** readiness/observability/gate) |
