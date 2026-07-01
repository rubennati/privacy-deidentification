# OCR / Text Engine — Levels 0–10

The OCR/Text engine turns an uploaded document into the **best possible machine-readable text**,
preserving structure as far as reasonably possible, so the PII engine and human reviewers work on
trustworthy input. It is the first sub-engine in the [north star](README.md#north-star).

Two output notions run through the levels and are defined in [`engine-artifacts.md`](engine-artifacts.md):

- **`best_text_result`** — the *canonical* text used by PII and review. Correctness first;
  reading order and layout are secondary.
- **`layout_text_result`** — a *human-readable* rendering that preserves paragraphs, tables, and
  reading order. A superset concern that appears from L6 onward.

Level numbers are cumulative: each level assumes the ones below it. They are **not** comparable to
the PII or Review ladders.

---

## Level 0 — Upload only

- **Goal:** accept and safely store a document; extract nothing.
- **Engine must:** validate type/size/magic bytes, store byte-identical original, record an
  original artifact + SHA-256.
- **Artifacts:** `document.json`, `original_artifact`.
- **Metrics:** upload success rate, rejected-invalid rate (no text metrics apply).
- **Tests/benchmarks:** upload validation unit/integration tests.
- **Tools:** FastAPI, python-stdlib hashing, MIME sniffing.
- **Not in scope:** any text extraction.
- **Acceptance:** a valid file is stored once, addressable by id, with a verifiable digest;
  invalid files are rejected with a clean error.

## Level 1 — Basic text extraction

- **Goal:** get the *embedded* text out of text-native documents.
- **Engine must:** extract a PDF text layer (pypdf) and DOCX text (python-docx, table-aware),
  produce a single canonical text string per document.
- **Artifacts:** `text_result` (serving as `best_text_result`).
- **Metrics:** character count, word count, extraction success rate.
- **Tests/benchmarks:** DOCX/PDF extraction unit tests; character-count parity between audit and
  OCR/Text on DOCX.
- **Tools:** pypdf, python-docx.
- **Not in scope:** OCR, image documents, scanned PDFs, quality judgement.
- **Acceptance:** a text-native PDF/DOCX yields deterministic text; audit and OCR/Text agree on
  DOCX character counts.

## Level 2 — Basic OCR runtime

- **Goal:** read text off images and scanned pages at all.
- **Engine must:** render PDF pages to raster (pdf2image/Poppler) and run a local OCR engine
  (PaddleOCR) behind an adapter; provision models locally; fail loudly (`503`) when the runtime or
  models are missing instead of downloading at request time.
- **Artifacts:** `text_result` with per-page `source = paddleocr`, `ocr_used = true`.
- **Metrics:** OCR availability, per-page OCR success/failure.
- **Tests/benchmarks:** `make ocr-smoke` (synthetic image → recognised text); adapter unit tests.
- **Tools:** PaddleOCR + PaddlePaddle (CPU), pdf2image/Poppler, Pillow.
- **Not in scope:** deciding *whether* a page needs OCR; layout; confidence scoring.
- **Acceptance:** an image document and a text-layer-free PDF page produce recognised text via the
  provisioned local models; a slim image returns `503` only when a request truly needs OCR.

## Level 3 — Page-level routing  ✅ *current baseline*

- **Goal:** per page, choose text layer vs OCR — never OCR a good page, never trust a broken one.
- **Engine must:** assess each PDF page's character/token plausibility with a dependency-free
  heuristic (`text_quality.py`) into `GOOD / LOW_CONFIDENCE / BROKEN / EMPTY`, record it additively
  on the audit page (`text_quality_status/score/reasons`, `recommended_text_source`, `needs_ocr`),
  and route each page independently (`pdf_mixed` when a document mixes both).
- **Artifacts:** `audit_result` with per-page quality verdict; `text_result` with per-page source.
- **Metrics:** page-status distribution (GOOD/LOW/BROKEN/EMPTY), `needs_ocr` page count, routing
  correctness vs an expected routing category.
- **Tests/benchmarks:** `text_quality` unit tests; benchmark runner's OCR/text routing table.
- **Tools:** pypdf (probe), `text_quality.py`, PaddleOCR (only for routed pages).
- **Not in scope:** OCR confidence, CER/WER, layout/reading order, runtime/memory metrics.
- **Acceptance:** a clean text PDF never renders a page or initialises OCR; a mixed PDF OCRs only
  broken/empty pages; a broken layer with no OCR runtime returns `503`, never garbage.

## Level 4 — Quality report  ⏳ *partially reached*

- **Goal:** report *how good* the extracted text is, page by page and per document, so quality is
  measurable and regressions are visible.
- **Engine must:** capture per-page OCR **confidence** from the engine, expose a per-document
  quality summary (source mix, coverage, low-confidence page count), and make the numbers feed a
  regression report. Character/token plausibility already exists (L3); L4 adds confidence and a
  first-class `quality_report`.
- **Artifacts:** `quality_report` (counts, statuses, coverage, confidence — **no page text**);
  richer `audit_result` page metrics.
- **Metrics:** OCR confidence (mean/min per page/doc), page coverage, source-per-page,
  character/word-count deviation vs expectation, routing correctness.
- **Tests/benchmarks:** extend `make benchmark-private` with confidence + coverage columns;
  regression thresholds.
- **Tools:** PaddleOCR (confidence in the predict payload), benchmark runner.
- **Not in scope:** CER/WER against a transcript (needs ground-truth text we deliberately do not
  store), layout, table reconstruction.
- **Acceptance:** every OCR page carries a confidence value; the quality report shows per-document
  source mix, coverage, and low-confidence counts, with no raw text.
- **Status today:** page-level *plausibility* verdicts and routing metrics exist; OCR **confidence**
  is not yet captured, and there is no distinct `quality_report` artifact. → **partial.**

## Level 5 — Human-readable text output  ⛔ *open*

- **Goal:** produce text a human can actually *read* — stable paragraphs, sensible line breaks,
  de-hyphenation — distinct from the raw canonical string.
- **Engine must:** post-process the canonical text into a readable rendering (paragraph joins,
  hyphenation repair, whitespace normalisation) **without** mutating `best_text_result`; keep both.
- **Artifacts:** `best_text_result` (canonical, unchanged) **plus** a first `layout_text_result`
  (readable), clearly separated so PII always runs on the canonical text.
- **Metrics:** layout readability (line-merge/hyphenation heuristics), reviewer-reported
  readability; canonical text must remain byte-stable.
- **Tests/benchmarks:** readability transforms unit-tested; guarantee canonical text is untouched.
- **Tools:** in-house normalisation (deterministic), optionally PyMuPDF for block geometry.
- **Not in scope:** tables, columns, key-value structure (L6/L7); any AI rewriting.
- **Acceptance:** a readable rendering exists alongside an unchanged canonical text; PII offsets
  still reference the canonical text.

## Level 6 — Layout-aware text  ⛔ *open*

- **Goal:** preserve reading order and block structure (columns, headings, paragraphs) so text
  reflects the page, not a top-to-bottom character dump.
- **Engine must:** obtain block/line geometry (e.g. PyMuPDF for PDFs, OCR block boxes for scans)
  and order text by layout; annotate blocks with type (heading/body/caption).
- **Artifacts:** `layout_text_result` with ordered, typed blocks and coordinates.
- **Metrics:** reading-order correctness, block-type accuracy, layout readability score.
- **Tests/benchmarks:** layout spike on representative multi-column/complex pages.
- **Tools:** PyMuPDF, PaddleOCR box output; PP-Structure as a spike candidate.
- **Not in scope:** semantic tables / key-value extraction (L7), document classification.
- **Acceptance:** multi-column and header/footer pages produce human-sensible reading order;
  canonical text remains the PII input.

## Level 7 — Table / text reconstruction  ⛔ *open*

- **Goal:** reconstruct tables and structured regions (invoices, cost breakdowns) as structure,
  not as a flattened text run.
- **Engine must:** detect tables and emit rows/cells; associate labels/values; keep a structured
  representation separate from canonical text.
- **Artifacts:** `structured_document_result` (tables, sections, key-value pairs).
- **Metrics:** table reconstruction quality (cell precision/recall), key-value extraction accuracy.
- **Tests/benchmarks:** table spike on invoice/offer-style documents.
- **Tools:** Docling / PP-Structure (spike), PyMuPDF; all behind an adapter.
- **Not in scope:** domain schema mapping, AI-based field understanding (later/optional).
- **Acceptance:** representative tables round-trip into rows/cells usable by downstream review and
  (eventually) redaction, without corrupting canonical text.

## Level 8 — Multi-engine benchmark / selection  ⛔ *open*

- **Goal:** compare OCR/extraction engines and pick the best per page/document with evidence.
- **Engine must:** run more than one extraction path (e.g. PaddleOCR vs OCRmyPDF/Tesseract) behind
  the same adapter, score outputs, and select per page; record which engine won and why.
- **Artifacts:** `benchmark_result` (per-engine metrics), engine-selection annotation on pages.
- **Metrics:** per-engine CER/WER (where ground truth exists), confidence, runtime/page, peak
  memory, selection-win rate.
- **Tests/benchmarks:** extended benchmark runner comparing engines on the private corpus.
- **Tools:** PaddleOCR, OCRmyPDF/Tesseract, MinerU (candidates), benchmark runner.
- **Not in scope:** cloud engines (privacy), automatic model training.
- **Acceptance:** the benchmark shows, per engine, quality/runtime/memory, and the pipeline can
  pick the best local engine per page reproducibly.

## Level 9 — Local AI assist  ⛔ *open, optional*

- **Goal:** use a **local** model to help on genuinely hard pages (bad scans, handwriting,
  marginalia) — assistive only.
- **Engine must:** run a local vision/OCR model behind an adapter, mark its output as
  low-confidence/assistive, and **never silently overwrite** the canonical text; results are
  auditable and stay local.
- **Artifacts:** assistive text/annotations flagged `assistive = true`, never replacing
  `best_text_result` without a recorded decision.
- **Metrics:** assist acceptance rate, delta vs baseline on hard pages, false-improvement rate.
- **Tests/benchmarks:** hard-page subset; human adjudication.
- **Tools:** local VLM/OCR (see the
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding)).
- **Not in scope:** any external/cloud inference; auto-committing AI text as canonical.
- **Acceptance:** on a hard-page set, assistive output is offered, clearly labelled, fully local,
  and only promoted to canonical through an explicit (reviewer/rule) decision.

