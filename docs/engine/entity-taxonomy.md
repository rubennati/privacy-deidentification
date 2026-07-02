# Entity Taxonomy & Risk / Protection Classes

This document is the **classification model** for what the OCR/Text and PII/Sensitive-Data engines
detect: the business categories, the concrete entity types, their default **risk / protection
class**, the **detection strategy** that fits them, how far the repository covers them **today**, and
the review and (later) redaction handling they imply.

It is the fachliche counterpart to the [0–19 maturity ladders](README.md#maturity-scale): the ladders
say *how mature* each engine is; this taxonomy says *what* it should recognise and *how sensitive*
each thing is. It is grounded in the entity types actually configured in
[`pii_profiles.py`](../../backend/app/services/pii_profiles.py) and the recognizers in
[`pii_recognizers.py`](../../backend/app/services/pii_recognizers.py).

## What this is and is not

- **It is a planning / classification model**, not an implementation. Listing an entity type or a
  strategy here does **not** mean it is implemented — the `Coverage` column is the single source of
  truth for that, and it points back to the [PII levels](pii-engine-levels.md) and
  [OCR levels](ocr-engine-levels.md).
- **It is detection-oriented, not redaction.** The pipeline is detection-only today
  ([Redaction L0](redaction-engine-levels.md)). The "later redaction policy" columns are *intended*
  behaviour for a future de-identification engine, recorded now so detection is built with it in
  mind — nothing here redacts.
- **It does not change behaviour.** No recognizer, profile, setting, API, UI, benchmark, or
  dependency is added or changed by this document. New entity types/strategies become real only
  through their own engine PR, which states the level it advances.
- **It is a living target.** Categories and coverage are expected to move as PII levels advance
  (feedback capture, grouping, overlap resolution, new recognizers).

## The four orthogonal axes

A single detected span is described by four **independent** axes. Keeping them separate is the whole
point of the taxonomy — confusing them is what produces flat, unmaintainable entity lists.

| Axis | Question | Examples | Where it lives |
| --- | --- | --- | --- |
| **Business category** | *What kind of thing is this?* | `FINANCE`, `GOVERNMENT_ID`, `MEDICAL` | this document |
| **Entity type** | *What concrete label does the engine emit?* | `IBAN_CODE`, `SVNR_AT`, `PERSON` | [`pii_profiles.py`](../../backend/app/services/pii_profiles.py), `pii_result` |
| **Risk / protection class** | *How sensitive / how much protection?* | `P0`…`P5` | this document ([below](#risk--protection-classes-p0p5)) |
| **Detection strategy** | *How is it found?* | `structured_regex`, `ner_model` | this document ([below](#detection-strategies)) |

Consequences of treating them as orthogonal:

- One entity type has **one** business category but may be reachable by **several** strategies
  (e.g. `ADDRESS` via `layout_rule` + `context_rule`; `PERSON` via `ner_model` + `human_feedback`).
- The **risk class is a default of the category/entity type but can escalate by context**. Rule:
  `effective_risk = max(default_risk, context_risk)`. A `CASE_NUMBER` is `P2` by default, but if its
  surrounding text is a medical or criminal matter, the *document* handling rises toward `P4`. The
  engine records the entity's default; policy/review decides the effective handling.
- Coverage is tracked per entity type, not per category — a category can be `partial` because some of
  its entity types are `implemented` and others are `planned`.

## Coverage status legend

| Status | Meaning |
| --- | --- |
| **implemented** | a recognizer/type is configured and emitted today (see `pii_profiles.py`) |
| **partial** | detectable but with known quality gaps, or only under a broad profile / dev gate |
| **planned** | on the roadmap; a named entity type or strategy but not yet built |
| **out of scope** | deliberately not pursued now (privacy, tooling, or product scope) |

## Risk / protection classes (P0–P5)

`P0–P5` express **protection need**, not detection difficulty. `P0–P4` follow a data-protection
gradient (roughly GDPR); **`P5` is deliberately not GDPR-only** — it is Geheimschutz / secret
protection (credentials, keys, trade secrets) whose exposure is a security incident regardless of
personal reference.

| Class | Meaning | Typical examples | Default review | Default later redaction policy |
| --- | --- | --- | --- | --- |
| **P0** | public / non-critical | public company name, generic date, published URL | none | keep |
| **P1** | personal reference possible (quasi-identifier) | first name alone, city, IP-as-context, plain date | optional | optional mask |
| **P2** | clearly personal data | full name, e-mail, phone, home address, customer/case number | standard (confirm/reject) | mask or pseudonymise |
| **P3** | high-impact / critical identifiers | IBAN, credit card, passport, national ID, social-security number | mandatory | mask, prefer irreversible |
| **P4** | special categories (GDPR Art. 9) or comparably sensitive | health/medical, biometric, genetic, union/religion/sexuality | mandatory + special handling | mask, irreversible, minimise even in review |
| **P5** | critical secrets / Geheimschutz | passwords, API keys, private keys, access tokens, trade secrets | mandatory + never persist in artifacts/logs | block/redact at ingestion; treat exposure as a leak |

Notes:

- **P5 is a different axis of harm.** A leaked API key is not "personal data" but is more damaging
  than most P2 items. P5 items should ideally never reach a stored `pii_result`/text artifact in the
  clear; the correct handling is closer to secret-scanning + suppression than to human review.
- The **review** and **redaction** columns are *defaults*; a policy/profile (Review L15) can raise
  them. They are targets for later engines, not current behaviour.

## Detection strategies

The strategy is *how* an entity is found. Most real detection is **hybrid** (a regex candidate
confirmed by a context anchor and pruned by candidate validation).

| Strategy | What it is | Strengths | Limits | Used today |
| --- | --- | --- | --- | --- |
| `structured_regex` | pattern match on a well-formed shape | precise on formatted ids; cheap; language-agnostic | misses free-text; format drift | **yes** — EMAIL/PHONE/IP/URL + AT/DE patterns |
| `checksum_validated` | regex + checksum/mod check | very high precision (rejects typos) | only where a checksum exists | **yes (indirect)** — IBAN (mod-97) / credit card (Luhn) via Presidio |
| `dictionary_gazetteer` | match against a term/deny list | good for closed sets (titles, legal forms) | list upkeep; ambiguity | **partial** — small stopword/company-form/title lists in validation |
| `ner_model` | statistical NER (spaCy) | free-text names/orgs/places | over-tags at fixed score; language-bound | **yes (opt-in)** — PERSON/ORGANIZATION/LOCATION, DATE_TIME |
| `context_rule` | require nearby anchor words | lifts precision of weak patterns | anchor coverage; word order | **yes** — domain-id and BIC context anchors |
| `layout_rule` | use line/position/structure | multi-token addresses, header/address blocks | needs layout signal | **yes** — ADDRESS/CONTACT_LINE + context hardening |
| `domain_recognizer` | domain-specific pattern+anchor pack | insurance/legal identifiers others miss | domain-specific upkeep | **yes** — `insurance-at-de` pack |
| `secret_scanner` | entropy/format scanners for secrets | catches keys/tokens/credentials | FP on random-looking ids; not personal-data aware | **no** — planned (P5) |
| `vision_ocr` | recover text from image/scan first | reaches entities only present as pixels | OCR errors propagate | **yes (upstream)** — OCR feeds canonical text |
| `human_feedback` | reviewer verdict as signal | corrects machine errors; captures misses | manual; not a detector | **partial** — dev-only feedback capture ([Review L5](review-feedback-levels.md)) |
| `hybrid` | combine the above | best precision/recall trade-off | orchestration complexity | **yes** — detection → candidate validation |

## Category catalogue

19 business categories. Each lists its typical entity types, the **default** risk class, the fitting
detection strategy, current coverage, the typical review obligation, and a later redaction idea.
Entity types in `code` that exist today match [`pii_profiles.py`](../../backend/app/services/pii_profiles.py);
others are named candidates.

> **Overlap note.** Some identifiers legitimately touch two categories (a `UID_AT` is both an
> `ORGANIZATION` identifier and a `GOVERNMENT_ID`; `LICENSE_PLATE_AT` is `VEHICLE` and quasi-personal).
> Each entity type has **one primary category** here; cross-links are noted. Resolving competing
> *spans* at detection time is [PII L12 overlap resolution](pii-engine-levels.md), a separate concern.

### PERSON

- **Entity types:** `PERSON` (impl.), `GIVEN_NAME` (planned), `FAMILY_NAME` (planned), title/honorific
  (as context, not a stored type).
- **Default risk:** P2 (a bare `GIVEN_NAME` alone → P1).
- **Detection strategy:** `ner_model` + `context_rule` (title/role anchors) + `human_feedback`.
- **Coverage:** **partial** — `PERSON` implemented via spaCy NER (opt-in, `broad-review`/`review-heavy`),
  hardened by candidate validation; `GIVEN_NAME`/`FAMILY_NAME` are benchmark labels not yet emitted.
- **Review:** standard (names are the archetypal review candidate; NER FPs are frequent).
- **Later redaction:** pseudonymise consistently (`PERSON_1`) so text stays readable.

### CONTACT

- **Entity types:** `EMAIL_ADDRESS` (impl.), `PHONE_NUMBER` (impl.), `CONTACT_LINE` (impl.), fax
  (as PHONE), messaging handle (planned).
- **Default risk:** P2.
- **Detection strategy:** `structured_regex` + `context_rule`; `CONTACT_LINE` via `layout_rule`.
- **Coverage:** **implemented** — with known AT/DE phone recall gaps tracked at the PII levels.
- **Review:** standard.
- **Later redaction:** mask; keep type label for context.

### ADDRESS

- **Entity types:** `ADDRESS` (impl.), `CUSTOMER_LINE` (impl.), `LOCATION` (impl., NER),
  `BIRTH_PLACE` (planned), postal code (as part of ADDRESS).
- **Default risk:** P2 (a precise residential address trends P3; a bare city `LOCATION` → P1).
- **Detection strategy:** `layout_rule` (street shape, labelled lines) + `context_rule` (PLZ/Ort);
  `LOCATION` via `ner_model`.
- **Coverage:** **implemented** for `ADDRESS`/`CONTACT_LINE`/`CUSTOMER_LINE`
  ([ADR-0015](../adr/0015-structured-address-contact-line-recognizers.md)); `LOCATION` partial (NER
  over-tags, validation prunes); `BIRTH_PLACE` planned.
- **Review:** standard; ADDRESS vs LOCATION overlap is a known [L12] resolution case.
- **Later redaction:** mask; optionally coarsen (city only) instead of full removal.

### ORGANIZATION

- **Entity types:** `ORGANIZATION` (impl., NER), `UID_AT` (impl., ↔ GOVERNMENT_ID),
  `FN_AT` (impl., Firmenbuchnummer), company-form suffix (context).
- **Default risk:** P1 (public org names) → P2 for org-bound identifiers (`UID_AT`/`FN_AT`).
- **Detection strategy:** `ner_model` for the name; `structured_regex` + `context_rule` for
  `UID_AT`/`FN_AT`; `dictionary_gazetteer` for legal-form suffixes.
- **Coverage:** **implemented** (`ORGANIZATION` opt-in; `UID_AT`/`FN_AT` in `insurance-at-de`).
- **Review:** optional for names, standard for identifiers.
- **Later redaction:** usually keep public org names; mask org-bound identifiers.

### FINANCE

- **Entity types:** `IBAN_CODE` (impl.), `CREDIT_CARD` (impl.), `BIC` (impl.), account number
  (planned).
- **Default risk:** P3.
- **Detection strategy:** `checksum_validated` (IBAN mod-97, credit card Luhn) + `context_rule`
  (`BIC` needs a financial anchor).
- **Coverage:** **implemented**.
- **Review:** mandatory.
- **Later redaction:** mask; prefer irreversible (financial-fraud impact).

### GOVERNMENT_ID

- **Entity types:** `SVNR_AT` (impl., social security), `TAX_ID_AT` (impl.), `PASSPORT_NUMBER` (impl.),
  `ID_CARD_NUMBER` (impl.), `UID_AT` (impl., ↔ ORGANIZATION), national-ID variants (planned).
- **Default risk:** P3 (`SVNR_AT` can encode a birth date → treat as strong identifier).
- **Detection strategy:** `structured_regex` (+ check digit where defined) + `context_rule`.
- **Coverage:** **implemented** for the AT set; other jurisdictions planned.
- **Review:** mandatory.
- **Later redaction:** mask, irreversible.

### LEGAL

- **Entity types:** `CASE_NUMBER` (impl.), `FILE_REFERENCE` (impl.), `REPORT_NUMBER` (impl.),
  `ASSESSMENT_NUMBER` (impl.), court/register reference (planned).
- **Default risk:** P2 (content can escalate the *document* to P4: criminal/health matters).
- **Detection strategy:** `domain_recognizer` (`context_rule`-heavy — generic ids need an adjacent
  label).
- **Coverage:** **implemented** (part of the `insurance-at-de` domain pack).
- **Review:** standard; flag for context escalation.
- **Later redaction:** mask the identifier; document-level policy may raise handling.

### MEDICAL

- **Entity types:** diagnosis / ICD code / medication / health status (all planned), insurance-medical
  references (partially reachable via LEGAL/DOMAIN ids).
- **Default risk:** P4 (GDPR Art. 9).
- **Detection strategy:** `dictionary_gazetteer` + `ner_model` + `context_rule`; strong
  `human_feedback` reliance.
- **Coverage:** **planned / out of scope now** — no medical recognizers today.
- **Review:** mandatory + special handling.
- **Later redaction:** mask, irreversible; minimise exposure even during review.

### BIOMETRIC

- **Entity types:** fingerprint/face/voice references or templates (planned).
- **Default risk:** P4.
- **Detection strategy:** `domain_recognizer` / `vision_ocr` for embedded biometric artefacts.
- **Coverage:** **out of scope now**.
- **Review:** mandatory + special handling.
- **Later redaction:** remove; irreversible.

### GENETIC

- **Entity types:** genetic-test / DNA-sequence references (planned).
- **Default risk:** P4.
- **Detection strategy:** `dictionary_gazetteer` + `context_rule`.
- **Coverage:** **out of scope now**.
- **Review:** mandatory + special handling.
- **Later redaction:** remove; irreversible.

### EMPLOYMENT

- **Entity types:** employee id (planned; today a generic `USER_ID`/`CUSTOMER_NUMBER` may cover it),
  salary/role/HR references (planned).
- **Default risk:** P2 (P4 if it reveals union membership/health).
- **Detection strategy:** `domain_recognizer` + `context_rule`.
- **Coverage:** **planned** (only indirectly via generic identifiers today).
- **Review:** standard.
- **Later redaction:** mask; pseudonymise ids.

### EDUCATION

- **Entity types:** student id, grade/qualification references (planned).
- **Default risk:** P2.
- **Detection strategy:** `domain_recognizer` + `context_rule`.
- **Coverage:** **out of scope now**.
- **Review:** standard.
- **Later redaction:** mask.

### VEHICLE

- **Entity types:** `LICENSE_PLATE_AT` (impl., ↔ PERSON quasi-identifier), VIN (planned).
- **Default risk:** P2 (a plate is a strong quasi-identifier → can trend P3).
- **Detection strategy:** `structured_regex` + `context_rule` (Kennzeichen anchor).
- **Coverage:** **implemented** for `LICENSE_PLATE_AT`; VIN planned.
- **Review:** standard.
- **Later redaction:** mask.

### DIGITAL_IDENTIFIER

- **Entity types:** `IP_ADDRESS` (impl.), `URL` (impl.), `USER_ID` (impl.), `TRANSACTION_ID` (impl.),
  `PROJECT_ID` (impl.), MAC/device id (planned), cookie/session id (planned).
- **Default risk:** P2 (`IP_ADDRESS` is personal data under GDPR); a public `URL` → P0/P1.
- **Detection strategy:** `structured_regex` + `context_rule`; EMAIL-vs-URL overlap handled at
  detection.
- **Coverage:** **implemented** for the listed ids.
- **Review:** standard (optional for public URLs).
- **Later redaction:** mask personal/device ids; keep public URLs unless policy says otherwise.

### DATE_TIME

- **Entity types:** `DATE_TIME` (impl., lower-confidence NER), `BIRTH_DATE` (planned).
- **Default risk:** P1 (a plain date) → P2 as a `BIRTH_DATE` / quasi-identifier.
- **Detection strategy:** `ner_model` + `context_rule` (role disambiguation: birth vs invoice vs
  claim date).
- **Coverage:** **partial** — `DATE_TIME` opt-in and noisy; `BIRTH_DATE` role not yet emitted.
- **Review:** optional → standard for birth dates.
- **Later redaction:** generalise (year only) rather than full removal where possible.

### BUSINESS_SECRET

- **Entity types:** trade-secret / internal-pricing / non-public-strategy references (planned).
- **Default risk:** P5 (Geschäftsgeheimnis; protection need independent of personal reference).
- **Detection strategy:** `domain_recognizer` + `human_feedback` (hard to pattern-match reliably).
- **Coverage:** **out of scope now**.
- **Review:** mandatory; keep out of shared artifacts.
- **Later redaction:** block/redact; treat exposure as an incident.

### CREDENTIAL_SECRET

- **Entity types:** password, API key, access/refresh token, secret bearer string (planned).
- **Default risk:** P5.
- **Detection strategy:** `secret_scanner` (entropy/format) + `structured_regex`.
- **Coverage:** **out of scope now** — no secret scanner integrated (see non-scope).
- **Review:** mandatory; must never persist in the clear.
- **Later redaction:** redact at ingestion; do not store; treat as leak.

### TECHNICAL_SECRET

- **Entity types:** private key, certificate, connection string, internal endpoint/credential
  (planned).
- **Default risk:** P5.
- **Detection strategy:** `secret_scanner` + `structured_regex` (PEM headers, DSNs).
- **Coverage:** **out of scope now**.
- **Review:** mandatory; must never persist in the clear.
- **Later redaction:** redact at ingestion; treat as leak.

### DOMAIN_SPECIFIC

- **Entity types:** `POLICY_NUMBER` (impl.), `CLAIM_NUMBER` (impl.), `CONTRACT_NUMBER` (impl.),
  `OFFER_NUMBER` (impl.), `INVOICE_NUMBER` (impl.), `CUSTOMER_NUMBER` (impl.), other vertical ids
  (planned).
- **Default risk:** P2 (identifiers that link to a person's file / transaction; a strong direct id
  can trend P3).
- **Detection strategy:** `domain_recognizer` (`structured_regex` + `context_rule` anchors like
  "Polizzennr.", "Schadennr.").
- **Coverage:** **implemented** — the core `insurance-at-de` value; verticals beyond insurance are
  planned.
- **Review:** standard.
- **Later redaction:** mask/pseudonymise the identifier.

## Tool / strategy mapping

Which tools realise the strategies above, per engine. Timing (`now` / `later` / `optional`) matches
[`tool-strategy.md`](tool-strategy.md); this table adds the taxonomy angle (what each tool covers).
Listing a tool is **not** a commitment to adopt it — `later`/`optional` tools need their own PR and
dependency review.

### OCR / Text

| Tool | Covers (strategy) | Strengths | Weaknesses | When |
| --- | --- | --- | --- | --- |
| **PaddleOCR** | `vision_ocr` (detection + recognition) | local CPU OCR, Latin/German recognizer | heavy image; CPU speed; ARM caveat | **now** (core OCR engine) |
| **PyMuPDF** | `layout_rule` (block/line geometry), later redaction primitives | fast geometry + coordinates | AGPL licensing to review; adds a dep | **later** (OCR L9–L10, redaction) |
| **pdfplumber** | `layout_rule` (tables/words with coordinates) | precise text/word boxes on native PDFs | PDF-only; not for scans | **optional** (layout/table candidate) |
| **OCRmyPDF** | `vision_ocr` (Tesseract pipeline, sidecar text) | mature, adds a text layer to scans | another heavy runtime | **optional** (benchmark spike vs PaddleOCR) |
| **Tesseract** | `vision_ocr` | ubiquitous OCR baseline | weaker on complex layouts | **optional** (benchmark spike) |
| **Docling** | `layout_rule` + document structure | modern structure/table extraction | new, heavy; maturity to assess | **later** (OCR L9–L11 spike) |
| **PP-Structure** | `layout_rule` + table structure | layout + table recovery | Paddle-ecosystem weight | **later** (OCR L9–L11 spike) |

### PII / Sensitive-Data

| Tool | Covers (strategy) | Strengths | Weaknesses | When |
| --- | --- | --- | --- | --- |
| **Presidio (Analyzer)** | `structured_regex`, `checksum_validated`, `context_rule`, orchestration | proven PII framework; checksum recognizers; adapter-friendly | English-leaning defaults; needs tuning | **now** (core) |
| **spaCy (`de_core_news_sm`)** | `ner_model` | free-text PERSON/ORG/LOCATION | small model over-tags at fixed score | **now** (opt-in NER) |
| **Regex / Pattern recognizers** | `structured_regex`, `domain_recognizer` | precise AT/DE + domain ids; no heavy dep | format drift; upkeep | **now** (core; `insurance-at-de`) |
| **Domain-specific recognizers** | `domain_recognizer`, `layout_rule` | insurance/legal/address coverage others miss | domain upkeep; anchor coverage | **now** (ADR-0012/0014/0015) |
| **GLiNER** | `ner_model` (flexible/zero-shot entities) | recall on types Presidio patterns miss | model weight; still needs validation | **later** (PII L-range NER option) |
| **Secret scanners** | `secret_scanner` | catches P5 credentials/keys/tokens | FP on random ids; not personal-data aware | **later** (CREDENTIAL/TECHNICAL_SECRET) |
| **Local LLM / VLM** | `hybrid` plausibility, `vision_ocr` assist | contextual plausibility on hard cases | large/slow; must stay local + assistive | **optional** (guarded; OCR/PII/Review AI chapters) |

## Relationship to the maturity ladders

The taxonomy and the [0–19 ladders](README.md#maturity-scale) are complementary:

- New **entity types / categories** land through PII levels — e.g. broader coverage sits around
  [PII L4/L8](pii-engine-levels.md); NER-flexible recall (GLiNER) is a later NER option; the
  MEDICAL/BIOMETRIC/GENETIC (P4) and the SECRET (P5) categories are **new detection capabilities**,
  each its own future PR.
- **Risk classes** feed review policy ([Review L15 policy-based review](review-feedback-levels.md))
  and the later [Redaction policy](redaction-engine-levels.md) — the "later redaction policy" columns
  above are Redaction-engine targets, not current behaviour.
- **Detection strategies** map to the [tool strategy](tool-strategy.md); which strategy is active for
  a run is shaped by [engine settings](engine-settings.md) (profile, score threshold, candidate
  validation).
- **`human_feedback`** as a strategy is the bridge to [Review/Feedback](review-feedback-levels.md):
  the dev-only feedback capture is the first, partial realisation.

## Open questions / non-scope

- **Non-scope (explicit):** this PR implements **no** recognizer, changes **no** profile/UI/feedback
  API/benchmark logic, integrates **no** secret scanner, and implements **no** redaction. It is
  classification only.
- **Category vs entity-type home for dual-use ids** (`UID_AT`, `LICENSE_PLATE_AT`) is a modelling
  choice; each has one primary category here with a cross-link. Revisit if a policy needs a strict
  1:1 mapping.
- **P5 handling belongs partly outside the PII review flow.** Credentials/keys should ideally be
  caught and suppressed *before* a `pii_result` stores them; whether that is a `secret_scanner`
  pre-stage or a detection type is an open design question for a future PR.
- **Risk-class escalation** (`effective_risk = max(default, context)`) is stated as a model rule but
  is not computed anywhere yet; it becomes real with policy-based review / redaction.
- **Jurisdiction beyond AT/DE** (other national IDs, tax ids, plates) is planned, not modelled in
  detail here.

## References

- [`README.md`](README.md) — engine capability model + 0–19 maturity scale
- [`pii-engine-levels.md`](pii-engine-levels.md) — PII 0–19 ladder (where new types/strategies land)
- [`ocr-engine-levels.md`](ocr-engine-levels.md) — OCR 0–19 ladder (`vision_ocr`, geometry, tables)
- [`tool-strategy.md`](tool-strategy.md) — core/spike/deferred tool decisions
- [`engine-settings.md`](engine-settings.md) — settings that shape which strategy runs
- [`review-feedback-levels.md`](review-feedback-levels.md) — review obligation / `human_feedback`
- [`redaction-engine-levels.md`](redaction-engine-levels.md) — later redaction/policy behaviour
- ADRs: [0012](../adr/0012-insurance-at-de-pii-recognizers.md) (AT/DE + domain pack),
  [0013](../adr/0013-pii-candidate-validation.md) (candidate validation),
  [0014](../adr/0014-pii-candidate-validation-context-hardening.md) (context hardening),
  [0015](../adr/0015-structured-address-contact-line-recognizers.md) (address/contact-line),
  [0017](../adr/0017-entity-taxonomy-and-risk-classes.md) (this taxonomy)
