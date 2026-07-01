# ADR-0012: Insurance AT/DE PII recognizers and named coverage profiles

## Status

Accepted — 2026-07-01

## Context

The private candidate benchmark showed a precision-first structured baseline with low AT/DE recall,
zero domain-sensitive coverage, and very noisy broad German spaCy NER. Insurance, legal, invoice,
offer, assessment, and contract documents contain sensitive identifiers that Presidio's predefined
German registry does not model. Enabling broad NER by default would not solve those structured gaps
and would materially increase false positives.

## Decision

- Keep Presidio Analyzer as the detection tool behind the existing lazy adapter and register a local
  `insurance-at-de` pack of Presidio `PatternRecognizer` instances. Pattern specifications remain
  dependency-free and are materialized only when the optional PII runtime loads.
- Reuse Presidio entity names for `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, and `URL`; use explicit
  AT/domain types for identifiers Presidio does not define.
- Treat regional identifiers and insurance/legal/business document metadata as
  `domain_sensitive_types`, distinct from `structured_types` and opt-in `ner_types`. Domain-sensitive
  metadata is protected even where it is not classical personal data.
- Detect format-strong identifiers directly. Generic domain values, SVNR, tax IDs, licence plates,
  and identity-document numbers require an immediately adjacent synthetic/tested label pattern; the
  match span contains only the value. This prevents nearby labels from boosting unrelated numbers.
- Add `PII_PROFILE` with `structured-only` (default), `insurance-at-de`, `broad-review`, and
  `review-heavy`. `PII_ENTITY_TYPES` remains an explicit compatibility override; artifacts record
  `custom` when the override differs from the selected profile.
- Keep `PERSON`, `ORGANIZATION`, `LOCATION`, and `DATE_TIME` opt-in. Do not add candidate validation,
  suppression, review feedback, UI, OCR, database, redaction, cloud services, models, or dependencies.

## Consequences

- PII L2/L3 structured/domain coverage improves without activating broad NER or changing the
  precision-first default.
- New `pii_result` artifacts record the effective profile and exact configured entity types. Older
  artifacts remain readable through the schema's `custom` default.
- Context patterns are deliberately conservative: identifiers without a known label or strong
  prefix can remain false negatives. Address/contact-line detection and seven benchmark semantic
  labels remain unsupported.
- Candidate validation is still required in the next PR. Current patterns can produce false
  positives for format-strong values; no post-processing silently removes or re-scores candidates.
- A private `review-heavy` before/after run materially improved global and domain-sensitive recall;
  only aggregate metrics are documented, while reports and source data remain under `volumes/`.