## Level 10 — Production-grade OCR/Text engine  ⛔ *open*

- **Goal:** reliable, observable, reproducible text extraction across the supported corpus.
- **Engine must:** combine L3–L8 (routing, quality, layout, tables, multi-engine selection) with
  monitoring (runtime/memory/error rates), reproducible model/engine versions, and regression gates.
- **Artifacts:** all of the above, versioned; a stable `quality_report` and `benchmark_result`.
- **Metrics:** the full [OCR metric set](quality-metrics.md#ocr--text-metrics) tracked over time
  with thresholds.
- **Tests/benchmarks:** CI-gated regression run; performance budget.
- **Tools:** the selected core engines + observability.
- **Not in scope:** perfect handwriting/complex-table accuracy (bounded by local tooling).
- **Acceptance:** text extraction meets agreed quality/performance thresholds on the benchmark
  corpus, is reproducible from pinned versions, and regressions fail the gate.

---

## Where the project stands (OCR/Text)

| Level | State | Evidence |
| --- | --- | --- |
| 0 Upload only | ✅ done | upload/core, `original_artifact` |
| 1 Basic text extraction | ✅ done | pypdf + table-aware python-docx |
| 2 Basic OCR runtime | ✅ done | PaddleOCR adapter, model provisioning, `ocr-smoke` |
| 3 Page-level routing | ✅ done | `text_quality.py` + per-page `needs_ocr` routing, `pdf_mixed` |
| 4 Quality report | ⏳ partial | quality verdicts + routing metrics exist; **no OCR confidence, no `quality_report` artifact** |
| 5 Human-readable text | ⛔ open | canonical text only; no readable/layout rendering |
| 6 Layout-aware text | ⛔ open | — |
| 7 Table reconstruction | ⛔ open | — |
| 8 Multi-engine selection | ⛔ open | single engine (PaddleOCR) |
| 9 Local AI assist | ⛔ open | — |
| 10 Production-grade | ⛔ open | — |

**What is achieved:** robust per-page routing that never OCRs a good page and never trusts a broken
text layer. On the local benchmark corpus, routing matched the expected category on 10 of 12
documents; the 2 "mismatches" were the gate routing *all* pages of a bad scan to OCR where a partial
fallback was expected — i.e. more conservative, not wrong.

**What is missing for the next level (L4 → L5):**
1. Capture per-page OCR **confidence** from PaddleOCR and surface it in the audit/quality report.
2. Introduce a first-class `quality_report` artifact (counts/coverage/confidence, no text).
3. Add a deterministic **human-readable** rendering (`layout_text_result` seed) that never mutates
   the canonical `best_text_result`.

See [`roadmap.md`](roadmap.md) (Engine-2, Engine-3) for the sequencing.
