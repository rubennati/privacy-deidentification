# ADR-0035: PII L14 / Review L10 — manual add of missed entities (architecture scope)

## Status

Accepted — 2026-07-10. Docs-only; scopes the next implementation PR, delivers no code. Builds on
[ADR-0021](0021-pii-entity-grouping-and-review-decisions.md) (review-decision overlay),
[ADR-0029](0029-pii-review-ready-entity-contract.md)/[ADR-0031](0031-text-identity-anchor-lineage-architecture.md)
(anchor-bound entity contract), [ADR-0033](0033-pii-binding-quality-suite.md) (occurrence-id-primary
keying / anchor-id-drift guardrail), and [ADR-0034](0034-review-l8-review-result-artifact.md)
(`review_result` artifact).

## Context

[`pii-engine-levels.md#level-14`](../engine/pii-engine-levels.md#level-14--manual-add--missed-entities--open)
and [`review-feedback-levels.md#level-10`](../engine/review-feedback-levels.md#level-10--manual-add--open)
already state the acceptance criterion for this step verbatim: *"manual additions in `review_result`
with canonical-text offsets and `origin = human`"*, *"a human-added span round-trips with valid
offsets and is distinguishable from machine detections"*, *"it becomes a recall (missed-entity)
signal."* `.ai/tasks.md` and `.ai/state.md` name this the next checkpoint-gated step after PII
L13/Review L9 (direct decision lineage). This ADR is the scoping pass that precedes that
implementation PR, per this repo's Understand → Plan → Implement workflow ([AGENTS.md](../../AGENTS.md#workflow)).

An audit of the current review/decision code (`pii_review_service.py`, `schemas.py`,
`pii_entity_contract.py`, `pii_anchor_binding.py`, and the frontend review components) found four
load-bearing facts that a naive "just add a row somewhere" implementation would violate:

1. **`pii_result` is strictly immutable and detector-only.** Every artifact docstring says so
   explicitly (`PiiArtifact`, `PiiEntityGroup`, `pii_review_service.py`'s module docstring: "Neither
   `pii_result` nor its entities/offsets are ever mutated by a decision"). There is no path to append
   a human-authored span here without breaking that invariant.
2. **`AnchorBoundPiiEntityV1.source_observations` structurally requires a detector observation.**
   It is `Field(min_length=1)` of `PiiSourceObservation`, and every field of that model
   (`pii_anchor_binding.py`) is derived 1:1 from an existing `PiiEntity` (`detection_id=entity.id`,
   `recognizer=entity.recognizer`, `confidence=entity.score`). Even the evidence-only fallback
   identity path hashes a `PiiEntity`'s raw offsets. A human-added span with no detector observation
   and no `pii_result` entry has **no path into this model** today.
3. **`PiiReviewResultArtifact`/`PiiReviewResult` are occurrence-id-primary, and
   `PiiReviewOccurrence.occurrence_id` *is* `PiiEntity.id`.** ADR-0034 deliberately keyed the review
   artifact on the raw detection uuid, not any anchor-derived identity — again detector-origin-only,
   by design (ADR-0033's anchor-id-drift finding).
4. **No actor/user field exists anywhere in review persistence.**
   `PiiReviewDecisionRecord.source` (`"user"|"default"|"imported"`) is a static request-source tag,
   hard-coded to `"user"` today, not a per-record origin/actor marker — actor/reason metadata is
   explicitly named future work at Review L11 in ADR-0021, not designed yet.

The frontend has no supporting primitives either: `PiiTextViewer`/`ReviewTextViewer` only handle
click-on-an-existing-highlight (`onClick` on `<mark>`); there is no `getSelection()`/`mouseup`
text-selection capture and no entity-type picker component anywhere in `frontend/src` today (the
existing `<select>` dropdowns in `PiiReviewGroupList.tsx` choose a *decision*
`pseudonymize/keep/false_positive`, not an entity type).

## Decision

Manual additions become a **new, additive record type layered on the existing review-decision
mechanism** — never forced into `pii_result` or the detector-oriented anchor-bound entity contract,
mirroring ADR-0034's own precedent of declining a same-PR extension that didn't structurally fit.

- **Same JSONL log, a new discriminated record shape.** `pii_review_decisions.jsonl` gains a second
  record variant (e.g. `record_type: "manual_addition"`) appended through the same
  `_append_decision_line` open-append + fsync path already used for decisions — no new file,
  directory, or database. `PiiReviewResult` gains an additive `manual_additions: list[PiiManualAddition]`
  field, parallel to but never merged into `occurrences`/`groups`.
- **Fields of `PiiManualAddition`:** a freshly minted `addition_id` (uuid4, never derived from any
  `pii_result` entity or anchor); `entity_type`, constrained to the current `pii_result`'s own
  `PiiContent.configured_entity_types` (`schemas.py:2067` — the exact types that run was configured
  to detect) rather than a free-text field, a new taxonomy, or the generic default-profile config;
  `canonical_start`/`canonical_end` offsets into `reading_text`, plus the exact
  `text_artifact_id` they were captured against (reusing the optional field
  `PiiReviewDecisionRecord.text_artifact_id` already carries for decisions); `origin: "human"`
  (literal, explicit per the acceptance criterion even though list placement alone is already
  structurally distinguishing); an optional `note` (reusing the existing decision `note` field, no
  new reason/comment model — actor/reason completeness stays Review L11, still open); `created_at`.
- **Canonical-text offsets, with best-effort raw reconciliation, never invented.** The acceptance
  criterion specifies canonical-text offsets (the human-facing default view per L10.5/ADR-0031's
  "User View defaults to Kanonischer Lesetext"), so capture happens against `reading_text`, not raw.
  A best-effort reverse projection to a raw span is attempted by **reusing the existing
  `reading_text_map`/Text Anchor Graph canonical↔raw projection machinery** (same exact/partial/
  unmapped discipline already governing the opposite direction for detected entities) — never a new
  matching heuristic. An unresolvable reverse projection is an explicit `raw_range = None`,
  reason-coded state (the mirror image of the existing `canonical_range_missing` case), not a
  guessed or dropped addition.
- **Staleness keys off `text_artifact_id`, not a `pii_result` artifact id.** A manual addition has no
  originating `PiiEntity`, so it cannot be scoped to a `pii_result.id` the way decisions are. It is
  instead scoped to the `text_result.id` its canonical offsets were captured against; a later
  OCR/PII re-run that produces a new `text_result` marks prior additions stale through the same
  `has_stale_decisions`-style mechanism ADR-0034 already built, extended to also scan
  `manual_addition` records.
- **Post-creation lifecycle reuses the existing decision endpoint — creation is the only new action.**
  Once an `addition_id` exists, it becomes a valid `target_id` for
  `POST …/pii/review/decisions` under a new `target_type: "manual_addition"`, so
  accept/keep/`false_positive` on a manual addition is handled by the *same* code path as on a
  detected occurrence. There is no separate edit/delete action — consistent with the append-only
  philosophy already governing every other review record; "removing" a manual addition is a
  `false_positive` decision against it, not a deletion.
- **Explicitly not merged into `AnchorBoundPiiEntityV1`/the entity contract or `pii_result`.**
  Manual additions surface only through `review_result` (`GET …/pii/review`,
  `GET …/pii/review-result`) as their own list. Whether/how they eventually join a unified stable
  entity identity is deferred to PII L17 (stable entity model with lineage) — an explicit non-goal
  here, not a decision made by omission.
- **Frontend needs three genuinely new primitives, named explicitly because none exist today:** (1)
  text-selection capture (`getSelection()`/`mouseup`) over the canonical reading-text view, (2) an
  entity-type picker sourced from `configured_entity_types`, and (3) a visually distinct rendering
  for a manual addition (parallel to how `kept`/`rejected` already render distinguishably from the
  default highlight), so a human-added span is distinguishable from a machine detection per the
  acceptance criterion.

### Explicit non-goals for the follow-up implementation PR

- Actor/user identity on any record (Review L11, still open).
- Reason/comment beyond the existing optional `note` field (also Review L11).
- Suppression/allowlist rules (L12) or reusable cross-run decisions (L13).
- Promoting manual additions into the private benchmark ground truth (L15/PII L15 — deferred).
- Any change to `pii_result`, detection, recognizers, the Text Anchor Graph, active PII input,
  pseudonymization, redaction, or export.
- Edit or hard-delete of a manual addition (handled via the existing decision mechanism instead).
- Merging manual additions into `AnchorBoundPiiEntityV1`/the entity contract (deferred to PII L17).

## Consequences

- `pii_result` and the anchor-bound entity contract (PII L12/Phase C) stay completely untouched —
  zero regression risk to already-delivered PII L11–L13 and Review L6–L9 behavior.
- Exactly one new discriminated record shape is added to the existing JSONL log and
  `PiiReviewResultArtifact`; no new file/directory convention, no SQLite/database.
- The design reuses three existing mechanisms — the decision log/artifact, canonical↔raw
  projection, and the configured entity-type list — instead of inventing new ones, per this
  project's tool-first/adapter-bound and no-ad-hoc-heuristics governance
  ([AGENTS.md](../../AGENTS.md#product-principle-tool-first--adapter-bound)).
- The frontend gap is real: selection capture, a type picker, and distinct rendering are net-new UI
  surface, not incidental additions — the implementation PR should budget for that explicitly rather
  than assume it is "just a new list to render."
- This ADR does not by itself deliver PII L14/Review L10; both stay `⛔ open`. It is the design that
  unblocks a single, focused follow-up PR.

## Next

Implement this design as `pii-l14-manual-add-v1` (or similarly named branch): the new record shape
and endpoint, the reused-projection reverse mapping, and the three frontend primitives above. Re-run
the checkpoint loop against `.ai/state.md`'s current-sequence priorities afterward.
