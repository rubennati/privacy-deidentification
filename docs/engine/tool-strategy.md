# Tool Strategy

Which tools we integrate, in which role, and when. This follows the project's **tool-first /
adapter-only** principle ([`AGENTS.md`](../../AGENTS.md)): we integrate proven open-source tools
behind ports/adapters and write orchestration, not bespoke OCR/NER/redaction intelligence. Every
tool must run **locally** — nothing sends document bytes, text, or PII to an external service.

## Classification

- **Core** — in the pipeline now, load-bearing.
- **Benchmark spike** — evaluate in the benchmark/an isolated spike before any pipeline commitment.
- **Later option** — plausible future role, not yet scheduled.
- **Explicitly not now** — deliberately excluded for this phase.

## Tool-by-tool

| Tool | Today's role | Possible later role | Problem it solves | Risks | Deps / image size | Privacy fit | Relevant from |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **pypdf** | Core — PDF text-layer extraction + page probe | stays | Get embedded PDF text without OCR | weak on broken/encoded layers (handled by the L3 gate) | tiny, pure-Python | local ✓ | OCR L1 |
| **python-docx** | Core — table-aware DOCX extraction | stays | DOCX text incl. tables/headers | complex layouts flattened | small | local ✓ | OCR L1 |
| **pdf2image / Poppler** | Core — render PDF pages to raster for OCR | stays | Feed scanned pages to OCR | native Poppler dependency; temp files (kept on tmpfs) | native lib | local ✓ | OCR L2 |
| **PaddleOCR + PaddlePaddle** | Core — CPU OCR (PP-OCRv5 mobile, Latin recognizer) | stays as an OCR engine option | Read text off images/scans | heavy image (~GB), CPU MKL-DNN quirk, ARM build caveat | large (OCR image only) | local ✓ | OCR L2 |
| **Pillow** | Core — image open/validation | stays | Image handling | — | small | local ✓ | OCR L2 |
| **Presidio (analyzer)** | Core — PII detection + shipped AT/DE/domain PatternRecognizers | stays; host validation rules | Structured + domain + NER PII detection | small-model NER over-tags (see PII L5) | moderate (PII image only) | local ✓ | PII L1–L3 |
| **spaCy (+ de_core_news_sm)** | Core — NER backend for Presidio | stays; POS/stopword info for validation | German NER + linguistic features | small model imprecise; fixed-score NER | moderate | local ✓ | PII L1 (validation input at L5) |
| **`text_quality.py` (in-house)** | Core — per-page quality/routing heuristic | stays | Detect broken/encoded text layers | heuristic thresholds (unit-tested) | none | local ✓ | OCR L3 |
| **PyMuPDF (fitz)** | — | Later — block/line geometry for layout + (much later) redaction | Reading order, layout blocks, redaction primitives | AGPL licensing to review; adds a dep | moderate | local ✓ | OCR L5–L6 |
| **OCRmyPDF / Tesseract** | — | Benchmark spike — alternative OCR engine | Compare OCR quality/runtime vs PaddleOCR | another heavy runtime | large | local ✓ | OCR L8 |
| **Docling** | — | Benchmark spike — document structure/layout/tables | Structured document understanding | new, heavy; maturity to assess | large | local ✓ | OCR L6–L7 |
| **PP-Structure** | — | Benchmark spike — layout + table structure | Table/layout extraction | Paddle ecosystem weight | large | local ✓ | OCR L6–L7 |
| **MinerU** | — | Later option — extraction/layout | Alternative structured extraction | maturity/weight to assess | large | local ✓ | OCR L7–L8 |
| **GLiNER** | — | Later option — flexible entity recognition | Recall on entity types Presidio patterns miss | model weight; validation still needed | moderate/large | local ✓ | PII L5–L9 |
| **Local VLM** (e.g. small local vision-language model) | — | Later option — hard-page assist + candidate plausibility | Bad scans, handwriting, contextual plausibility | large model, latency, must stay assistive & local | very large | local **only** ✓ | OCR L9 / PII L9 |

## What stays core

`pypdf`, `python-docx`, `pdf2image`/Poppler, `PaddleOCR`/`PaddlePaddle`, `Pillow`, `Presidio` +
`spaCy`, and the in-house `text_quality.py` routing heuristic. These deliver OCR L1–L3 and PII L1
today and remain the backbone through the near-term roadmap. PII L2/L3 is implemented as lazy
**Presidio PatternRecognizers** with format-strong or immediate-label context; L5 validation rules
remain separate future post-processing, not part of the recognizer pack.

## What is a benchmark spike (evaluate before adopting)

`PyMuPDF` (layout geometry), `OCRmyPDF`/`Tesseract` (alternative OCR engine), `Docling` and
`PP-Structure` (layout/table structure). Each is trialled *in the benchmark or an isolated spike*
and only enters the pipeline behind its adapter if it demonstrably wins on quality/runtime/memory.

## What is a later option

`MinerU`, `GLiNER`, and a local VLM. Plausible future value, but not scheduled and not evaluated
yet; gated behind spikes and the local-only/assistive rules.

## What is explicitly not now

- **No cloud/external OCR, NER, or LLM services** — ever, by the privacy principle.
- **No local VLM/LLM integration in the near-term roadmap** — deferred to an isolated spike
  (Engine-8); see the
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding).
- **No new heavy dependency** added for a capability a Presidio recognizer or a deterministic rule
  can deliver (e.g. AT/DE and domain packs need recognizers, not a new model).
- **No bespoke OCR/NER/redaction algorithm** — always integrate a proven tool behind an adapter.
- **No redaction tooling wired in yet** — PyMuPDF's redaction primitives are noted for the future
  de-identification foundation, not this phase.
