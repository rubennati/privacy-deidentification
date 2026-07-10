# PII / Sensitive-Data Engine — Levels 0–19

The PII engine turns the canonical text (`best_text_result`) into **labelled sensitive spans** so a
human can review them and, later, so redaction can build on them. It is the second sub-engine in the
[north star](README.md#north-star).

Principles specific to this engine:

- **Detection-only.** It labels spans; it never anonymises, masks, or alters the document.
- **Precision-first defaults.** Noisy recognizers are opt-in, not on by default.
- **Candidate validation is a distinct pipeline stage.** After detection, a *subtractive*
  validation stage (L6) prunes/scores-down obvious false positives. It is a post-processing filter,
  **not** a new detection mechanism (see the
  [dedicated section](#candidate-validation-is-a-post-processing-exclusion-step)).
- **Tool-first / adapter-bound.** Recognition is Presidio + spaCy (and later compatible tools)
  behind an adapter. Presidio pattern recognizers, context rules, candidate validation, and small
  deterministic domain heuristics are allowed under the quality constraints in
  [`AGENTS.md`](../../AGENTS.md); a bespoke NER engine is not.

Level numbers are cumulative and **not** comparable to the OCR, Review, Benchmark, or Redaction
ladders. This engine uses the **0–19 maturity scale** ([why 0–19](README.md#maturity-scale)); a
mapping from the previous 0–10 ladder is in
[Legacy scale mapping](#legacy-scale-mapping-010--019).

**What** the engine detects — the business categories, concrete entity types, their risk /
protection class (P0–P5), and the fitting detection strategy — is modelled in
[`entity-taxonomy.md`](entity-taxonomy.md). This ladder is the *maturity* axis; the taxonomy is the
*coverage/sensitivity* axis.

**Current standing:** **L13 done (L0–L9, L11–L13); L10 partial (dev-only human feedback capture).**
Structured + AT/DE + insurance/legal recognizers, named profiles, benchmark, candidate validation,
context hardening, address/contact-line coverage, and reproducible artifact `engine_settings` are
all shipped. A **dev-only** per-entity feedback-capture side-channel exists (behind
`ENABLE_DEV_ENGINE_SETTINGS`). Conservative entity grouping (L11) is delivered as a derived
view over `pii_result`, paired with a lineage-bound review-decision overlay that covers much of the
*practical* intent of the later L13 review-confirm/reject step without yet being that formal
artifact model (see [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md) for the
precise scope). Engine-level **overlap resolution (L12)** is now delivered: PII consumes the OCR
Output Contract v1 Document Text Package through the `pii_input` intake adapter and resolves
duplicate/nested/overlapping candidates deterministically with provenance
([ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md)).

The pipeline this ladder describes:

```text
detect (Presidio/spaCy + shipped recognizers)   L1–L4
  → measure quality (benchmark/regression)       L5
  → validate candidates (subtractive filter)     L6–L8   (context hardening, address/contact)
  → make runs reproducible (engine_settings)     L9
  → capture human feedback / review              L10–L14
  → close the loop (regression, policy)           L15–L16
  → stabilise the entity model                    L17
  → become redaction-ready                        L18–L19
```

## Profiles (the configuration axis)

Profiles bundle *which entity types are active*. They are first-class configuration and are recorded
in `pii_result`. Profile selection is a **Level 2** capability; the per-type validation intensity is
a **Level 6** concern.

| Profile | Intent | Entity coverage | Validation posture |
| --- | --- | --- | --- |
| `structured-only` | High precision, low noise (conservative code fallback if `PII_PROFILE` is unset; `.env.example` recommends `review-heavy` for interactive review) | EMAIL/PHONE/IBAN/CREDIT_CARD/IP/URL | validation runs, near-zero drops (light types pass through) |
| `insurance-at-de` | AT/DE + insurance/legal domain identifiers | structured + AT/DE + policy/claim/contract/… + ADDRESS/CONTACT_LINE/CUSTOMER_LINE ([ADR-0015](../adr/0015-structured-address-contact-line-recognizers.md)) | validation runs; only `BIC` + a few domain IDs get a context check |
| `broad-review` | Maximise recall for a human reviewer | above + PERSON/ORGANIZATION/LOCATION | full lexical/context validation on PERSON/ORGANIZATION/LOCATION |
| `review-heavy` | Nothing missed; reviewer resolves everything | above + DATE_TIME | above, plus DATE_TIME year-only/shape checks |

Validation intensity is a function of *entity type*, not profile — see
[Level 6](#level-6--candidate-validation--false-positive-suppression---done) and
[ADR-0013](../adr/0013-pii-candidate-validation.md). Because `structured-only`/`insurance-at-de`
never configure PERSON/ORGANIZATION/LOCATION/DATE_TIME, the strong rules simply never fire for those
profiles — there is no profile branching in the validator itself.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Detection basics | 0–3 | Structured recognizers, profiles/config, NER integration |
| Domain coverage + validation | 4–9 | AT/DE/domain packs, benchmark, candidate validation, context hardening, address/contact, reproducible settings |
| Review / feedback + entity quality | 10–14 | Human feedback capture, grouping, overlap resolution, confirm/reject, manual add |
| Regression + policy | 15–16 | Feedback-derived regression sets, policy/profile presets |
| De-identification readiness | 17–19 | Stable entity model + lineage, redaction-ready spans, production-near engine |

---

## Level 0 — No PII detection

- **Description:** text exists, nothing is labelled.
- **Acceptance:** the pipeline can carry text without any PII stage.
- **Boundary to L1:** L1 introduces the first (structured) recognizers.

## Level 1 — Structured recognizers  ✅ *done*

- **Description:** detect high-precision, pattern-based structured identifiers.
- **Entity types:** `EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, CREDIT_CARD, IP_ADDRESS, URL`.
- **Artifacts:** `pii_result` with page-local + global offsets, per-type counts, tool versions.
- **Acceptance:** structured identifiers are detected with stable Unicode-codepoint offsets and
  stored immutably.
- **Boundary to L2:** L1 is a fixed recognizer set; L2 makes coverage a named, selectable profile.

## Level 2 — Profile / config system  ✅ *done*

- **Description:** make coverage a named, selectable profile rather than an ad-hoc env list.
- **Config:** `PII_PROFILE` (`structured-only`/`insurance-at-de`/`broad-review`/`review-heavy`);
  `PII_ENTITY_TYPES` is a backwards-compatible allowlist override recorded as profile `custom`.
- **Artifacts:** `pii_result` records the effective profile name and `configured_entity_types`.
- **Acceptance:** a named profile fully determines the entity set and is recorded in the artifact; an
  allowlist override is recorded as `custom`.
- **Boundary to L3:** L2 selects *which* types are active; L3 adds the NER model that some of those
  types need.

## Level 3 — NER / model integration  ✅ *done*

- **Description:** integrate a real NER backend so model-based types (PERSON/ORGANIZATION/LOCATION,
  DATE_TIME) are *available* — opt-in, because the small German model over-tags at a fixed score.
- **Tools:** Presidio Analyzer + spaCy (`de_core_news_sm`) behind a lazy adapter; language via
  `PII_LANGUAGE`, model via `PII_SPACY_MODEL`.
- **Artifacts:** `pii_result` with NER types when a broader profile enables them.
- **Acceptance:** NER types are detectable when enabled and stay off by default; missing
  packages/model/language-mismatch fail cleanly (`503`), never silently.
- **Boundary to L4:** L3 gives generic NER; L4 adds region/domain-specific structured recognizers.

## Level 4 — AT/DE / domain recognizers  ✅ *done*

- **Description:** detect Austrian/German and insurance/legal/business identifiers the generic
  recognizers miss.
- **Entity types:** AT/DE phone/IBAN/URL/credit-card variants, `SVNR_AT`, `UID_AT`, `FN_AT`, `BIC`,
  `TAX_ID_AT`, `LICENSE_PLATE_AT`, `PASSPORT_NUMBER`, `ID_CARD_NUMBER`, plus domain types
  (`POLICY_NUMBER`, `CLAIM_NUMBER`, `CONTRACT_NUMBER`, `CASE_NUMBER`, `FILE_REFERENCE`,
  `REPORT_NUMBER`, `ASSESSMENT_NUMBER`, `INVOICE_NUMBER`, `OFFER_NUMBER`, `CUSTOMER_NUMBER`,
  `PROJECT_ID`, `TRANSACTION_ID`, `USER_ID`). See
  [ADR-0012](../adr/0012-insurance-at-de-pii-recognizers.md).
- **Tools:** Presidio pattern/context recognizers (no new heavy dependency); keyword anchors
  ("Polizzennr.", "Schadennr.").
- **Acceptance:** synthetic AT/DE + domain identifiers are detected; `PHONE_NUMBER` recall and the
  `domain_sensitive_types` group move off zero on the benchmark without wrecking precision.
- **Boundary to L5:** L4 broadens detection; L5 makes detection *quality measurable*.

## Level 5 — Benchmark / regression  ✅ *done*

- **Description:** measure detection quality reproducibly against a private candidate ground truth.
- **Delivered:** the stdlib-only private benchmark runner (`scripts/benchmark/`,
  `make benchmark-private`) reports P/R/F1 per doc/type/group/global, guarded by `privacy_guard.py`.
  See [ADR-0010](../adr/0010-private-benchmark-runner.md) and
  [`benchmark-engine-levels.md`](benchmark-engine-levels.md).
- **Acceptance:** a run produces per-type/group/global P/R/F1 from existing artifacts, deterministically
  and without writing any raw text/PII value.
- **Boundary to L6:** with quality now measurable, L6 introduces the validation stage that raises
  precision.

## Level 6 — Candidate validation / false-positive suppression  ✅ *done*

`PII_CANDIDATE_VALIDATION_ENABLED` is **not merely a flag** — it switches on a **distinct pipeline
stage that runs after detection**. This stage is a first-class part of the engine's maturity.

- **Description:** prune or score-down obvious false positives *after* detection, especially NER
  noise — subtractive, rule-based, auditable.
- **Entity types:** full rules on `PERSON`/`ORGANIZATION`/`LOCATION`/`DATE_TIME`; a single
  context-presence check on `BIC` and a handful of weak-context domain IDs (`OFFER_NUMBER`,
  `CASE_NUMBER`, `PROJECT_ID`, `USER_ID`, `FILE_REFERENCE`, `REPORT_NUMBER`, `ASSESSMENT_NUMBER`,
  `CUSTOMER_NUMBER`); every other type is a deliberate pass-through.
- **Artifacts:** `pii_result` gains additive per-entity `original_score`/`validation_status`/
  `validation_reasons` and a content-level `validation` summary (counts + reason codes, never a
  value). A separate `pii_validation_result` artifact was considered and deliberately **not** built —
  see [ADR-0013](../adr/0013-pii-candidate-validation.md).
- **Config:** `PII_CANDIDATE_VALIDATION_ENABLED` (default on) is an escape hatch back to raw
  detection output; a dropped candidate never appears in `entities`, a score-down is capped at `0.3`
  (below the `0.5` threshold).
- **Acceptance:** on the benchmark, NER precision rises substantially with negligible true-positive
  loss, and every suppression carries a reason code.
- **Boundary to L7:** L6 is token-level; L7 hardens it with document-layout context.

## Level 7 — Context hardening  ✅ *done*

- **Description:** make validation aware of document-layout context, not just tokens.
- **Engine must:** account for address-line house/stair/door numbers (not `DATE_TIME`), AT postal-code
  lines, a company-form suffix after an `ORGANIZATION` candidate, academic/professional-title and
  contact-role-label context for `PERSON`, and top-of-document header/address-block position for
  `PERSON`/`ORGANIZATION`/`LOCATION`. See
  [ADR-0014](../adr/0014-pii-candidate-validation-context-hardening.md).
- **Acceptance:** layout-context cases (title-preceded person, header-block org) validate correctly
  on the benchmark without new detections.
- **Boundary to L8:** L7 hardens existing types; L8 adds explicit address/contact-line coverage.

## Level 8 — Address / contact-line coverage  ✅ *done*

- **Description:** cover multi-token addresses and labelled contact/customer lines that single-token
  recognizers miss.
- **Entity types:** `ADDRESS`, `CONTACT_LINE`, `CUSTOMER_LINE` (street shape + labelled-line capture
  with content-shape checks). See
  [ADR-0015](../adr/0015-structured-address-contact-line-recognizers.md).
- **Acceptance:** the benchmark `address_contact_types` group moves off zero with acceptable
  precision/recall; a labelled line without any contact signal is deliberately not marked.
- **Boundary to L9:** L8 completes near-term coverage; L9 makes a run reproducible and dev-selectable.

## Level 9 — Reproducible engine settings + dev engine settings  ✅ *done*

- **Description:** make a PII run reproducible from recorded settings, and allow safe per-run
  overrides in dev.
- **Engine must:** record effective non-sensitive settings under `pii_result.content.engine_settings`
  (`pii_profile`, candidate validation, score threshold, source); expose read-only PII defaults +
  the `ENABLE_DEV_ENGINE_SETTINGS` gate via `GET /api/config`; when the gate is on, allow the detail
  UI to override the profile for **one local run only** — `.env`/backend defaults stay authoritative.
- **Config:** `PII_SCORE_THRESHOLD`, `PII_PROFILE`, `PII_CANDIDATE_VALIDATION_ENABLED`,
  `ENABLE_DEV_ENGINE_SETTINGS` (see [`engine-settings.md`](engine-settings.md)).
- **Acceptance:** two runs with identical inputs + recorded settings produce identical entities; the
  effective settings are visible in the artifact; with the gate off, no per-run override is possible.
- **Boundary to L10:** L9 makes machine output reproducible; L10 starts capturing *human* signal on
  it.

## Level 10 — Human feedback capture  ⏳ *partial — dev-only, current frontier*

- **Description:** capture structured human feedback per detected entity so recurring detection
  errors can be analysed — **analysis input only, not a learning system.**
- **Delivered (dev-only, behind `ENABLE_DEV_ENGINE_SETTINGS`):** a per-entity "correct"/issue verdict
  with optional comment, appended to `document-store/{id}/feedback/pii_feedback.jsonl`; on load, the
  latest verdict per entity key (type+start+end+recognizer) is restored and the card locks. Writes
  are accepted only for entities present in the referenced `pii_result`; the artifact supplies the
  stored score. The structured fingerprint excludes document/OCR/entity text, `text_hash` is limited
  to a SHA-256 digest, and comments must not contain copied document text or raw PII. The file remains
  inside the protected document-store boundary. It never mutates `pii_result` and applies no rules. See
  [`review-feedback-levels.md`](review-feedback-levels.md#level-5--per-entity-dev-feedback-capture---partial--dev-only-current-frontier).
- **Why partial:** production stays gated off; this is the analysis side-channel, not the binding
  L13 review overlay.
- **Acceptance:** with the gate on, a per-entity verdict persists within the documented local
  feedback boundary and is restored on reload; with the gate off, the feedback endpoints return
  `403` and the controls are hidden.
- **Boundary to L11:** L10 captures feedback on a *flat list*; L11 groups repeated occurrences of the
  same entity.

## Level 11 — Entity grouping / repeated occurrences  ✅ *done*

- **Description:** present each distinct entity once and collect its occurrences/offsets beneath it
  (`PERSON Max Mustermann → 0–14, 220–234, 540–554`), with clickable offsets and feedback per
  occurrence or per group.
- **Delivered:** `pii_grouping.group_pii_entities()` groups `pii_result` entities by entity type +
  a conservative per-type normalized-value fingerprint (exact lowercase email, whitespace/case
  IBAN normalization, digit/`+`-only phone normalization, whitespace-stripped ID-like types, exact
  whitespace-normalized text for names/organizations/addresses/dates/everything else). Grouping is
  a **pure, derived view** — it is recomputed from the latest `pii_result` on every
  `GET …/pii/review` request and stores nothing on `PiiEntity`/`PiiContent`/`PiiArtifact`, so
  detection and the existing `pii_result` schema are unchanged. `entity_group_id` and
  `normalized_fingerprint` are SHA-256 hashes of type + normalized value (never the raw value
  itself); each group also carries a reading-text projection coverage summary
  (exact/partial/unmapped counts). See
  [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).
- **Engine/UI must:** group by a stable entity key without changing detection; keep jump-to-text per
  occurrence.
- **Acceptance:** repeated mentions of one entity render as a single group with correct per-occurrence
  offsets; grouping never drops or invents a detection. Different entity types, fuzzy name
  variants, and proximity alone never merge into one group.
- **Boundary to L12:** L11 groups *same-type* mentions; L12 resolves *conflicts between overlapping*
  candidates.

## Level 12 — Overlap / conflict resolution  ✅ *done*

- **Description:** resolve overlapping/duplicate/nested candidates deterministically (engine-level,
  not just display), as a **consumer of the OCR Output Contract v1 Document Text Package**.
- **Delivered:** PII consumes `DocumentTextPackageV1` through the `pii_input` intake adapter
  (`PiiInputDocumentV1`) — raw text stays the primary/only active detection input, canonical is
  contextual, structured content a hint, quality/noise evidence trust context — and
  `pii_overlap.resolve_pii_overlaps` runs after candidate validation:
  - **exact duplicates** (same start/end/type) merge into one survivor (`exact_duplicate` /
    `recognizer_duplicate`, decision `merged_provenance`);
  - **same-type overlaps/nesting** keep the strongest span (longest → highest score → earliest →
    recognizer → id) and drop the rest, recording their ids on the survivor (`nested_entity` /
    `same_type_overlap`, `longer_span_selected` / `stronger_confidence_selected`);
  - **different-type overlaps** are **never dropped** — both are preserved and flagged for review
    (`conflicting_entity_type` + `ambiguous_overlap_review_required`).
  Entity offsets/text/scores are never modified. Additive optional `pii_result` fields carry the
  outcome (`PiiEntity.provenance`, `PiiContent.input_contract`, `PiiContent.overlap_resolution`),
  all reason-codes/counts/ids only — no raw text. See
  [ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md).
- **Status note:** the display-layer resolver (`piiHighlights.ts`) still exists for rendering; this
  adds the engine-level resolution beneath it. A specific cross-type auto-suppression precedence
  table (structured id > generic id, `ADDRESS` > `LOCATION`, e-mail > inner URL fragment) is
  deliberately deferred in favour of flag-for-review, pending benchmark/review evidence.
- **Acceptance:** overlapping candidates resolve deterministically without dropping distinct
  (cross-type) entities; merge/drop/flag decisions are recorded in provenance and the run summary.
- **Anchor-bound entity contract (additive stabilization, not a level bump):** on top of L12 and
  ADR-0031 Phase B, a pure derived view (`pii_anchor_binding.py`, `pii_entity_contract.py`,
  `GET …/pii/entity-contract`) packages the resolved entities review-ready with anchor-derived
  identity where the matching Text Anchor Graph binds, explicit evidence-only fallback when binding
  is missing/ambiguous/not applicable, detector source observations, raw + optional
  canonical/layout display ranges, canonical `mapping_status`, overlap provenance, resolved review
  state, and a text-free display model. Binding and entity-contract summaries report
  raw/canonical/layout range coverage plus reason-code counts for missing canonical/layout ranges,
  degraded or missing anchor graphs, repeated-token ambiguity, reading-text mapping gaps, and
  intentionally conservative layout mapping. Missing/partial/ambiguous anchor or canonical mapping
  never drops an entity. This is the stable foundation the formal L13 `review_result` builds on,
  **not** that binding artifact itself. See
  [ADR-0029](../adr/0029-pii-review-ready-entity-contract.md) and
  [ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md).
- **Boundary to L13:** L12 makes the machine's entity set clean; L13 makes a human's decision binding.

## Level 13 — Review confirm / reject  ✅ *done*

- **Description:** let a reviewer confirm or reject a candidate, bindingly.
- **Artifacts:** a `review_result` overlay carries direct `pii_result.id` + `text_result.id`
  lineage; the append-only decision record and immutable snapshot both store the consumed text
  artifact id. The `pii_result` stays immutable. Owned jointly with the
  [Review engine](review-feedback-levels.md#level-9--confirm--reject---done).
- **Acceptance:** met. The pseudonymize-by-default binding action (`pseudonymize`/`keep`/
  `false_positive`) persists at group or occurrence scope, re-renders on reload, and a later PII
  run marks it stale rather than reapplying it.
- **Boundary to L14:** L13 acts on machine candidates; L14 lets a human add what the machine missed.

## Level 14 — Manual add / missed entities  ⛔ *open*

- **Description:** let a reviewer add a span the engine missed, with a type.
- **Artifacts:** manual additions in `review_result` with canonical-text offsets and `origin = human`.
- **Acceptance:** a human-added span round-trips with valid offsets and is distinguishable from
  machine detections; it becomes a recall (missed-entity) signal.
- **Boundary to L15:** L14 records corrections; L15 turns them into regression data.

## Level 15 — Feedback-derived regression sets  ⛔ *open*

- **Description:** promote confirmed/rejected/added decisions into the private benchmark ground-truth
  signal (locally, privately).
- **Artifacts:** review-derived corrections exported into `volumes/benchmark/` (never committed).
- **Acceptance:** a reviewer can turn corrections into private benchmark data without exporting any
  PII outside `volumes/`; regression numbers become more trustworthy.
- **Boundary to L16:** L15 improves the ground truth; L16 ties review coverage to a policy.

## Level 16 — Policy / profile presets  ⛔ *open*

- **Description:** review/detect under a policy (e.g. GDPR/insurance) that defines which types *must*
  be handled, with required-field checks.
- **Artifacts:** policy + per-policy completeness alongside the profile; ties to the
  [profiles axis](#profiles-the-configuration-axis).
- **Acceptance:** completeness is measurable against a named policy before a document counts as
  "reviewed".
- **Boundary to L17:** L16 governs coverage; L17 stabilises the entity model itself.

## Level 17 — Stable entity model with lineage  ⛔ *open*

- **Description:** a stable, resolved, lineage-complete entity model (grouped, overlap-resolved,
  review-adjusted) that downstream stages can rely on.
- **Acceptance:** each entity has a stable identity across occurrences and re-runs, with explicit
  lineage to the text and review artifacts it derives from.
- **Design:** the target substrate is the OCR/Text-owned **text anchor** identity layer in
  [ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md) (**Phase B anchor graph and
  Phase C PII binding implemented additively**) — PII entities bind to anchors (`entity_anchors`)
  rather than string offsets where anchors are available, with explicit evidence-only fallback for
  missing/ambiguous/no-graph cases. This is what makes identity stable across views/re-runs and
  consistent between raw and canonical highlights.
- **Boundary to L18:** L17 stabilises the model; L18 makes its spans redaction-ready.

## Level 18 — Redaction-ready entity spans  ⛔ *open*

- **Description:** produce entity spans that de-identification can act on directly — reviewed, stable,
  and (with OCR L15) mappable to page geometry.
- **Acceptance:** for an approved entity, the engine yields exact canonical spans (and, via OCR L15,
  page regions) sufficient for the [Redaction engine](redaction-engine-levels.md) to remove/replace
  it with no drift.
- **Boundary to L19:** L18 makes spans redaction-ready; L19 is the whole engine, production-near.

## Level 19 — Production-near local PII / de-identification engine  ⛔ *open*

- **Description:** reliable, profile-driven detection + validation + resolution + review + feedback,
  tracked over time and reproducible.
- **Acceptance:** detection quality meets agreed per-profile/per-type thresholds on the benchmark, is
  reproducible from recorded settings, and regressions fail the gate.
- **Boundary:** top of the ladder; further work is accuracy/coverage improvement within this envelope.

---

## Candidate validation is a post-processing exclusion step

This is important enough to state precisely, because it is easy to misread as "more detection". It is
the **Level 6** pipeline stage.

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

Validation output is **auditable within its artifact contract**: surviving candidates retain their
original score, validation status, and reason codes. Dropped candidates are represented only by
aggregate counts and reason codes, not preserved individually; a later binding review workflow
must account for that boundary explicitly.

---

## Where the project stands (PII)

| Level | State | Evidence |
| --- | --- | --- |
| 0 None | n/a | — |
| 1 Structured recognizers | ✅ done | Presidio structured recognizers, default allowlist |
| 2 Profile / config | ✅ done | `PII_PROFILE` + `PII_ENTITY_TYPES` (`custom`), recorded in artifact |
| 3 NER / model integration | ✅ done | Presidio + spaCy `de_core_news_sm`, NER opt-in |
| 4 AT/DE / domain recognizers | ✅ done | [ADR-0012](../adr/0012-insurance-at-de-pii-recognizers.md) pack |
| 5 Benchmark / regression | ✅ done | `make benchmark-private`, [ADR-0010](../adr/0010-private-benchmark-runner.md) |
| 6 Candidate validation | ✅ done | KEEP/SCORE_DOWN/DROP stage, [ADR-0013](../adr/0013-pii-candidate-validation.md) |
| 7 Context hardening | ✅ done | [ADR-0014](../adr/0014-pii-candidate-validation-context-hardening.md) |
| 8 Address / contact-line | ✅ done | [ADR-0015](../adr/0015-structured-address-contact-line-recognizers.md) |
| 9 Reproducible + dev settings | ✅ done | `content.engine_settings`, `ENABLE_DEV_ENGINE_SETTINGS` |
| 10 Human feedback capture | ⏳ partial | dev-only per-entity feedback JSONL; not the binding overlay |
| 11 Entity grouping | ✅ done | derived `pii_grouping.py` view + review-decision overlay ([ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) |
| 12 Overlap / conflict resolution | ✅ done | `pii_input` adapter + deterministic `pii_overlap` resolution + anchor-bound entity diagnostics ([ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md), [ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md)) |
| 13 Review confirm / reject | ⛔ open | review UI is display + dev-feedback only |
| 14 Manual add | ⛔ open | — |
| 15 Feedback-derived regression | ⛔ open | benchmark inputs hand-authored today |
| 16 Policy / profile presets | ⛔ open | profiles exist as config, not policy |
| 17 Stable entity model + lineage | ⛔ open | — |
| 18 Redaction-ready spans | ⛔ open | prerequisite for [Redaction](redaction-engine-levels.md) |
| 19 Production-near | ⛔ open | — |

**Benchmark signal (aggregate private before/after run, candidate ground truth — a regression
signal, not a gold standard), 12-document corpus, two deterministic runs per profile:**

**`review-heavy` (NER opt-in) — PII L4/L5 baseline → PII L6 candidate validation:**

| Metric | Before PII L6 | After PII L6 |
| --- | --- | --- |
| Global | 119 TP / 487 FP / 90 FN, P=0.1964, R=0.5694, F1=0.2920 | 118 TP / 145 FP / 91 FN, P=0.4487, R=0.5646, F1=0.5000 |
| NER group | 42 TP / 455 FP / 29 FN, P≈0.08, R≈0.59 | 41 TP / 118 FP / 30 FN, P=0.2579, R=0.5775, F1=0.3565 |
| Structured group | P=0.9130→0.7937 (L4-domain-pack delta), R=0.8772 | unchanged: P=0.7937, R=0.8772, F1=0.8333 |
| Domain-sensitive group | 27 TP / 19 FP / 20 FN, P=0.5870, R=0.5745 | 27 TP / 14 FP / 20 FN, P=0.6585, R=0.5745, F1=0.6136 |
| Validation | — | kept=263, dropped=14, score_down=329 (12/12 docs, validation enabled) |
| Dropped by reason | — | `TOO_SHORT_SINGLE_TOKEN`=10, `GENERIC_DOCUMENT_WORD`=2, `NER_SINGLE_COMMON_WORD`=1, `NUMERIC_ONLY_FOR_NER`=1 |
| Score-down by reason | — | `ORG_WITHOUT_ORG_SIGNAL`=147, `LOCATION_WITHOUT_LOCATION_SIGNAL`=108, `MISSING_REQUIRED_CONTEXT`=69, `BIC_WITHOUT_FINANCIAL_CONTEXT`=5 |

NER precision more than tripled (FP −74%, 455→118) for a true-positive cost of exactly 1 (42→41),
and global FP fell 70% (487→145) while recall moved by −0.0048 — confirming the L6 goal: raise
precision without collapsing recall.

**`insurance-at-de` (no NER) — PII L4/L5 baseline → PII L6:**

| Metric | Before | After |
| --- | --- | --- |
| Global | 77 TP / 32 FP / 132 FN, P=0.7064, R=0.3684, F1=0.4843 | 77 TP / 27 FP / 132 FN, P=0.7404, R=0.3684, F1=0.4920 |
| Domain-sensitive group | P=0.5870, R=0.5745 | P=0.6585, R=0.5745, F1=0.6136 (5 `BIC` score-downs) |
| Structured group | P=0.7937, R=0.8772 | unchanged: P=0.7937, R=0.8772, F1=0.8333 |

**Structured address & contact-line coverage
([ADR-0015](../adr/0015-structured-address-contact-line-recognizers.md)) — PII L7 baseline →
+`ADDRESS`/`CONTACT_LINE`/`CUSTOMER_LINE`, aggregate before/after on the same corpus:**

| Metric | Before PII L8 | After PII L8 (ADR-0015) |
| --- | --- | --- |
| `review-heavy` global | 118 TP / 147 FP / 91 FN, P=0.4453, R=0.5646, F1=0.4979 | 140 TP / 158 FP / 69 FN, P=0.4698, R=0.6699, F1=0.5523 |
| `insurance-at-de` global | 77 TP / 27 FP / 132 FN, P=0.7404, R=0.3684, F1=0.4920 | 99 TP / 38 FP / 110 FN, P=0.7226, R=0.4737, F1=0.5723 |
| `address_contact_types` group (new) | — (all 26 candidates were unsupported FNs in `other_types`) | 22 TP / 11 FP / 4 FN, P=0.6667, R=0.8462, F1=0.7458 |
| Per type | — | `ADDRESS` 18/10/3 (R=0.8571), `CONTACT_LINE` 3/1/1, `CUSTOMER_LINE` 1/0/0 |
| Unsupported types | 7 labels | 4: `BIRTH_DATE`, `BIRTH_PLACE`, `FAMILY_NAME`, `GIVEN_NAME` |

**Determinism:** two consecutive `make benchmark-private` runs per profile produced identical
reports (timestamps aside).

**What is missing next:**

1. **Human feedback capture (L10)** beyond the dev-only side-channel remains partial; **entity
   grouping (L11)** is delivered (with a review-decision overlay, see
   [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) and engine-level **overlap
   resolution (L12)** is now delivered as a consumer of the OCR Output Contract v1 boundary
   ([ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md)). The formal **Review L8
   `review_result`** artifact model is the next documented follow-up, then the **PII validation
   transparency report**.
2. The four remaining unsupported semantic labels (`BIRTH_DATE`, `BIRTH_PLACE`, `FAMILY_NAME`,
   `GIVEN_NAME`) and per-profile benchmark runs in one invocation.
3. Formalizing the review-decision overlay into the full `review_result` artifact model (L13) with
   actor/reason metadata (L11 on the Review ladder), scoped suppression rules (L12), and manual add
   (L14) so a human can confirm/reject/add against validation-surviving candidates with a durable,
   database-backed history.

See the [current sequence](roadmap.md#current-sequence) and
[later engine work](roadmap.md#later-engine-work) for the next steps.

---

## Legacy scale mapping (0–10 → 0–19)

The engine previously used a 0–10 ladder. Historical citations can be translated with this table.
The old ladder had a
coarser, differently ordered structure — the new scale reorders detection basics and splits the
former "production-grade" tail into readiness levels.

| Old (0–10) | Meaning | New (0–19) |
| --- | --- | --- |
| L1 Structured basics | structured recognizers | **L1** |
| L2 AT/DE pattern pack | AT/DE structured | **L4** |
| L3 Insurance/legal pack | domain identifiers | **L4** |
| L4 Entity profiles | named profiles | **L2** |
| L5 Candidate validation | subtractive filter | **L6** (+ **L7** context, **L8** address/contact) |
| L6 Entity resolution / overlap | overlap logic | **L11** grouping + **L12** overlap |
| L7 Human review actions | confirm/reject/add | **L13** + **L14** (feedback capture at **L10**) |
| L8 Feedback rules | suppression rules | Review L12 / regression **L15** |
| L9 Local AI plausibility | assistive model | (Review L17 / target-architecture AI chapter) |
| L10 Production-grade | production | **L19** (+ **L16–L18** policy/model/redaction-ready) |

New levels with no old equivalent: **L3** (explicit NER/model integration), **L5** (benchmark as a
gating level), **L9** (reproducible + dev engine settings).
