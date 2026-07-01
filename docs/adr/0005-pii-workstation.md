# ADR-0005: Detection-only PII Workstation with Presidio adapter

## Status

Accepted — 2026-07-01

## Context

OCR/Text v1 produces immutable ordered text artifacts. The next station must detect and label PII
without changing text, source documents, or the existing file-based architecture. Detection may
need page-local coordinates while later stations also require stable offsets in the complete text.

## Decision

- Expose synchronous document-scoped `POST` and `GET` PII endpoints and store each result as an
  immutable `pii_result` JSON artifact referencing the newest valid `text_result`.
- Analyze PDF/image text page by page when page data exists. Derive global offsets from the exact
  existing `\n\n` page separator. Analyze DOCX text once and omit synthetic page coordinates.
- Keep Microsoft Presidio Analyzer and spaCy behind a `PiiAnalyzer` adapter with lazy import and
  model initialization. Disable decision-process logging and never log source or entity text.
- Support one configured language per process, German by default, with a small configured entity
  allowlist and score threshold. Do not perform automatic language detection.
- Package Presidio, spaCy, and the pinned German model as an optional `pii` dependency extra. The
  PII-capable image installs the model during build and requests perform no downloads.
- Treat unavailable dependencies, models, or configured languages as `503`; invalid/missing input
  artifacts as `409`; analysis failures as `422`.

## Consequences

- PII artifacts retain exact cleartext entity spans and must receive the same access controls and
  deletion behavior as text artifacts.
- Detection remains independently replaceable and normal tests require neither Presidio nor a
  spaCy model.
- The v1 API detects and labels only. Review, anonymization, masking, and document redaction remain
  explicit later stations.
