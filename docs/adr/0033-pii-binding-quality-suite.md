# ADR-0033: PII binding quality suite (Phase 2)

## Status

Accepted — 2026-07-10. Builds on [ADR-0031](0031-text-identity-anchor-lineage-architecture.md) and
follows [ADR-0032](0032-reading-text-row-construction-lineage-v1.md) (**Reading-text row
construction lineage v1, Phase 1**), which merged first as planned, so no numbering collision
occurred. Delivers Phase 2 of the sequence recommended in
[`text-anchor-architecture-feasibility-audit.md`](../engine/text-anchor-architecture-feasibility-audit.md#phase-2--pii-binding-quality-suite).

## Context

The audit's Phase 2 goal: "a synthetic hard-case regression corpus + metrics gate for binding/
coverage quality: mixed-uniqueness entities, adjacent same-line dates/phones/ids (tokenizer
fusion), punctuation-swallowing recognizer spans (partial binding), header/footer repeats, table
columns, DOCX/no-geometry documents; plus a documented builder-version identity-drift test and the
frontend contract-fetch-failure notice." Mixed-uniqueness entities and header/footer repeats were
already covered by `test_anchor_bound_pii_e2e_conformance.py`; the remaining named cases were not.

While scoping the tokenizer-fusion case, this work found a real, previously untested edge case:
`document_text_anchors.py`'s phone pattern (`\+?\d[\d \t()./\-]{5,}\d`) fuses a date and a directly
adjacent phone number (e.g. `"14.03.1978 0664 1234567"`, no separating label) into one raw anchor,
because the middle character class accepts plain spaces. This is not a hypothetical — it is exactly
the class of tokenizer risk the audit named. Per the "Do not" guardrail for this phase ("tune
recognizers, add detection features"), the tokenizer itself is intentionally **not** changed here;
instead the binding layer's existing honest-degradation behavior (partial, not exact, when a
detection doesn't align to a whole anchor) is verified and regression-locked.

## Decision

- **New coverage-ratio metrics on `PiiAnchorBindingSummary`**: `anchor_bound_ratio` (exact + partial
  bindings ÷ total) and `exact_bound_ratio` (exact ÷ total), `0.0` when there are no entities.
  Additive fields, computed in both existing summary builders
  (`pii_anchor_binding.py`, `pii_entity_contract.py`) from the counts already present; a new
  model-validator cross-check keeps them in sync with those counts, mirroring the schema's existing
  count-consistency validators. No detection/binding logic changes — metrics only.
- **`backend/tests/test_pii_binding_quality_suite.py`**, a new synthetic regression corpus (no
  private data) covering the four previously-untested hard cases:
  - Adjacent same-line date+phone tokenizer fusion (the real gap above) — regression-locks that both
    entities still bind (`partial`, never lost, never silently `exact`, never merged into one
    identity), plus a positive control proving the same values *with* a label between them bind
    `exact` as normal.
  - A punctuation/character-swallowing recognizer span (a leading `+` trimmed from a phone
    detection by a validator quirk) — binds `partial`, never a false `exact`.
  - Table-column canonical-range cross-contamination — two table cells that swap order between raw
    and reading-text order must each resolve their own canonical range, never the other cell's.
  - A DOCX/no-geometry document (`pages=[]`, no `text_geometry`) — binds identically to a paginated
    document, regression-locking that this module stays geometry-agnostic.
  - A coverage-ratio gate asserting a documented `anchor_bound_ratio` floor per fixture class.
- **Builder-version identity-drift test**: verifies the audit's stated safety property directly —
  binding the same `PiiEntity` occurrences against two anchor graphs that differ only in their
  minted anchor ids (simulating a builder-version bump over unchanged raw text) yields a different
  anchor-derived `entity_id`, while the underlying `PiiEntity.id` that durable review decisions
  (`pii_review_service.py`) actually key on is completely unaffected. A companion guard test asserts
  neither `pii_review_service.py` nor `feedback_service.py` (the two durable JSONL-writing modules)
  contains the strings `anchor_id`/`entity_id` at all, so a future change that starts persisting
  either must be a conscious, reviewed decision.
- **Frontend contract-fetch-failure notice**: `fetchPiiEntityContract` now returns a discriminated
  `{ status: "ok", contract } | { status: "not_found" } | { status: "error" }` instead of
  `T | null`, so a genuine failure (network error, unexpected 5xx) is distinguishable from the
  normal, expected `404` ("no PII result yet" — never shown as an error). `DocumentDetailPage.tsx`
  tracks the failure in a new `piiEntityContractError` state and shows a `StatusNotice` ("PII
  highlights could not be loaded; the recognized text is still visible without highlights") when a
  current PII run exists but its contract failed to load — previously this was silently
  indistinguishable from "no entities."

## Consequences

- No recognizer, detection, tokenizer, active-PII-input, `pii_result` schema, review-decision, or
  binding-algorithm change. The date+phone fusion case is documented and regression-locked, not
  fixed — fixing the tokenizer pattern is explicitly out of scope for this phase (see the audit's
  "Do not" guardrail) and remains open future work if warranted.
- `PiiAnchorBindingSummary` gains two additive float fields; both existing Python builders and the
  frontend TS interface were updated together, and existing fixtures across
  `test_pii_anchor_binding.py`, `test_anchor_bound_pii_e2e_conformance.py`,
  `piiHighlights.test.ts`, and `piiEntityContract.test.ts` needed no changes beyond adding the two
  new fields to hand-built summary literals (all already-computed values, no behavior change).
- `fetchPiiEntityContract`'s return type is a genuine breaking change to its two call sites, both
  inside this PR (`DocumentDetailPage.tsx`); no other frontend module called it.
- Fixtures express invariants and coverage floors, not exact segment layouts, so they are not
  over-fit to today's heuristics.

## Next

The remaining recommended branch from the feasibility audit is **`review-result-v1`** (Phase 3,
Review L8): a single durable artifact per PII run replacing today's JSONL decision overlay, with an
explicit stale-decision flag.
