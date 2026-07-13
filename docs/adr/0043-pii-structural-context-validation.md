# ADR-0043: PII structural-context validation (views → false-positive reduction)

- Status: Accepted
- Date: 2026-07-13
- Related: [ADR-0013](0013-pii-candidate-validation.md) (candidate validation),
  [ADR-0027](0027-ocr-output-contract-v1-strategy.md) (OCR Output Contract / structured_content),
  [ADR-0028](0028-pii-intake-document-text-package-v1.md) (PII intake + overlap resolution),
  [pii-structural-context-validation.md](../engine/pii-structural-context-validation.md) (design plan),
  [quality-gates.md](../../.ai/quality-gates.md) (PII detection & display foundation gate)

## Context

PII detects on **technical raw text** (single-source, correct). Its measured over-capture false
positives are boundary/structural: ADDRESS/CONTACT_LINE recognizers grab whole lines, NER swallows a
field label into a value, and a section heading ("Leistungen und Positionen") is captured as an
ADDRESS. The OCR Output Contract v1 already carries `structured_content` — per-page table cells,
label/value fields, and heading-bound sections referenced by offsets — but PII exposed it only as an
availability flag (`structured_hint`); the spans that *know* these structural roles were never
applied. This is the highest-leverage detection-quality step under the foundation gate and is
complementary to the gold-standard ground truth (which quantifies the gain later).

## Decision

Add a **post-detection, strictly subtractive** structural-context validation stage — the sanctioned
place for FP suppression (the candidate-validation family) — that consumes `structured_content`
spans as *context* to fix boundary/structural FPs, **without changing the detection input or the
contract**. It is config-flagged (`PII_STRUCTURAL_VALIDATION_ENABLED`, default **off**) and lands
with a no-true-positive-loss invariant.

- **Plumbing (`pii_input.py`).** The intake adapter now exposes `structured_content` as offset-only
  `PiiInputStructuralSpan`s (table cells, field labels, field values, section headings), each with
  page-local **and** global raw offsets, a structural `kind`, a bounded `role` code, and the owning
  `container_id`. No source text is copied. Verified against the OCR structure builder, the schema
  validator, and PII's own per-page detection loop: structural spans and entity offsets share the
  raw-text coordinate system on both axes (identical `len(page.text) + 2` page accumulation). The
  `StructuredSpan` schema's `canonical_*` fields reference the **raw** text, not `reading_text`; the
  global `raw_*` pair is the robust alignment key (a non-paged DOCX carries structural
  `page_number = 1` while detections carry `page_number = None`).

- **Mechanism (`pii_structural_validation.py`).** A pure, deterministic, order-independent function
  `(entities, spans) → (kept, trimmed, dropped, provenance)` with a fixed per-entity rule precedence
  (heading rejection → label/value trim → cell/field-value clip), each reason-coded:
  - `structural_cell_clip` — an entity that starts inside a table cell / field value but overflows
    its end is clipped to that boundary (an entity does not span two cells).
  - `structural_label_value_trimmed` — an entity that swallowed a field label is trimmed to the
    paired value.
  - `structural_heading_rejected` — a **name/organization/address-family** entity fully contained in
    a section heading is dropped. Hard structured identifiers (IBAN, national IDs, cards, plates) are
    **never** dropped here — a miss is a leak (gate: P3 recall ≥ 0.98).
  A clip/trim only ever **narrows** a span (never widens, moves, empties, or relabels) and shifts
  page offsets consistently; matching is on the global raw offsets.

- **Wiring (`pii_service.py`).** The stage runs after candidate validation and **before** overlap
  resolution. Because overlap resolution rebuilds provenance from scratch, structural reason codes
  are attached to the surviving entities afterwards (matched by the ids the stage preserved). A
  metrics-only `PiiStructuralValidationSummary` is recorded on `pii_result` (additive/optional), and
  per-entity `PiiEntityProvenance.structural_reasons` records clip/trim outcomes — reason codes and
  counts only, never text. With the flag off the stage is a no-op and `structural_validation` is
  `None`, so baseline detection is byte-identical.

## Consequences

- **Positive:** boundary/structural FPs (whole-line ADDRESS/CONTACT_LINE, label-into-value, heading
  captured as an entity) are clipped or rejected deterministically from existing, contract-carried
  structural evidence — no new detection input, recognizer, model, or dependency. Additive,
  reversible, reason-coded, and measurable; the raw offset authority and the active-input separation
  gate are untouched.
- **Guardrails:** rules are structural, not corpus-fitted, and covered by synthetic tests per rule
  plus wiring tests (disabled no-op, enabled trim, enabled heading drop). The no-TP-loss invariant is
  the primary acceptance signal until the gold-standard GT exists, since the current benchmark ground
  truth is an incomplete candidate signal.
- **Deferred:** default remains **off** until a private-corpus pass confirms FP↓ with no TP loss;
  the optional token-edge trim rule; a cross-type precedence table (still `ambiguous_overlap_review`);
  the honorific-title question (decided separately against trustworthy GT); the anchor/canonical
  display question (tracked separately — this ADR is detection-quality only).
