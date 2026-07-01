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
| `structured-only` | High precision, low noise (current default) | EMAIL/PHONE/IBAN/CREDIT_CARD/IP/URL | validation not implemented |
| `insurance-at-de` | AT/DE + insurance/legal domain identifiers | structured + AT/DE + policy/claim/contract/… | validation not implemented |
| `broad-review` | Maximise recall for a human reviewer | above + PERSON/ORGANIZATION/LOCATION | validation not implemented |
| `review-heavy` | Nothing missed; reviewer resolves everything | above + DATE_TIME | validation not implemented |

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
- **Profiles:** `structured-only` (as the env default).
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

## Level 5 — Candidate validation / false-positive suppression  ⛔ *open (priority)*

- **Goal:** prune or score-down obvious false positives *after* detection, especially NER noise.
- **Entity types:** applies to all, but primarily tames `PERSON/ORGANIZATION/LOCATION/DATE_TIME`.
- **Profiles:** the "validation posture" column becomes real here.
- **Artifacts:** a `pii_validation_result` (or an annotation on `pii_result`) recording, per
  candidate, the validation verdict + reason + score adjustment. The original detection is retained;
  validation is additive and auditable.
- **Metrics:** precision lift at fixed recall; FP reduction per type; false-suppression rate
  (validation must not remove true positives).
- **Tests/benchmarks:** validation-rule unit tests; benchmark precision delta with validation on/off.
- **Tools:** deterministic rules over spaCy POS/stopword info (already available via the spaCy model
  behind the adapter); optional dictionaries — **no new detection model**.
- **Acceptance:** on the benchmark, NER precision rises substantially with negligible true-positive
  loss, and every suppression carries a reason.
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
| 4 Entity profiles | ⏳ partial | named coverage profiles recorded; validation posture open |
| 5 Candidate validation | ⛔ open | no post-processing; NER over-tags |
| 6 Entity resolution | ⛔ open | display-only overlap resolution exists |
| 7 Human review actions | ⛔ open | review UI is display-only |
| 8 Feedback rules | ⛔ open | — |
| 9 Local AI plausibility | ⛔ open | — |
| 10 Production-grade | ⛔ open | — |

**Benchmark signal (aggregate private before/after run, candidate ground truth — a regression
signal, not a gold standard).** With NER enabled (`review-heavy`) over a 12-document corpus:

- **Structured group** — recall rose from ~0.37 to ~0.88; precision moved from ~0.91 to ~0.68 as
  additional AT/DE phone, IBAN, and URL formats became visible.
- **NER group** — high recall (~0.59) but very low precision (~0.08): `LOCATION`/`ORGANIZATION`/
  `PERSON` over-tag massively at a fixed score. → confirms the L5 (candidate validation) priority.
- **Domain-sensitive group** — moved from zero coverage to 28 TP / 22 FP / 19 FN (~0.56 precision,
  ~0.60 recall). Four expected labels moved from the old `other` bucket into this canonical group.

**What is missing next:**
1. L5 candidate validation to make `broad-review` usable by cutting NER false positives.
2. Address/contact-line recognition and the seven remaining unsupported semantic labels.
3. Per-profile benchmark runs and validation posture to complete L4.

See [`roadmap.md`](roadmap.md) (Engine-5) for the next step.
