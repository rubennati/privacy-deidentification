# ADR-0022: OCR L12 is multi-column layout reconstruction

## Status

Accepted — 2026-07-08. Builds on [ADR-0016](0016-engine-maturity-levels-0-19.md),
[ADR-0018](0018-ocr-pii-implementation-plan.md), and
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md).

## Context

The next OCR/Text quality gap is not a second OCR engine; it is deterministic layout understanding
for documents whose existing text fragments are geometrically correct but read in the wrong order.
AGB/terms pages, service tables, expert reports, photo documentation, and dense PDFs can interleave
columns, fuse table headers into one text run, or place form values near labels without sharing the
same row.

Earlier planning placeholders described OCR/Text L12 as multi-engine benchmark/selection. That
would require a dependency and adapter-selection discussion, while the immediate problem can be
addressed with bounded heuristics over geometry the system already extracts.

## Decision

- Re-scope OCR/Text L12 to **multi-column layout reconstruction**.
- Keep the implementation inside the existing `reading_text` layer: `reading_text_version` remains
  `"1"` and no new artifact/schema is introduced.
- Optimize for stable, measurable quality improvements rather than theoretical layout perfection.
  L12 accepts only confidence-aware improvements from multiple conservative signals; when evidence
  is weak, it preserves the existing order and records uncertainty instead of guessing.
- Use deterministic geometry-based heuristics only:
  - x-position clustering plus overlapping vertical ranges for confident multi-column prose;
  - explicit skips for table-owned, party-heading-owned, low-confidence, and data-dense regions;
  - fused table-header rendering only when following rows provide safe column positions;
  - label/value pairing only when adjacent geometry is unambiguous.
- Do not add private-corpus-specific rules. If a corpus gap lacks enough generic evidence, classify
  the gap, document the missing signal, and add a must-not-trigger test only when the risk is already
  known.
- Preserve all boundaries from ADR-0019: technical raw `text_result.text` and `pages[].text` remain
  byte-stable, PII still runs only on technical raw text, and no pseudonymization, redaction,
  reconstruction/export, or review-decision behavior is added.
- Defer multi-engine benchmark/selection to a later OCR-quality/benchmark spike, not the active L12
  maturity level.

## Consequences

- Canonical Reading Text improves for complex multi-column and dense-layout documents without a new
  dependency or public API.
- `structured_content` remains the L11 span-backed structure layer; L12 can make the display text
  more readable but does not redefine structured-content spans or switch PII input.
- New non-sensitive `reading_text_flags` may include `multi_column_reconstruction`,
  `dense_table_reconstruction`, and `label_value_pairing`.
- Low-confidence layouts deliberately keep existing row order instead of inventing structure.
- Future OCR/Text quality signals should be additive evidence sources, not hard dependencies for
  PII/review/pseudonymization. Candidate signals include dictionary or domain-vocabulary checks,
  PDF-text-layer versus OCR comparison, optional second-OCR-engine agreement, OCR confidence, layout
  confidence, document-type hints, review feedback, and benchmark regression gates. They can be
  introduced later as additional confidence gates without rewriting the L12 reading-text pipeline.
- The migration note avoids mixing the older L12 multi-engine placeholder with the active 0–19 OCR
  level definition.
