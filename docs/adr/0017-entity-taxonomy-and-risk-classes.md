# ADR-0017: Entity taxonomy and risk / protection classes

## Status

Accepted — 2026-07-02. Complements [ADR-0011](0011-engine-capability-model.md) (capability model) and
[ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 maturity scale). Docs-only.

## Context

The 0–19 maturity ladders (ADR-0016) say *how mature* each engine is, but not *what* the OCR/Text and
PII/Sensitive-Data engines should recognise or *how sensitive* each detected thing is. Coverage was
described implicitly through the entity types configured in
[`pii_profiles.py`](../../backend/app/services/pii_profiles.py) and scattered across the PII
levels and ADRs 0012/0014/0015. There was no single, professional model that answers: which business
categories exist, which entity types belong to them, what protection they need, which detection
strategy fits, what is implemented today, and how review/redaction should later treat them.

Without such a model, entity coverage tends to become a flat, unmaintainable list, sensitivity is
judged ad hoc, and future categories (medical, biometric, genetic, secrets) have no home in the
planning.

## Decision

- Add a **classification model** in [`docs/engine/entity-taxonomy.md`](../engine/entity-taxonomy.md)
  built on **four orthogonal axes**: business **category**, concrete **entity type**, **risk /
  protection class**, and **detection strategy** — plus an explicit **coverage** status
  (implemented / partial / planned / out of scope) that is the single source of truth for what is
  built.
- Define **19 business categories** (PERSON, CONTACT, ADDRESS, ORGANIZATION, FINANCE, GOVERNMENT_ID,
  LEGAL, MEDICAL, BIOMETRIC, GENETIC, EMPLOYMENT, EDUCATION, VEHICLE, DIGITAL_IDENTIFIER, DATE_TIME,
  BUSINESS_SECRET, CREDENTIAL_SECRET, TECHNICAL_SECRET, DOMAIN_SPECIFIC), each with typical entity
  types, a default risk class, a fitting detection strategy, current coverage, review obligation, and
  a later redaction idea.
- Define **risk / protection classes P0–P5**. P0–P4 follow a data-protection gradient (roughly GDPR,
  with P4 = Art. 9 special categories); **P5 is deliberately not GDPR-only** — it is Geheimschutz /
  secret protection (credentials, keys, trade secrets). Risk is a **default that escalates by
  context**: `effective_risk = max(default_risk, context_risk)`.
- Define a **detection-strategy vocabulary**: `structured_regex`, `checksum_validated`,
  `dictionary_gazetteer`, `ner_model`, `context_rule`, `layout_rule`, `domain_recognizer`,
  `secret_scanner`, `vision_ocr`, `human_feedback`, `hybrid`.
- Add a **tool ↔ strategy mapping** for OCR/Text (PyMuPDF, pdfplumber, OCRmyPDF, Tesseract,
  PaddleOCR, Docling, PP-Structure) and PII (Presidio, spaCy, regex/pattern recognizers, GLiNER,
  secret scanners, domain-specific recognizers, later local LLM/VLM), consistent with
  [`tool-strategy.md`](../engine/tool-strategy.md).

## Consequences

- Coverage, sensitivity, and detection approach are now explicit and reviewable; new entity types and
  categories have a defined home and land through their own PII/OCR-level PR that states the level it
  advances.
- **Docs-only, no behaviour change:** no recognizer, profile, setting, API, UI, benchmark, or
  dependency is added or changed. The taxonomy is a planning/classification model; the `Coverage`
  column separates model from implementation. Redaction/policy columns are targets for future engines
  (Redaction is still L0, detection-only).
- Privacy posture unchanged: no private data or `volumes/` content appears; only synthetic/aggregate
  material and repo entity-type names are referenced.
- Two design questions are recorded for later: whether P5 secret handling belongs *before* the
  `pii_result` (a `secret_scanner` pre-stage) rather than in the review flow, and how dual-category
  identifiers (`UID_AT`, `LICENSE_PLATE_AT`) are finally modelled.
