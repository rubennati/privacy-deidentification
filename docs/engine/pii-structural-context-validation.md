# PII Structural-Context Validation (views → false-positive reduction)

> **Design plan, not yet implemented.** Realizes the OCR Output Contract's unfulfilled promise: the
> structural text views (`structured_content`, `layout`) are currently carried through the contract
> but **inert** — they reduce no false positives. This plan uses them as post-detection *context* to
> fix boundary/structural FPs, **without changing the detection input or the contract**.
>
> Grounded in the pre-validation of the OCR→PII handoff: detection is single-source (raw), the
> Document Text Package contract is stable and sound, and the boundary problems ("whole lines
> marked", "extra words left/right") are detection-side, fixable with structural context.

## Problem (measured)

Detection runs on raw text (correct, single-source). The over-capture FPs come from raw detection:
ADDRESS/CONTACT_LINE recognizers grab whole lines (ADDRESS ≈10 FP on the corpus), GLiNER includes
titles, table headings/labels get captured as entities ("Leistungen und Positionen" → ADDRESS). The
contract's `structured_content` (tables/cells, label/value fields, headings/sections) and `layout`
views **know** these structural roles but are never applied — `pii_input.py` exposes them only as
availability flags, and candidate validation ignores them.

## Principle

- **Detection input stays raw; the Document Text Package contract is unchanged.** This is a
  *post-detection, subtractive* stage — the sanctioned place for FP suppression (candidate
  validation L6/L7 family; this is "structural context hardening").
- **Deterministic and structural, never corpus-fitted.** Rules encode structural truths ("an entity
  does not span two table cells", "a section heading is not an address"), not benchmark numbers.
- **Subtractive/clip only** — trim or reject candidates; never expand, move, or invent a detection.
- **Additive, reversible, measured.** Config-flagged (`PII_STRUCTURAL_VALIDATION_ENABLED`, default
  off); reason-coded provenance (text-free); benchmark must show FP↓ with **no true-positive loss**.

## Where it fits in the pipeline

```
detect (raw)  →  candidate validation (L6/L7)  →  [NEW] structural-context validation  →  overlap resolution  →  entity contract
```

It consumes `structured_content`/`layout` spans threaded through `PiiInputDocumentV1` (today only a
flag; extend it to expose the actual structural spans). Alignment key: structured cells/fields carry
**page-local** spans and detected entities carry **page-local** offsets — they align on the same
page coordinate system (verify at implementation).

## Rules (v1 — each deterministic, structural, individually toggle/reason-coded)

1. **Cell / field-value boundary clipping.** If a candidate span extends beyond the table cell or
   label-value it starts in, clip it to that boundary. Fixes "extra words left/right" that bleed
   into the neighbouring cell or the label. Reason: `structural_cell_clip`.
2. **Heading / section-title rejection.** A candidate that coincides with (or is contained in) a
   `structured_content` heading/section title, for a content type (ADDRESS/PERSON/ORGANIZATION/…),
   is dropped or scored down — a heading is not an entity. Fixes "Leistungen und Positionen" →
   ADDRESS. Reason: `structural_heading_rejected`.
3. **Whole-line label+value trim.** When a labelled-line recognizer captured a whole line but
   `structured_content` identifies a label prefix + value, trim the span to the value. Reason:
   `structural_label_value_trimmed`.
4. **(optional) Token-edge trim.** Trim trailing/leading tokens that structural/tokenization info
   shows are not part of the entity (e.g. trailing punctuation, an adjacent label word). Kept
   conservative; the honorific-title question (GLiNER "Mag. …") is decided separately against a
   trustworthy ground truth, not here.

## What it explicitly does NOT touch

- The detection input (still raw) and the **Document Text Package contract** (stable — do not churn).
- The **anchor / canonical-display layer** — that is a *separate* question (whether PII needs
  highlights in the reading view at all). This plan is detection-quality only.
- No corpus-fitted rule; no new detection; no new heavy dependency.

## Plumbing (implementation outline)

1. Extend `pii_input.py` to expose concrete `structured_content` spans (cells, field values,
   headings) with their page-local offsets — realizing the `structured_hint` role as data, not a
   flag. Contract and package schema unchanged (additive read).
2. New `pii_structural_validation.py`: pure function `(entities, structural_spans) → (kept, trimmed,
   dropped, provenance)`; deterministic, order-independent.
3. Wire it into `pii_service` after candidate validation, before `pii_overlap`. Record outcomes in
   the existing additive `PiiEntity.provenance` / a content summary (reason codes/counts only).
4. Config flag + `.env.example` + ADR (0043) when implemented.

## Acceptance / measurement

- **Precision up, recall unchanged** on the benchmark (each rule must not drop a true positive).
  Because the benchmark ground truth is currently an incomplete *candidate* signal (see the quality
  plan), rely primarily on the **no-TP-loss** invariant and on synthetic structural tests, not on
  absolute precision deltas, until the gold-standard GT exists.
- Synthetic tests per rule (table cell overflow, heading-as-address, label+value line) that are
  independent of the private corpus.
- A local private-corpus pass reporting, per document, FP removed vs. any TP touched (no raw text).

## Sequence note

This is the highest-leverage detection-quality architecture step and is complementary to — not
blocked by — the gold-standard GT and the PII-worker container split. Recommended order: land the
mechanism with the no-TP-loss invariant + synthetic tests; complete the gold-standard GT to quantify
the precision gain; then tune thresholds. The anchor-display question is tracked separately.
