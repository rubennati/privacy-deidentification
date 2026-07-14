# ADR-0044: Context-gated BIRTH_DATE and BIRTH_PLACE recognizers

- Status: Accepted
- Date: 2026-07-15
- Related: [ADR-0012](0012-insurance-at-de-pii-recognizers.md) (recognizer pack),
  [ADR-0013](0013-pii-candidate-validation.md) (candidate validation),
  [ADR-0015](0015-structured-address-contact-line-recognizers.md) (line/label recognizers),
  [ADR-0028](0028-pii-intake-document-text-package-v1.md) (overlap resolution),
  [pii-detection-quality-plan.md](../engine/pii-detection-quality-plan.md)

## Context

The PII detection & display foundation gate ([quality-gates.md](../../.ai/quality-gates.md)) lists
`BIRTH_DATE` (P1/quasi-identifier, target R ≥ 0.90) and `BIRTH_PLACE` (context-gated) as expected
types. The private benchmark showed both at **0 recall** (`BIRTH_DATE` 0/4, `BIRTH_PLACE` 0/2): no
recognizer existed and neither type was in any named profile. `DATE_TIME` already detects dates
generically, but it does not carry the *birth* role, and a bare city over-tags heavily (which is why
`LOCATION` is deliberately kept out of the profiles — see
[pii-detection-quality-plan.md](../engine/pii-detection-quality-plan.md)).

## Decision

Add two deterministic, **context-gated** pattern recognizers to the insurance-at-de pack, and put
`BIRTH_DATE`/`BIRTH_PLACE` into every named profile except `structured-only`:

- **`BirthDateRecognizer` → `BIRTH_DATE`.** A German numeric date (`dd.mm.yyyy`, optional spaces)
  emitted **only** when it follows an explicit birth label (`geboren am`, `Geburtsdatum`, `geb.`, …),
  same line or next line, reusing the existing `_contextual_patterns` / `_labeled_value_patterns`
  builders. The strict date value shape means `geb.` introducing a maiden name
  (`Müller geb. Schmidt`) never matches. A birth date is the same span the generic NER emits as
  `DATE_TIME`, so a new cross-type precedence rule (`BIRTH_DATE` ⊳ `DATE_TIME` in `pii_overlap.py`)
  makes the specific birth role win and prevents double-counting.
- **`BirthPlaceRecognizer` → `BIRTH_PLACE`.** A capitalized place name (up to three words, capital
  enforced with an inline `(?-i:…)` group) emitted **only** after a birth-place label (`geboren in`,
  `Geburtsort`, `geb. in`, …). A residence city under a non-birth label, or a lowercased word, does
  not match — so this stays the single genuinely sensitive location without reintroducing the
  `LOCATION` over-tagging.

Both are label-gated for precision, carry `context` words, pass through candidate validation as
light/pattern-gated types, and are covered by synthetic positive **and** must-not-over-match tests.

## Consequences

- **Positive:** closes two previously-unsupported ground-truth types generically (no corpus-specific
  tuning), advancing the detection-quality gate. Deterministic and auditable; no new dependency or
  model. `BIRTH_DATE` no longer double-counts against `DATE_TIME`.
- **Negative / cost:** birth detection is only as good as the label vocabulary; unlabelled birth
  dates/places (e.g. the `*` birth-symbol convention, or a date in free prose) are intentionally not
  captured, favouring precision. The value shapes are AT/DE-centric.
- **Deferred:** `GIVEN_NAME`/`FAMILY_NAME` (the other two unsupported ground-truth types) via GLiNER
  zero-shot labels; the `*`/`✱` birth-symbol convention; non-numeric month names in birth dates.
