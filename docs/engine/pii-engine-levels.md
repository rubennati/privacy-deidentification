# PII / Sensitive-Data Engine — Levels 0–10

The PII engine turns the canonical text (`best_text_result`) into **labelled sensitive spans** so a
human can review them and, later, so redaction can build on them. It is the second sub-engine in the
[north star](README.md#north-star).

Principles specific to this engine:

- **Detection-only.** It labels spans; it never anonymises, masks, or alters the document.
- **Precision-first defaults.** Noisy recognizers are opt-in, not on by default.
- **Candidate validation is *subtractive*.** From L5 it prunes/scores-down obvious false positives;
  it is a post-processing filter, **not** a new detection mechanism (see the
  [dedicated section](#candidate-validation-is-a-post-processing-exclusion-step)).
- **Tool-first / adapter-only.** Recognition is Presidio + spaCy (and later GLiNER etc.) behind an
  adapter; we add *recognizers and rules*, not a bespoke NER model.

Level numbers are cumulative and **not** comparable to the OCR or Review ladders.

## Profiles (the configuration axis)

Profiles bundle *which entity types are active*. They are now first-class configuration and are
recorded in `pii_result`; per-profile validation posture remains future L5 work.

| Profile | Intent | Entity coverage | Validation posture |
| --- | --- | --- | --- |
| `structured-only` | High precision, low noise (conservative code fallback if `PII_PROFILE` is unset; `.env.example` recommends `insurance-at-de` instead) | EMAIL/PHONE/IBAN/CREDIT_CARD/IP/URL | validation runs, near-zero drops (light types pass through) |
| `insurance-at-de` | AT/DE + insurance/legal domain identifiers | structured + AT/DE + policy/claim/contract/… | validation runs; only `BIC` + a few domain IDs get a context check |
| `broad-review` | Maximise recall for a human reviewer | above + PERSON/ORGANIZATION/LOCATION | full lexical/context validation on PERSON/ORGANIZATION/LOCATION |
| `review-heavy` | Nothing missed; reviewer resolves everything | above + DATE_TIME | above, plus DATE_TIME year-only/shape checks |

Validation intensity is a function of *entity type*, not profile — see
[Level 5](#level-5--candidate-validation--false-positive-suppression--done) and
[ADR-0013](../adr/0013-pii-candidate-validation.md). Because `structured-only`/`insurance-at-de`
never configure PERSON/ORGANIZATION/LOCATION/DATE_TIME, the strong rules simply never fire for
those profiles — there is no profile branching in the validator itself.

---

## Level 0 — No PII detection

- **Goal:** none; text exists, nothing is labelled.
- **Entity types:** —. **Profiles:** —.
- **Artifacts:** none (only `text_result`).
- **Metrics:** —. **Tests:** —. **Tools:** —.
- **Acceptance:** the pipeline can carry text without any PII stage.

## Level 1 — Structured basics  ✅ *current baseline*

- **Goal:** detect high-precision, pattern-based structured identifiers.
- **Entity types:** `EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, CREDIT_CARD, IP_ADDRESS, URL`
  (default allowlist). `PERSON/ORGANIZATION/LOCATION/DATE_TIME` are **supported but opt-in**.
- **Profiles:** `structured-only` (the conservative code fallback when `PII_PROFILE` is unset).
  `.env.example` uses `review-heavy` as the local interactive review default; `insurance-at-de`
  remains the recommended precision-oriented profile.
- **Artifacts:** `pii_result` with page-local + global offsets, per-type counts, tool versions.
- **Metrics:** per-type precision/recall/F1, TP/FP/FN vs candidate ground truth.
- **Tests/benchmarks:** `pii_adapters` unit tests, `pii-smoke`, benchmark PII table.
- **Tools:** Presidio Analyzer + spaCy (German model) behind a lazy adapter.
- **Acceptance:** structured identifiers are detected with stable offsets and stored immutably; NER
  stays off unless explicitly enabled.
- **Status today:** reached. But benchmark shows the *quality* of these basics is uneven on AT/DE
  data (see [current state](#where-the-project-stands-pii)) — EMAIL/IP are strong, while `PHONE_NUMBER`
  and `URL` had zero recall on the local corpus. Hardening them is L2 work, not new levels.

## Level 2 — AT/DE pattern pack  ✅ *core pack delivered*

- **Goal:** reliably detect Austrian/German-formatted structured identifiers the generic
  recognizers miss.
- **Entity types:** AT/DE phone formats, `SVNR_AT` (social-security), `UID_AT` (VAT/UID),
  `FN_AT` (Firmenbuchnummer), `BIC`, `TAX_ID_AT`, AT/DE `IBAN`/URL/credit-card variants.
- **Profiles:** feeds `insurance-at-de` and `broad-review`.
- **Artifacts:** `pii_result` with the new types populated; `configured_entity_types` reflects them.
- **Metrics:** per-type P/R/F1 for the AT/DE types; recall lift on `PHONE_NUMBER`/`IBAN_CODE`.
- **Tests/benchmarks:** recognizer unit tests with synthetic AT/DE-shaped values; benchmark deltas.
- **Tools:** Presidio custom pattern/context recognizers (no new heavy dependency).
- **Not in scope:** postal/address recognition remains open; NER tuning (L5); real values in tests.
- **Acceptance:** synthetic AT/DE identifiers are detected; `PHONE_NUMBER` recall rises materially
  on the benchmark without wrecking precision.

## Level 3 — Insurance / legal domain pack  ✅ *delivered*

- **Goal:** detect the domain identifiers that dominate insurance/legal documents.
- **Entity types:** `POLICY_NUMBER`, `CLAIM_NUMBER`, `CONTRACT_NUMBER`, `CASE_NUMBER`,
  `FILE_REFERENCE`, `REPORT_NUMBER`, `ASSESSMENT_NUMBER`, `INVOICE_NUMBER`, `OFFER_NUMBER`,
  `CUSTOMER_NUMBER`, `PROJECT_ID`, `TRANSACTION_ID`, `USER_ID`, `LICENSE_PLATE_AT`,
  `PASSPORT_NUMBER`, and `ID_CARD_NUMBER`.
- **Profiles:** completes `insurance-at-de`.
- **Artifacts:** `pii_result` with domain types; context-aware confidence.
- **Metrics:** per-type P/R/F1 for domain types; coverage of the domain-sensitive group (0 today).
- **Tests/benchmarks:** synthetic domain-shaped values; benchmark's `domain_sensitive_types` group.
- **Tools:** Presidio pattern + context recognizers, keyword anchors ("Polizzennr.", "Schadennr.").
- **Not in scope:** entity resolution across mentions (L6), review actions (L7).
- **Acceptance:** the `domain_sensitive_types` benchmark group moves off zero with acceptable
  precision on synthetic and corpus data.

## Level 4 — Entity profiles  ⏳ *coverage/configuration delivered; validation posture open*

- **Goal:** make coverage/aggressiveness a named, selectable profile rather than an ad-hoc env list.
- **Entity types:** whatever the chosen profile enables (see the [profiles table](#profiles-the-configuration-axis)).
- **Profiles:** `structured-only` / `insurance-at-de` / `broad-review` / `review-heavy` are
  first-class for entity coverage; per-profile validation posture remains open.
- **Artifacts:** `pii_result` records the active profile name; `configured_entity_types` derived
  from it.
- **Metrics:** per-profile P/R/F1; profile chosen vs profile appropriate for the document type.
- **Tests/benchmarks:** benchmark run per profile; profile selection tests.
- **Tools:** config layer over the existing adapter (no new detection dependency).
- **Not in scope:** automatic profile selection by document type (later), validation logic itself
  (L5).
- **Acceptance:** a named profile fully determines the entity set + validation posture and is
  recorded in the artifact.
- **Status today:** `PII_PROFILE` provides all four named coverage profiles and `pii_result` records
  the effective name (`custom` for an allowlist override). Per-profile validation posture and
  benchmark runs are still missing. → **partial.**

## Level 5 — Candidate validation / false-positive suppression  ✅ *done*

- **Goal:** prune or score-down obvious false positives *after* detection, especially NER noise.
- **Entity types:** full rules on `PERSON`/`ORGANIZATION`/`LOCATION`/`DATE_TIME`; a single
  context-presence check on `BIC` and the domain identifiers with weaker recognizer-level context
  requirements (`OFFER_NUMBER`, `CASE_NUMBER`, `PROJECT_ID`, `USER_ID`, `FILE_REFERENCE`,
  `REPORT_NUMBER`, `ASSESSMENT_NUMBER`, `CUSTOMER_NUMBER`); every other type is a deliberate
  pass-through.
- **Profiles:** the "validation posture" column is real, but emerges from *which entity types a
  profile enables* rather than profile-specific branching in the validator.
- **Artifacts:** `pii_result` gains additive per-entity `original_score`/`validation_status`/
  `validation_reasons` and a content-level `validation` summary (counts + reason codes, never a
  value). The original detection score is retained via `original_score`; validation is additive
  and auditable. A separate `pii_validation_result` artifact was considered and deliberately not
  built — see [ADR-0013](../adr/0013-pii-candidate-validation.md).
- **Metrics:** precision lift at fixed recall; FP reduction per type; dropped/score-down counts by
  reason code, corpus-wide via the benchmark runner.
- **Tests/benchmarks:** validation-rule unit tests; pii_service integration tests; benchmark
  before/after (see [`quality-metrics.md`](quality-metrics.md)).
- **Tools:** deterministic lexical/shape rules (small stopword/generic-word/company-form/name/
  address/date/financial-context lists) — **no spaCy POS dependency, no new detection model**.
- **Acceptance:** on the benchmark, NER precision rises substantially with negligible true-positive
  loss, and every suppression carries a reason.
- **Layout-context hardening:** candidate validation is not only token-level — it also accounts
  for document-layout context: address-line house/stair/door numbers (not `DATE_TIME`), AT
  postal-code lines, a company-form suffix immediately after an `ORGANIZATION` candidate,
  academic/professional-title and contact-role-label context for `PERSON`, and a top-of-document
  header/address-block position for `PERSON`/`ORGANIZATION`/`LOCATION`. See
  [ADR-0014](../adr/0014-pii-candidate-validation-context-hardening.md).
- **Detail:** see the [dedicated section below](#candidate-validation-is-a-post-processing-exclusion-step).

## Level 6 — Entity resolution / overlap logic  ⛔ *open*

- **Goal:** resolve overlapping/duplicate/nested candidates and link mentions of the same entity.
- **Entity types:** all; especially overlapping NER + structured spans on the same text.
- **Artifacts:** `pii_result` with resolved, de-duplicated entities and mention groups; overlap
  decisions recorded.
- **Metrics:** overlap-resolution correctness, duplicate rate, cross-mention consistency.
- **Tests/benchmarks:** overlap resolution unit tests; benchmark duplicate counts.
- **Tools:** in-house deterministic resolution over adapter output.
- **Not in scope:** human actions (L7), feedback rules (L8).
- **Acceptance:** overlapping candidates resolve deterministically and repeated mentions of one
  entity are grouped, without dropping distinct entities.
- **Status note:** the *display-layer* overlap resolver (`piiHighlights.ts`) and the schema's
  deterministic sort exist, but there is no *engine-level* entity resolution yet.

## Level 7 — Human review actions  ⛔ *open*

- **Goal:** let a reviewer confirm/reject/add/annotate candidates (the PII side of the
  [Review engine](review-feedback-levels.md)).
- **Artifacts:** `review_result` referencing the `pii_result` it acts on.
- **Metrics:** review corrections (confirm/reject/add counts), reviewer agreement.
- **Tools:** API + review UI; storage of decisions.
- **Acceptance:** a reviewer's confirm/reject/add on a candidate persists against the exact
  `pii_result` and text lineage. (Owned jointly with the Review engine — see its levels.)

## Level 8 — Feedback rules / local suppression rules  ⛔ *open*

- **Goal:** turn repeated review decisions into reusable, *scoped* rules (allow/deny lists).
- **Artifacts:** `review_result` + a rules store; `pii_result` annotated with which rule fired.
- **Metrics:** rule reuse rate, precision/recall change attributable to rules, over-suppression
  guardrail (a rule must not globally hide a whole entity type by accident).
- **Tools:** in-house rules engine, file-based first (see the
  [DB chapter](target-architecture.md#database-considerations)).
- **Not in scope:** AI plausibility (L9).
- **Acceptance:** a confirmed suppression rule applies consistently and its scope (document/profile/
  global) is explicit and auditable; global effects require deliberate opt-in.

## Level 9 — Local AI plausibility assist  ⛔ *open, optional*

- **Goal:** use a **local** model to *plausibilise* candidates in context (e.g. "is this token a
  person here?") — assistive, never authoritative.
- **Artifacts:** plausibility annotations on candidates flagged `assistive = true`; never a silent
  add/remove.
- **Metrics:** assist agreement with reviewer, precision lift, false-plausibility rate.
- **Tools:** local VLM/LLM behind an adapter (see
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding)).
- **Not in scope:** external inference; auto-deciding without a rule/human.
- **Acceptance:** plausibility hints are local, labelled, auditable, and only affect outcomes via an
  explicit validation rule or reviewer action.

## Level 10 — Production-grade PII engine  ⛔ *open*

- **Goal:** reliable, profile-driven detection + validation + resolution + review + feedback, tracked
  over time.
- **Artifacts:** the full set, versioned and lineage-complete.
- **Metrics:** the full [PII metric set](quality-metrics.md#pii-metrics) with per-type/per-profile
  thresholds, regression-gated.
- **Tests/benchmarks:** CI-gated benchmark; per-profile acceptance thresholds.
- **Acceptance:** detection quality meets agreed per-profile/per-type thresholds on the benchmark,
  is reproducible, and regressions fail the gate.

---

## Candidate validation is a post-processing exclusion step

This is important enough to state precisely, because it is easy to misread as "more detection".

```text
1. PII is detected first (Presidio/spaCy recognizers produce candidates).
2. Candidate validation then inspects those candidates.
3. Its only job: drop obvious false positives, or lower their score.
4. It never creates new detections and never raises a score to "invent" PII.
```

Illustrative rules (synthetic examples only):

- A `PERSON` candidate that is only a stopword / article / preposition → **discard or score down.**
- An `ORGANIZATION` candidate that is only a generic document word ("Rechnung", "Anlage") →
  **score down.**
- A `LOCATION` candidate with no address/place context nearby → **score down.**
- A `DATE_TIME` candidate is **disambiguated by context** into roles — birth date, invoice date,
  claim date, offer date — to inform review/redaction, not to add a detection.

Why this matters here: on the local benchmark the NER group produced hundreds of candidates at a
fixed score the score-threshold cannot separate (`LOCATION` was almost entirely false positives).
Candidate validation is the *correct* lever for that — subtractive, rule-based, auditable — rather
than turning NER off (which loses real recall) or inventing a new recognizer.

Validation output is always **additive and auditable**: the original candidate and the validation
verdict + reason both survive, so a human (or a later review action) can override the machine.

---

## Where the project stands (PII)

| Level | State | Evidence |
| --- | --- | --- |
| 0 None | n/a | — |
| 1 Structured basics | ✅ done (quality uneven on AT/DE) | Presidio structured recognizers, default allowlist |
| 2 AT/DE pattern pack | ✅ core delivered | Presidio pattern/context recognizers; address remains open |
| 3 Insurance/legal pack | ✅ done | domain-sensitive recognizers and benchmark coverage |
| 4 Entity profiles | ⏳ partial | named coverage profiles recorded; per-profile benchmark reporting open |
| 5 Candidate validation | ✅ done | KEEP/SCORE_DOWN/DROP post-processing; NER over-tagging reduced |
| 6 Entity resolution | ⛔ open | display-only overlap resolution exists |
| 7 Human review actions | ⛔ open | review UI is display-only |
| 8 Feedback rules | ⛔ open | — |
| 9 Local AI plausibility | ⛔ open | — |
| 10 Production-grade | ⛔ open | — |

**Benchmark signal (aggregate private before/after run, candidate ground truth — a regression
signal, not a gold standard), 12-document corpus, two deterministic runs per profile:**

**`review-heavy` (NER opt-in) — Engine-4 final → Engine-5 (candidate validation on):**

| Metric | Before (Engine-4) | After (Engine-5) |
| --- | --- | --- |
| Global | 119 TP / 487 FP / 90 FN, P=0.1964, R=0.5694, F1=0.2920 | 118 TP / 145 FP / 91 FN, P=0.4487, R=0.5646, F1=0.5000 |
| NER group | 42 TP / 455 FP / 29 FN, P≈0.08, R≈0.59 | 41 TP / 118 FP / 30 FN, P=0.2579, R=0.5775, F1=0.3565 |
| Structured group | P=0.9130→0.7937 (Engine-4 delta), R=0.8772 | unchanged: P=0.7937, R=0.8772, F1=0.8333 |
| Domain-sensitive group | 27 TP / 19 FP / 20 FN, P=0.5870, R=0.5745 | 27 TP / 14 FP / 20 FN, P=0.6585, R=0.5745, F1=0.6136 |
| Validation | — | kept=263, dropped=14, score_down=329 (12/12 docs, validation enabled) |
| Dropped by reason | — | `TOO_SHORT_SINGLE_TOKEN`=10, `GENERIC_DOCUMENT_WORD`=2, `NER_SINGLE_COMMON_WORD`=1, `NUMERIC_ONLY_FOR_NER`=1 |
| Score-down by reason | — | `ORG_WITHOUT_ORG_SIGNAL`=147, `LOCATION_WITHOUT_LOCATION_SIGNAL`=108, `MISSING_REQUIRED_CONTEXT`=69, `BIC_WITHOUT_FINANCIAL_CONTEXT`=5 |

NER precision more than tripled (FP −74%, 455→118) for a true-positive cost of exactly 1 (42→41),
and global FP fell 70% (487→145) while recall moved by −0.0048 — confirming the L5 goal: raise
precision without collapsing recall. `ORG_WITHOUT_ORG_SIGNAL` and
`LOCATION_WITHOUT_LOCATION_SIGNAL` dominate, exactly the generic-word-without-signal FP class the
rules target.

**`insurance-at-de` (no NER) — Engine-4 final → Engine-5:**

| Metric | Before | After |
| --- | --- | --- |
| Global | 77 TP / 32 FP / 132 FN, P=0.7064, R=0.3684, F1=0.4843 | 77 TP / 27 FP / 132 FN, P=0.7404, R=0.3684, F1=0.4920 |
| Domain-sensitive group | P=0.5870, R=0.5745 | P=0.6585, R=0.5745, F1=0.6136 (5 `BIC` score-downs) |
| Structured group | P=0.7937, R=0.8772 | unchanged: P=0.7937, R=0.8772, F1=0.8333 |

No regression: precision improved slightly (the 5 unlabelled `BIC` candidates were the only
change), recall and the structured group are bit-for-bit unchanged, confirming light/pass-through
types are untouched.

**Determinism:** two consecutive `make benchmark-private` runs per profile produced identical
reports (timestamps aside).

**Unsupported types** (both profiles, after regenerating artifacts): exactly the seven documented
labels — `ADDRESS`, `BIRTH_DATE`, `BIRTH_PLACE`, `CONTACT_LINE`, `CUSTOMER_LINE`, `FAMILY_NAME`,
`GIVEN_NAME`.

**What is missing next:**
1. Address/contact-line recognition and the seven remaining unsupported semantic labels.
2. Per-profile benchmark runs in one invocation (today: rerun per configured profile) and
   validation posture surfaced per-profile, to complete L4.
3. Review/feedback persistence (Engine-6) so a human can act on validation-surviving candidates.

See [`roadmap.md`](roadmap.md) (Engine-5) for the next step.
