# ADR-0013: PII candidate validation (Engine-5)

## Status

Accepted — 2026-07-01

## Context

Engine-4 ([ADR-0012](0012-insurance-at-de-pii-recognizers.md)) closed the AT/DE structured and
domain-sensitive detection gaps, but left the known NER precision problem untouched: on the
private benchmark, `review-heavy` (NER opt-in) produced 119 TP / 487 FP / 90 FN — precision
≈0.20 — because the small German spaCy model over-tags common words as `PERSON`/`ORGANIZATION`/
`LOCATION` at a fixed ~0.85 score that the score threshold cannot discriminate. `insurance-at-de`
(no NER) stayed at precision ≈0.71 / recall ≈0.37. Turning NER off is not a fix (it loses real
recall); a new recognizer is not the right tool for a false-positive problem. The engine model
already named this gap PII L5 — candidate validation — a **subtractive, auditable post-processing
step over already-detected candidates**, never a new detection mechanism (see
[`pii-engine-levels.md`](../engine/pii-engine-levels.md#candidate-validation-is-a-post-processing-exclusion-step)).

## Decision

- Add two small, dependency-free modules: `pii_validation_rules.py` (lexical/shape signal data —
  stopwords, generic document words, company-form/name/address/date/financial-context signals —
  and the predicates over them) and `pii_candidate_validation.py` (the `KEEP` / `SCORE_DOWN` /
  `DROP` decision engine and the orchestration over one document's candidates). No spaCy/Presidio
  import in either module; no new dependency.
- Every already-detected candidate gets exactly one verdict:
  - **`KEEP`** — unchanged, no reason recorded.
  - **`SCORE_DOWN`** — score capped at `SCORE_DOWN_CAP = 0.3`, one machine-readable reason
    recorded. `0.3` is deliberately below the default `PII_SCORE_THRESHOLD` (`0.5`), so a
    downgraded candidate is excluded from the final layer under default settings — the existing
    threshold stays the single gate, rather than adding a second one. A deployment that lowers the
    threshold below `0.3` will see these candidates again, deliberately.
  - **`DROP`** — removed unconditionally, one reason recorded. Reserved for classes that are
    *always* wrong regardless of context (a stopword, a function word, a numeric-only NER
    candidate, a token of length ≤2, a single generic document word standing alone).
  - Per the source PR's own guidance, ambiguous cases prefer `SCORE_DOWN` over `DROP`.
- Reason codes are a small closed set, chosen to match the concrete false-positive classes seen on
  the benchmark: `STOPWORD_ONLY`, `FUNCTION_WORD_ONLY`, `GENERIC_DOCUMENT_WORD`,
  `TOO_SHORT_SINGLE_TOKEN`, `NUMERIC_ONLY_FOR_NER`, `MISSING_REQUIRED_CONTEXT`,
  `LOW_SHAPE_CONFIDENCE`, `NER_SINGLE_COMMON_WORD`, `DATE_YEAR_ONLY`, `ORG_WITHOUT_ORG_SIGNAL`,
  `LOCATION_WITHOUT_LOCATION_SIGNAL`, `BIC_WITHOUT_FINANCIAL_CONTEXT`.
- Validation intensity follows entity type, not profile: `PERSON`/`ORGANIZATION`/`LOCATION`/
  `DATE_TIME` get full lexical/context rules (they dominate NER noise); `BIC` and the domain
  identifiers with weaker recognizer-level context requirements (`OFFER_NUMBER`, `CASE_NUMBER`,
  `PROJECT_ID`, `USER_ID`, `FILE_REFERENCE`, `REPORT_NUMBER`, `ASSESSMENT_NUMBER`,
  `CUSTOMER_NUMBER`) get a single context-presence check; every other type (structured + the
  remaining, already pattern/context-gated domain identifiers) is a deliberate pass-through
  (`KEEP`, no rule). Because `structured-only` and `insurance-at-de` never configure
  `PERSON`/`ORGANIZATION`/`LOCATION`/`DATE_TIME` in the first place, the strong rules simply never
  fire for those profiles — **no profile branching exists in the validator itself**, and
  `PERSON`/`ORGANIZATION`/`LOCATION` remain opt-in exactly as before.
- Context is a small window (60 characters before/after the candidate) sliced from the exact text
  the analyzer already saw for that page/document — never logged, stored, or returned. A decision
  is a pure function of `(entity_type, candidate_text, context_before, context_after, score)`.
- `pii_result` is extended **additively**, not replaced with a new artifact type: `PiiEntity` gains
  `original_score` (pre-validation score), `validation_status` (`kept`/`score_down`; absent for a
  dropped candidate, since it never appears), and `validation_reasons` (empty unless
  `score_down`); `PiiContent` gains a `validation` summary (`enabled`, `kept`, `dropped`,
  `score_down`, `dropped_by_reason`, `score_down_by_reason` — counts and reason codes only, never a
  value). All new fields default to `None`/empty so artifacts written before this PR still
  validate. This is a deliberate deviation from the `pii_validation_result` artifact sketched in
  [`engine-artifacts.md`](../engine/engine-artifacts.md): a subtractive filter with no independent
  existence without its `pii_result` input does not need a second artifact, lineage edge, or API
  surface — see [`target-architecture.md`](../engine/target-architecture.md#station-pipeline-target).
- A new `PII_CANDIDATE_VALIDATION_ENABLED` setting (default `true`) is an explicit escape hatch —
  set it `false` to fall back to raw detection output without touching `PII_PROFILE`/
  `PII_ENTITY_TYPES`.
- The private benchmark runner aggregates each document's `validation` summary (sum of counts,
  merged reason-code dictionaries) into the report, guarded by the existing `privacy_guard.py` —
  no new forbidden-key or PII-pattern class is introduced, since the aggregate is exactly the same
  shape (counts + reason-code strings) the guard already allows.

## Consequences

- `broad-review`/`review-heavy` should see materially fewer false positives on `PERSON`/
  `ORGANIZATION`/`LOCATION`/`DATE_TIME` with a documented, bounded recall cost (a `SCORE_DOWN`
  candidate is excluded by the existing threshold, not silently invented back); `structured-only`
  and `insurance-at-de` are structurally unaffected beyond the always-KEEP pass-through and one
  narrow `BIC`/domain-identifier context check.
- Every suppression or downgrade carries a reason and the original score survives on the artifact,
  so a human (or a later Review action) can always see what candidate validation did and override
  it — nothing is invented, and no true positive is silently deleted without a recorded reason.
- Deliberately **not** solved here: stopword/generic-word/company-form/name-context/place-signal
  lists stay small and general rather than an exhaustive gazetteer (a large hard-coded name/city
  list was explicitly out of scope); birth-date vs. other business-date-role classification is not
  further split; per-profile validation *aggressiveness* configuration does not exist (aggression
  is entirely a function of which entity types a profile enables); entity resolution/overlap logic
  (PII L6), human review actions (L7), feedback rules (L8), and any AI-based plausibility (L9)
  remain separate, later engine levels.
- Review/feedback persistence (Engine-6) and a database (Engine-7) are unaffected and still not
  needed for this PR: validation state lives entirely inside the existing immutable `pii_result`
  artifact.
