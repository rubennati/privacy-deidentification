# ADR-0010: Private local OCR/PII benchmark runner

## Status

Accepted — 2026-07-01

## Context

PR #6 ([ADR-0009](0009-text-layer-quality-routing.md)) added a text-layer quality gate and
page-level OCR fallback, but there was no reproducible, local way to measure whether it (or any
future OCR/PII change) actually improved routing or detection quality against a realistic
document corpus. A private local corpus (`volumes/document-data/`), a private benchmark metadata
file (expected page counts, text-quality buckets, expected pipeline routing), and a private
candidate PII ground truth (entity type/page/offset anchors, no unmasked values) were available,
but:

- None of that data may be committed: it is derived from real customer-style documents, and even
  a "masked" ground-truth value or a routing report built from real text risks leaking PII into
  version control.
- The benchmark needed to be runnable repeatedly without triggering expensive OCR/PII
  reprocessing every time — it should measure the *current* state of already-computed artifacts.

## Decision

- Add `scripts/benchmark/`, a standard-library-only (no third-party dependencies) Python tool
  that **reads** existing `document.json` and `audit_result`/`text_result`/`pii_result`
  artifacts under `volumes/document-data/`, matches them by filename to private benchmark
  metadata and candidate ground-truth JSON files, and writes a markdown + JSON report.
- Private inputs and all generated reports live under `volumes/benchmark/`, already covered by
  the existing `/volumes/*` `.gitignore` rule (see [ADR-0008](0008-separate-upload-and-document-data-storage.md)).
  Nothing benchmark-related is committed.
- The runner never triggers audit/OCR/PII processing, calls the API, or writes/deletes a
  document. Missing artifacts are reported as `missing`, not generated — a `--refresh-missing`
  flag is deliberately deferred to a future PR.
- A dedicated `privacy_guard.py` runs immediately before any report is written: it recursively
  rejects the report if a forbidden field name (`value`, `text`, `entity_text`, `raw_text`,
  `full_text`, `masked_value`, `page_text`, `ocr_text`, `source_text`, `snippet`, `excerpt`)
  appears anywhere, or if any string looks like an email/IBAN/phone/credit-card/IPv4 value. This
  is redundant by design: every loader (`artifact_loader.py`, `document_matching.py`) already
  keeps only counts, types, statuses, and offsets — raw extracted text and ground-truth
  `masked_value`/`source` fields are dropped at load time and never assigned to a field. The
  guard exists to fail loudly if that invariant is ever accidentally broken.
- Filename matching (local `document.json` filenames vs. benchmark/ground-truth filenames, which
  often differ only by a `(1)`/`(2)` copy suffix) is a strict, ordered pipeline — exact, then
  normalized, then suffix-stripped, then size as a plausibility tiebreaker — that reports
  `ambiguous` rather than guessing when more than one candidate remains.
- PII matching is pragmatic and transparent rather than aggressive: entity types are mapped to a
  canonical name (documented in `pii_matching.py`), grouped into `structured_types`/`ner_types`/
  `domain_sensitive_types`/`other_types`, and a type is reported `unsupported_by_current_pipeline`
  per document based on that document's own recorded `configured_entity_types` — not a hardcoded
  list. Matching uses page-local offset overlap (`page_aware`) when the text has page structure,
  falling back to type-count-only matching (`document_level`) otherwise (e.g. DOCX).
- The candidate ground truth is explicitly not a validated gold standard — the report and its
  documentation say so, so precision/recall/F1 are read as a regression signal, not an absolute
  accuracy claim.
- `make benchmark-private` / `make benchmark-private-json` run the tool in a plain
  `python:3.12-slim` container (no dependencies to install); `make benchmark-test` runs its
  synthetic-data-only pytest suite the same way. Neither touches the backend's `uv`-managed venv
  or adds a dependency to `backend/pyproject.toml`.

## Consequences

- Local OCR/text-routing and PII detection quality against the private corpus are now
  measurable and reproducible without committing any of the underlying data, in line with
  existing PII-handling principles (no anonymization/redaction, detection-only, cleartext stays
  inside the protected artifact directory).
- Because the runner never triggers processing, a document without a computed artifact simply
  shows up as `missing` in the report; a human (or a later PR) decides whether to run it.
- The tool intentionally does not add a new PII recognizer, candidate validation, stopword/POS
  filter, dictionary integration, OCRmyPDF/Tesseract/Docling/PP-Structure integration, OCR
  preprocessing change, UI/API change, database, queue, or redaction/anonymization — those remain
  out of scope for this PR.
- Remaining limitation: filename matching is greedy (first-come, first-served) rather than a
  global optimal assignment, so a pathological corpus with many near-identical filenames could
  produce an avoidable `ambiguous` report; this is an accepted tradeoff for simplicity and has not
  occurred on the actual local corpus.
