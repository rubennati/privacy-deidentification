# ADR-0039: Review Result v1 — unified stable entity entries

## Status

Accepted — 2026-07-11. Builds on [ADR-0021](0021-pii-entity-grouping-and-review-decisions.md)
(review-decision overlay), [ADR-0029](0029-pii-review-ready-entity-contract.md)/
[ADR-0031](0031-text-identity-anchor-lineage-architecture.md) (anchor-bound entity contract),
[ADR-0033](0033-pii-binding-quality-suite.md) (occurrence-id-primary keying / anchor-id-drift
guardrail), [ADR-0034](0034-review-l8-review-result-artifact.md) (`review_result` artifact), and
[ADR-0035](0035-pii-l14-review-l10-manual-add-scope.md) (manual additions). Named as the
`review-result-v1` branch in
[`text-anchor-architecture-feasibility-audit.md`](../engine/text-anchor-architecture-feasibility-audit.md#phase-3--review-result-v1-review-l8).

## Context

ADR-0034 delivered an immutable, occurrence-id-primary `PiiReviewResultArtifact`, and ADR-0035
layered manual additions onto the same decision log as a parallel `manual_additions` list —
deliberately *not* merged into `occurrences`/`groups` or the anchor-bound entity contract, since
both structurally assume a detector origin. Both PRs explicitly named what they left open:

- ADR-0034: "The audit's goal text also names an anchor-derived `entity_id` as *secondary*
  linkage; this PR does not add it … left open for a future PR if a consumer actually needs the
  secondary linkage."
- ADR-0035: "Whether/how they eventually join a unified stable entity identity is deferred to PII
  L17 (stable entity model with lineage) — an explicit non-goal here, not a decision made by
  omission."

A downstream Replacement Plan needs exactly that: one coherent shape for "this stable entity was
reviewed and decided," regardless of whether the entity was detector-found or human-added, plus an
explicit signal for whether the identity backing that decision is still trustworthy after
reprocessing. Today a consumer would have to read two differently-shaped lists
(`PiiReviewOccurrence` vs. `PiiManualAddition`), reconstruct anchor identity itself by calling into
`pii_anchor_binding.py`, and infer version compatibility only from the coarse, document-level
`stale_decision_count`/`has_stale_decisions` pair — not per entity.

## Decision

- **`PiiReviewResultEntry`** (`backend/app/schemas.py`): one row per detected occurrence *or*
  manual addition, in the *same* shape. `entry_id` is always the existing occurrence/addition uuid
  (never anchor-derived — the ADR-0033 guardrail is unchanged: anchor ids are only stable per
  text-artifact-bytes × graph-builder version, never a safe persisted key). `origin`
  (`"detected"`/`"manual"`) replaces the need for two competing types. Every field is an id, code,
  offset-free status, or count — no copied source text.
- **`anchor_entity_id`** is an additive, freshly-recomputed secondary reference into the
  anchor-bound entity contract (ADR-0031 Phase C) — the secondary linkage ADR-0034 explicitly
  deferred. It is *never* persisted as a lookup key: `pii_review_result.py` rebuilds it on every
  read by rebinding the entity's own originating pii/text artifact pair (never "today's" pair for
  a stale entry), exactly mirroring how `pii_entity_contract.py` already computes anchor identity
  fresh per request. A decision's applicability still resolves through `entry_id` alone; a builder
  version change can only ever change the *displayed* `anchor_entity_id`, never which decision
  applies.
- **`identity_status`** (`resolved`/`unresolved`/`incompatible`) makes explicit what was previously
  only inferable: `resolved` — anchor-bound (detected, exact/partial) or a resolved raw/canonical
  projection (manual, `pii_manual_addition.py`'s existing exact/partial). `unresolved` — identity
  was attempted but came back missing/ambiguous/not-applicable; the entry is still fully
  reviewable, exactly per the existing "never drop, only flag" discipline
  ([`quality-gates.md`](../../.ai/quality-gates.md)). `incompatible` — a genuine structural break
  (stored offsets that no longer fit their own referenced text, or a referenced artifact that fails
  to load) rather than an ordinary binding gap; this is intentionally rare and mostly exercised by
  direct unit tests, since the normal artifact-creation path never produces it.
- **`artifact_currency`** (`current`/`stale`) is the per-entry counterpart of the existing
  document-level `has_stale_decisions`: whether the entry's own originating artifact (its
  `pii_artifact_id` for a detected entry, its `text_artifact_id` for a manual addition) still
  matches the document's current one. It reuses the exact same comparisons `_count_stale_decisions`
  already made — no new staleness rule.
