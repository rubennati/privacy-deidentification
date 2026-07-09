# ADR-0029: PII Review-Ready Entity Contract v1

## Status

Accepted / implemented additively — 2026-07-09. On top of the PII intake adapter + overlap
resolution ([ADR-0028](0028-pii-intake-document-text-package-v1.md)), PII now exposes a derived,
review-facing **entity contract** (`PiiEntityContractV1` / `ReviewReadyPiiEntity`) that connects
every detected entity to both the technical raw text and the canonical reading text with an
explicit mapping status, a stable entity id, deterministic overlap provenance, the resolved review
state, and a text-free display model. It adds `backend/app/services/pii_entity_contract.py` (the
builder), additive schema models, and one additive route
(`GET /api/documents/{document_id}/pii/entity-contract`). It is **not** pseudonymization, redaction,
reconstruction/export, or the formal binding `review_result` artifact — those remain out of scope.

This builds on [ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 scale),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md) (technical-raw vs
canonical-reading contract), [ADR-0021](0021-pii-entity-grouping-and-review-decisions.md) (entity
grouping + review-decision overlay), [ADR-0027](0027-ocr-output-contract-v1-strategy.md) (the
Document Text Package), and [ADR-0028](0028-pii-intake-document-text-package-v1.md) (PII intake +
overlap resolution).

## Position in the sequence

Like [ADR-0027](0027-ocr-output-contract-v1-strategy.md) for OCR, this is a **cross-cutting
stabilization milestone, not a numbered level**: it does not bump PII beyond L12 or complete the
formal **Review L8/L13 `review_result`** model (still open). It stabilizes how the L12-resolved
entity set is *presented for review* — recognition quality, stable display, raw/canonical mapping,
reviewability, and provenance — as the foundation the future binding `review_result` model consumes.

## Context

After [ADR-0028](0028-pii-intake-document-text-package-v1.md), the immutable `pii_result` already
carries raw offsets, an optional reading-text projection (`projection_status`/`projection_method` +
reading offsets), and per-entity overlap `provenance`. But nothing packaged that into a single,
stable, review-ready shape: the raw↔canonical connection was implicit, there was no explicit
per-entity *mapping status* (a reviewer could not tell "unmapped" from "ambiguous" from "no
canonical text at all"), the artifact's `PiiEntity.id` is a volatile per-run UUID (unstable across
re-runs), and there was no text-free display model telling a UI which layer to highlight in.

## Decision

### 1. A pure, derived, additive review-ready contract

`build_pii_entity_contract(settings, document_id)` reads the latest immutable `pii_result` (and,
where available, the matching text artifact's canonical reading text) and derives a
`PiiEntityContractV1`. It is a pure view — like `pii_grouping.py` and `pii_review_service.py`: it
never mutates the artifact, adds no detection, and re-uses the existing review-decision overlay
(`get_pii_review_result`) for review state. Existing `GET …/pii` and `GET …/pii/review` responses
are byte-for-byte unchanged; the frontend never has to call the text-package endpoint itself.

### 2. Explicit raw↔canonical mapping status

Each `ReviewReadyPiiEntity` carries a `raw_text_range` (always) and a `canonical_reading_text_range`
(only when mapped), plus an explicit `mapping_status`:

- `exact` — offset-map projection; `projected` — value re-match projection (both carry a canonical
  range);
- `partial` — the projection was partial; `missing` — canonical text exists but this entity did not
  map; `ambiguous` — unmapped and the exact value occurs more than once in the canonical text;
- `not_applicable` — the run produced no canonical reading text at all (a degraded package).

**A missing/partial/ambiguous canonical mapping never drops an entity** — it stays fully reviewable
and is flagged (`needs_review`) with reason codes. `not_applicable` is deliberately *not* flagged,
so a document with no reading text does not mark every entity for review.

### 3. Stable entity id

`entity_id` is a deterministic 32-hex hash of `document_id`, `entity_type`, and the raw span — the
same for the same document + span + type across re-runs — while the volatile per-occurrence
`PiiEntity.id` is preserved as `source_entity_id` (the key the review overlay and feedback use).
Exact same-span/same-type duplicates are already merged upstream by overlap resolution, so the key
is unique within one resolved set.

### 4. Text-free display model + provenance passthrough

`display` gives a UI everything it needs to render consistently using *ranges only* — a preferred
text source, raw and (optional) canonical highlight ranges, an entity-type `display_label`,
`display_context_available`, `needs_review`, and `review_reason_codes` — never a surrounding text
snippet. Overlap `provenance` and the run's `input_contract`/`overlap_resolution` summaries are
passed through unchanged. The entity's own `value` (identical to `PiiEntity.text`, already returned
by `GET …/pii`) appears only on the entity, never inside display, warnings, or provenance.

## Policy (unchanged from ADR-0027/0028)

- Technical raw text stays the **primary and only active detection source**; canonical reading text
  is display/context/projection only, and the `text_lineage_map` separation gate is not bypassed.
- `structured_content` remains a hint layer; quality/noise evidence remains trust context.
- Overlaps are resolved or flagged deterministically upstream (ADR-0028); this contract only
  *surfaces* that outcome.

## Explicitly not included

- No pseudonymization, redaction, reconstruction/export, replacement placeholders, or correction
  suggestions.
- No change to detection, recognizers, candidate validation, overlap resolution, the
  `DocumentTextPackageV1` schema, OCR extraction, runtime/worker behavior, or benchmark payloads.
- **Not** the formal binding `review_result` artifact (Review L8/L13) — this is a derived read model,
  not a persisted single-artifact-per-run decision record.
- No broad new frontend UI; only additive TypeScript types + a fetch helper were added.

## Consequences

- Consumers (Review UI, and later pseudonymization/analysis/export) get one stable, review-ready
  entity shape with an explicit raw↔canonical mapping status and stable ids, instead of re-deriving
  it from `pii_result` internals.
- Backward compatibility holds: the immutable artifact and existing routes are unchanged; the
  contract is a separate additive endpoint; legacy artifacts (no provenance/projection) still yield
  a valid contract (`detection_source` defaults to `raw_text`, mapping falls back safely).
- The formal `review_result` model can now be built on top of a stable review-ready contract.
