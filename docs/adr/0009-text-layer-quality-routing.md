# ADR-0009: Text-layer quality gate and page-level OCR fallback

## Status

Accepted — 2026-07-01

## Context

Audit v1 records, per PDF page, whether a text layer exists (`has_text_layer = bool(text.strip())`)
and how many characters it holds. OCR/Text v1 then routes each page on that single boolean: any
non-empty text layer is used as-is; only pages without a text layer are rendered and OCR'd.

That decision is too coarse. Some PDFs ship a **formally present but broken/encoded** text layer:
extraction returns many characters, but they are almost entirely digits, symbols, and control/
replacement characters with near-zero letters — semantically unusable "garbage". Local corpus
documents `S80286-GA.pdf` and `S80917-GA.pdf` exhibit this; `S80826-RE.pdf` mixes one scanned page
with one usable page, and `S80998-…pdf` is a pure scan. Under the boolean rule the garbage layer is
accepted as valid text, which then pollutes downstream PII detection with noise. OCR of the same
page produces markedly more usable text.

The problem is not *"does the page have text?"* but *"is the text usable?"*.

## Decision

- Add a small, pure, dependency-free helper `services/text_quality.py` that assesses one page's
  extracted text and returns a `TextQualityAssessment`: a `status`
  (`GOOD_TEXT_LAYER` / `LOW_CONFIDENCE_TEXT_LAYER` / `BROKEN_TEXT_LAYER` / `EMPTY_TEXT_LAYER`), a
  `0–100` `score`, machine-readable `reasons`, a `recommended_text_source`
  (`text_layer` / `ocr`), and a `needs_ocr` boolean. It uses robust character/token heuristics
  (letter/digit/punctuation/control ratios, plausible-token ratio for well-formed words and
  numbers). No ML and no dictionary.
- A high digit ratio alone must never route to OCR — tables and invoices are number-heavy. A hard
  fail (`BROKEN_TEXT_LAYER`) requires a *combination*: very low letter ratio **and** high
  symbol/digit share **and** few plausible tokens, or a high control/replacement-character ratio.
  Thresholds are conservative and unit-tested.
- Extend `AuditPageResult` **additively** with optional `text_quality_status`,
  `text_quality_score`, `text_quality_reasons`, `recommended_text_source`, and `needs_ocr`. Older
  audit artifacts that lack these fields still validate. Only aggregate metrics/status/reasons are
  stored — **never the extracted page text**. Two additive content flags,
  `pdf_pages_need_ocr` and `pdf_broken_text_layer`, summarize the decision.
- OCR/Text routes each PDF page on the audit's `needs_ocr` decision instead of `has_text_layer`.
  `GOOD`/`LOW_CONFIDENCE` keep the text layer; `BROKEN`/`EMPTY` are rendered and OCR'd. A page whose
  audit predates this gate (no `needs_ocr`) falls back to the original rule (OCR only when there is
  no text layer at all).

## Consequences

- Broken/encoded text layers are OCR'd instead of accepted, so their garbage no longer reaches PII.
- A broken text layer is **never silently used** as the result: when a page needs OCR but the OCR
  runtime/models are unavailable, the request fails cleanly with `503` (unchanged mechanism) rather
  than falling back to garbage.
- Clean text-layer PDFs incur **no OCR runtime**: no page is rendered and PaddleOCR is never
  initialized. Mixed PDFs OCR only the affected pages, preserving page order and the per-page
  `source` (`pdf_text_layer` vs `paddleocr`) in the `text_result`.
- No new dependency, database, queue, auto-trigger, workstation, OCR engine, or UI change. The
  canonical per-page source selection changes, which is why this is recorded as an ADR.
- Remaining tuning points: page-level image coverage is not yet a routing signal, so a very short
  `LOW_CONFIDENCE` page on an image-heavy scan is kept on the text layer rather than compared
  against OCR; and a genuinely blank page is still rendered/OCR'd (yielding empty text) because
  audit cannot distinguish "blank" from "scanned" without rendering. Thresholds may need corpus
  tuning.
