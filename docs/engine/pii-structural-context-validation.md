# PII Structural-Context Validation (views → false-positive reduction)

> **Mechanism implemented, default-off ([ADR-0043](../adr/0043-pii-structural-context-validation.md));
> pending a private-corpus no-TP-loss pass before it is enabled.** Realizes the OCR Output Contract's
> unfulfilled promise: the
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

It consumes `structured_content` spans threaded through `PiiInputDocumentV1`. **Step 1 (below) is
implemented**: the adapter now exposes them as offset-only `PiiInputStructuralSpan`s, not a flag.

**Alignment key — verified.** Both coordinate systems line up, checked against the OCR structure
builder, the schema validator, and PII's own per-page detection loop (all use the identical
`len(page.text) + 2` page accumulation over the *raw* per-page text):

- Page-local: `PiiInputStructuralSpan.page_start/page_end` ↔ `PiiEntity.page_start_offset/
  page_end_offset` — both into the raw per-page text.
- Global: `PiiInputStructuralSpan.raw_start/raw_end` ↔ `PiiEntity.start_offset/end_offset` — both
  into the combined raw text. Despite the `StructuredSpan` schema's `canonical_*` naming, those
  offsets reference the **raw** text (the validator enforces it), not `reading_text`.

The global `raw_*` pair is the robust alignment key for Step 2: a paged document also matches on
`page_number`, but a non-paged document (DOCX) carries structural `page_number = 1` while its
detections carry `page_number = None`, so only the raw offsets align there.

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

1. **Done.** `pii_input.py` exposes concrete `structured_content` spans (table cells, field labels,
   field values, section headings) as offset-only `PiiInputStructuralSpan`s on
   `PiiInputDocumentV1.structural_spans`, with page-local **and** global raw offsets, a structural
   `kind`, a bounded `role` code, and the owning `container_id` — realizing the `structured_hint`
   role as data, not a flag. No source text is copied (offsets/codes only). Contract and package
   schema unchanged (additive read). Covered by `backend/tests/test_pii_input.py` (kinds, offset
   alignment invariant, no-text-leak). Nothing consumes it yet — it is inert until Step 3 wires it.
2. **Done.** `pii_structural_validation.py`: pure function `(entities, structural_spans) → (kept,
   trimmed, dropped, provenance)`; deterministic, order-independent, fixed rule precedence
   (heading → label/value trim → cell clip). Reason codes `structural_cell_clip`,
   `structural_label_value_trimmed`, `structural_heading_rejected`; hard structured identifiers are
   never heading-rejected (P3 leak guard). Covered by `backend/tests/test_pii_structural_validation.py`.
3. **Done.** Wired into `pii_service._analyze_text` after candidate validation, before `pii_overlap`.
   Structural reasons are attached to the surviving entities *after* overlap (which rebuilds
   provenance) via preserved ids; outcomes recorded on additive optional `PiiEntity.provenance.
   structural_reasons` and `PiiContent.structural_validation` (`PiiStructuralValidationSummary`),
   reason codes/counts only. With the flag off the stage is a byte-identical no-op. Covered by
   wiring tests in `backend/tests/test_pii.py`.
4. **Done.** Config flag `PII_STRUCTURAL_VALIDATION_ENABLED` (default off) + `.env.example` +
   [ADR-0043](../adr/0043-pii-structural-context-validation.md); additive frontend TS types.

## Acceptance / measurement

- **Precision up, recall unchanged** on the benchmark (each rule must not drop a true positive).
  Because the benchmark ground truth is currently an incomplete *candidate* signal (see the quality
  plan), rely primarily on the **no-TP-loss** invariant and on synthetic structural tests, not on
  absolute precision deltas, until the gold-standard GT exists.
- Synthetic tests per rule (table cell overflow, heading-as-address, label+value line) that are
  independent of the private corpus.
- A local private-corpus pass reporting, per document, FP removed vs. any TP touched (no raw text).

### Corpus A/B result (2026-07-13, 4 GT-matched TEST docs, GLiNER, review-heavy)

Same image, only the flag toggled. **First ON run failed no-TP-loss** (TP 132→129, R 0.88→0.86):
rule 2 dropped **3 real ORGANIZATION true positives** in section headings vs. 1 PERSON FP removed —
company/person names legitimately *are* headings. **Fix:** the heading-rejectable set is narrowed to
line/place types only (`ADDRESS`/`CONTACT_LINE`/`CUSTOMER_LINE`/`LOCATION`/`BIRTH_PLACE`); names and
organizations are never heading-rejected. After the fix the ON run equals the OFF run exactly
(**TP=132, FP=31, R=0.88, F1=0.844**) — no TP loss, but **no measurable FP↓**: the heading rule fires
0× (no ADDRESS-as-heading in these docs) and the 3 remaining cell-clips are score-neutral. The corpus
is too thin in the targeted FP patterns to show the precision gain. **Default stays OFF** until the
gold-standard GT (or a document exhibiting the real ADDRESS-heading/cross-cell patterns) demonstrates
FP↓ with no TP loss.

## Sequence note

This is the highest-leverage detection-quality architecture step and is complementary to — not
blocked by — the gold-standard GT and the PII-worker container split. Recommended order: land the
mechanism with the no-TP-loss invariant + synthetic tests; complete the gold-standard GT to quantify
the precision gain; then tune thresholds. The anchor-display question is tracked separately.
