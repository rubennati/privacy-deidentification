# ADR-0034: Review L8 `review_result` artifact (Phase 3)

## Status

Accepted — 2026-07-10. Builds on [ADR-0021](0021-pii-entity-grouping-and-review-decisions.md) (PII
entity grouping and the JSONL review-decision overlay) and follows
[ADR-0032](0032-reading-text-row-construction-lineage-v1.md)/[ADR-0033](0033-pii-binding-quality-suite.md)
(Phases 1–2). Delivers Phase 3 of the sequence recommended in
[`text-anchor-architecture-feasibility-audit.md`](../engine/text-anchor-architecture-feasibility-audit.md#phase-3--review-result-v1-review-l8),
the last of its three recommended branches.

## Context

The audit's Phase 3 goal: "the formal single-artifact-per-run `review_result` over stable entity
identity, keyed primarily on occurrence ids with anchor-derived `entity_id` as secondary linkage,
with an explicit stale flag when the underlying `pii_result` changes." Acceptance: "immutable-per-run
review artifact; decisions survive reload and re-runs mark staleness explicitly; `pii_result` stays
immutable; overlay migration path documented; no DB required yet (JSON per run), with the
SQLite-ready shape stated." Guardrails: no SQLite in this PR, no anchor ids as decision keys without
a pinned graph, no replacement planning built into the artifact.

Before this PR, `GET …/pii/review` recomputed the reviewable view fresh on every call from the
append-only `pii_review_decisions.jsonl` log (ADR-0021) — decisions already survived reload
(the log is durable) and already never silently reapplied across a PII re-run
(`_load_latest_decisions` filters strictly by the current `pii_result` artifact id). What was
missing was (a) a proper immutable, versioned *artifact* for the resolved review state, consistent
with how every other station (`original`/`audit`/`text`/`pii`) persists its output, and (b) an
*explicit* signal when decisions exist but no longer apply — today that case looks byte-identical to
"nothing was ever reviewed," which silently discards the fact that a reviewer's prior work was
invalidated by a re-run.

## Decision

- **New immutable `PiiReviewResultArtifact`** (`backend/app/schemas.py`), following the exact same
  envelope shape as `PiiArtifact`/`TextArtifact` (`id`/`document_id`/`artifact_type`/`station`/
  `input_pii_artifact_id`/`created_at`/`content`) and the same file-based persistence
  (`artifact_service.save_pii_review_result_artifact`/`get_latest_pii_review_result_artifact`,
  sharing the same per-document `artifacts/` directory and newest-wins-on-read pattern as the other
  four artifact kinds — discriminated by each schema's `Literal` `artifact_type`/`station` fields,
  exactly like the existing four). `content` reuses `PiiReviewResult` unchanged in shape.
- **Occurrence-id-primary keying**: the snapshot's `content.occurrences` key on
  `PiiReviewOccurrence.occurrence_id` (the raw `PiiEntity.id` detection uuid), never on any
  anchor-derived identity from the entity contract (ADR-0031 Phase C) — per the audit's explicit
  guardrail and its own drift finding (ADR-0033): anchor ids are only stable per
  (text-artifact-bytes × graph-builder version), not yet a safe persisted key. The audit's goal text
  also names an anchor-derived `entity_id` as *secondary* linkage; this PR does not add it —
  `pii_review_service.py` has no existing dependency on the anchor-binding pipeline
  (`pii_anchor_binding.py`/`pii_entity_contract.py`), and wiring one in for a best-effort secondary
  reference was judged a real architectural addition rather than a same-PR-sized extra field.
  Occurrence ids alone satisfy the acceptance criteria (decisions survive reload/re-runs correctly);
  left open for a future PR if a consumer actually needs the secondary linkage.
- **Immutable-per-run**: `set_pii_review_decision` appends its JSONL record exactly as before
  (unchanged write path), then builds and persists a fresh `PiiReviewResultArtifact` snapshot
  reflecting the fully-resolved state after that decision — a new artifact id every time, never
  overwritten. New `GET …/pii/review-result` returns the latest one.
- **Explicit staleness**: `PiiReviewResult` gains additive `stale_decision_count`/
  `has_stale_decisions`. `_count_stale_decisions` collapses the JSONL log to the latest record per
  `(target_type, target_id)` across *every* artifact id ever recorded for the document (not
  filtered to the current one, unlike the existing decision-resolution path), then counts how many
  of those latest-per-target records target a now-superseded `pii_result` artifact id. This changes
  no resolution behavior — a stale decision still never reapplies — it only surfaces what was
  previously silent. Both `GET …/pii/review` and the persisted snapshot carry these fields.
- **Direct text lineage (additive follow-up):** New decision records and immutable snapshots also
  carry the exact `input_text_artifact_id` consumed by their referenced PII artifact; the review
  response exposes the same field. Existing JSONL lines/snapshots without it remain readable as
  legacy data. The exact PII artifact id remains the reapplication boundary, so this field makes
  lineage explicit without changing stale-decision resolution or introducing automatic reuse.
- **Frontend**: `PiiReviewResult`'s TS type gains the two fields; `DocumentDetailPage.tsx` shows a
  `StatusNotice` ("N Überprüfungsentscheidung(en) aus einem vorherigen PII-Lauf … bitte erneut
  prüfen") when `has_stale_decisions` is true for the current PII run.
- **Overlay migration path (documented, not executed in this PR)**: the JSONL log remains the
  append-only write-time source of truth every decision is recorded into — it is not removed or
  replaced. `PiiReviewResultArtifact` is the durable *read* model going forward: consumers that need
  "the current resolved review state as of the last decision" should prefer
  `GET …/pii/review-result`; `GET …/pii/review` keeps its on-demand recomputation behavior
  unchanged for full backward compatibility. A future step could migrate the JSONL log itself into
  SQLite (mirroring `job_store.py`'s pattern) without changing this artifact's shape — explicitly
  deferred per the "no DB in this PR" guardrail. The artifact's `content` is already a flat,
  offset-keyed list of occurrence/group rows, which is the "SQLite-ready shape" the acceptance
  criteria asks to have stated: each occurrence row would map to one table row keyed by
  `(document_id, occurrence_id)`, with no schema change needed to move the same fields into a table.

## Consequences

- No detection, recognizer, `pii_result` schema, active-PII-input, pseudonymization, redaction, or
  export change. `pii_result` stays immutable; nothing about it is touched.
- No replacement/reconstruction planning is built into the artifact — it carries resolved review
  status/decision/timestamps only, exactly what `GET …/pii/review` already exposed.
- No SQLite/database introduced; persistence stays the existing file-based artifact model.
- Existing `GET …/pii/review` and `POST …/pii/review/decisions` behavior and response shapes are
  unchanged except for the two additive fields; existing tests needed no changes beyond adding
  those fields to hand-built fixtures.
- A `POST` review decision now does two writes instead of one (the JSONL append, then the snapshot
  save) — both are small, local, atomic file writes consistent with every other artifact save in
  this codebase; no new failure mode beyond the existing `ApiError` paths those already have.

## Next

This was the last of the feasibility audit's three recommended branches (Phases 1–3). Future
engine work should re-run the checkpoint loop against `.ai/state.md`'s current-sequence priorities
rather than continuing this specific audit's list.