- **`mapping_status`** is visible on every entry (reusing `PiiEntityMappingStatus`, exact/
  projected/partial/missing/ambiguous/not_applicable) and is computed once, then only ever *read*
  by review — a decision never upgrades or recomputes it. For manual additions it is a direct
  mapping of the already-resolved `raw_projection_status` (exact→exact, partial→partial,
  unmapped→missing); manual additions are still **not** run through anchor binding here, per
  ADR-0035's explicit non-goal.
- **Integration, not a new artifact.** `PiiReviewResult.entries` (and therefore
  `PiiReviewResultArtifact.content.entries`) is additive on the *existing* Review L8 artifact and
  endpoints (`GET …/pii/review`, `GET …/pii/review-result`) — no new endpoint, no new persistence
  boundary, no change to the append-only JSONL write path. `groups`/`occurrences`/
  `manual_additions` are unchanged for full backward compatibility; `entries` is the coherent
  superset a Replacement Plan should read instead.
- **Shared display logic extracted, not duplicated.** `pii_entity_contract.py`'s private
  mapping-status/display-range/reason-code helpers move to a new leaf module
  `pii_entity_display.py` (zero behavior change — proven by the full existing entity-contract test
  suite passing unchanged) so both `pii_entity_contract.py` and the new `pii_review_result.py` call
  the same functions instead of maintaining two copies. `pii_review_result.py` cannot import
  `pii_entity_contract.py` (that module already imports `pii_review_service.py`, which now imports
  `pii_review_result.py` — a direct import back would cycle), which is exactly why the shared logic
  needed its own leaf module rather than being reused in place.
- **`PiiReviewOccurrence.updated_at`** (additive) now carries the effective decision's timestamp,
  mirroring the sibling `PiiEntityGroupReview.updated_at` that already existed — needed so
  `PiiReviewResultEntry.updated_at` has a real value to report ("provenance and timestamps
  available from the current review workflow").

## Consequences

- No detection, recognizer, `pii_result` schema, active-PII-input, anchor-graph, tokenizer,
  pseudonymization, redaction, or export change. `pii_result` and the Text Anchor Graph stay
  completely untouched by review, proven by a dedicated end-to-end test comparing `GET …/pii` and
  `GET …/pii/entity-contract` before and after a decision.
- No SQLite/database introduced; persistence stays the existing file-based artifact + JSONL model.
- Existing `GET …/pii/review`, `GET …/pii/review-result`, `POST …/pii/review/decisions`, and
  `POST …/pii/review/manual-additions` response shapes are unchanged except for the additive
  `entries` (and `PiiReviewOccurrence.updated_at`) fields; the full existing backend and frontend
  test suites pass unchanged.
- A downstream Replacement Plan can read `PiiReviewResult.entries` (or the persisted
  `PiiReviewResultArtifact.content.entries`) alone: `entry_id` for stable identity, `origin` for
  detected-vs-manual, `review_decision`/`review_status` for disposition, `identity_status`/
  `artifact_currency` for whether the decision is still trustworthy, and `mapping_status` for
  display quality — without reading `pii_result`, the anchor graph, or the JSONL decision log
  directly.
- Replacement, pseudonymization, redaction, and reconstruction are explicitly **not** implemented
  by this branch.

## Next

This closes the third and final branch named in the feasibility audit's Phase 3 recommendation
list (`anchor-first-text-package-v2` → `pii-binding-quality-suite` → `review-result-v1`), on top of
the already-delivered Review L8 `review_result` artifact. Re-run the checkpoint loop against
`.ai/state.md`'s current-sequence section for the next engine priority; a Replacement Plan
consuming `PiiReviewResultEntry` is explicitly the next step this branch was scoped to unblock, not
implemented here.
