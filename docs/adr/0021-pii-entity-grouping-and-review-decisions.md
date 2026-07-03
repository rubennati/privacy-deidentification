# ADR-0021: PII entity grouping and a review-decision overlay

## Status

Accepted — 2026-07-03

## Context

PII detection (`pii_result`) has always rendered as a flat list of occurrences: the same email,
IBAN, phone number, or name mentioned three times produces three separate entity cards with no
way to act on "this value" once. [`pii-engine-levels.md`](../engine/pii-engine-levels.md) names
this **PII L11 — entity grouping** (present each distinct entity once with its occurrences
collected beneath it) and [`review-feedback-levels.md`](../engine/review-feedback-levels.md) names
the companion **Review L6 — grouped occurrences** and **Review L8 — `review_result` artifact
model** (a persisted decision overlay bound to `pii_result`, with `pii_result` staying immutable).

Before pseudonymization can exist, something has to answer "which of these detected spans should
later be pseudonymized, kept as-is, ignored, or treated as a false positive?" — durably, per
document, without a human re-deciding on every reload and without ever mutating the immutable
`pii_result` artifact or its raw/projected offsets.

## Decision

**Grouping is a pure, derived view — never persisted.**

- `pii_grouping.group_pii_entities()` groups `PiiContent.entities` by **entity type + a
  conservative per-type normalized value**: exact lowercase for email, whitespace-stripped/upper
  for IBAN, digit/`+`-only for phone, whitespace-stripped (case/punctuation preserved) for
  structured ID-like types, and exact whitespace-normalized text for everything else (names,
  organizations, addresses, dates, …). There is no fuzzy matching, no cross-type grouping, and no
  proximity-based grouping — ambiguous cases stay separate rather than risk merging distinct
  entities.
- `entity_group_id` and `normalized_fingerprint` are both derived from a SHA-256 digest of
  `entity_type + normalized_value`; the normalized value itself is never stored, only the hash and
  a projection-coverage summary (`exact_count`/`partial_count`/`unmapped_count`).
- Grouping is recomputed on every request from the **latest** `pii_result`; nothing is added to
  `PiiEntity`, `PiiContent`, or `PiiArtifact`, so the immutable detection artifact and its schema
  are completely unchanged. Existing `GET/POST …/pii` responses are byte-for-byte unaffected.

**Review decisions are a separate, additive overlay — not a field on `pii_result`.**

- A decision (`pseudonymize | keep | ignore | false_positive`, optional `note`) targets either an
  `entity_group` or a single `occurrence` (a `PiiEntity.id`). Occurrence-level decisions override
  the group-level decision for that one occurrence; everything else in the group inherits the
  group decision. No decision ever mutates `start_offset`/`end_offset`/`reading_start_offset`/
  `reading_end_offset` on any entity.
- Persistence reuses the existing append-only JSONL pattern from the dev-only feedback
  side-channel (`pii_feedback.jsonl`) rather than inventing a new artifact-file model, per the
  explicit instruction to reuse existing review-feedback archive logic where it fits: each decision
  is one line under `document-data/<document_id>/review/pii_review_decisions.jsonl`, and reading
  collapses the log to the **latest line per (target_type, target_id)** scoped to the exact current
  `pii_result.id`. A re-run that produces a new PII artifact id makes prior decisions invisible
  (never silently reapplied) rather than requiring a separate staleness flag.
- Unlike the feedback side-channel, this overlay is **not** gated behind
  `ENABLE_DEV_ENGINE_SETTINGS` — it is the binding handoff layer future pseudonymization work will
  read from, not a dev-only quality-analysis channel, so it must be available whenever PII results
  exist.
- A coarse `review_status` (`pending | accepted | rejected | ignored`) is derived from the decision
  for display: `pseudonymize`/`keep` → `accepted`, `ignore` → `ignored`, `false_positive` →
  `rejected`. `pending` is the default for every occurrence/group with no decision yet.
- `GET …/pii/review` returns the merged, request-time view (groups + occurrences with resolved
  decisions); `POST …/pii/review/decisions` appends one decision and returns a small
  acknowledgement. An unknown group/occurrence id returns `404`; an invalid `decision`/`target_type`
  value returns `422` via normal Pydantic validation. Both endpoints 404 cleanly when a document has
  no PII result yet, and legacy documents with no decisions file simply show everything as
  `pending`.

## Consequences

- This is a **lighter persistence shape than the `review_result` artifact originally sketched** in
  `review-feedback-levels.md` Level 8 (a single immutable JSON artifact per run, "the first place a
  database becomes genuinely useful"). It satisfies that level's *practical* intent — decisions
  persist, restore on reload, and never silently reapply across a re-run — without yet introducing
  a database or a formal artifact-file model. Formalizing this into a proper `review_result`
  artifact (with actor/reason metadata at Review L11, scoped suppression rules at L12, and reusable
  cross-run decisions at L13) remains explicitly open.
- The decision vocabulary (`pseudonymize/keep/ignore/false_positive`) is broader than the plain
  confirm/reject binary in the original Review L9 sketch; `keep` and `pseudonymize` both map to the
  `accepted` status (an entity a human has reviewed and wants to remain active), while `ignore` and
  `false_positive` both suppress the entity from being an "active" highlight but stay visually and
  semantically distinct from each other.
- `entity_group_id` is deterministic across requests for the *same* PII artifact (a hash of type +
  normalized value), which is what lets a decision persist and be found again — but it also means
  the same value in two different documents, or across two different PII runs on the same document,
  can produce the same group id. This is harmless today because decisions are always scoped and
  looked up per document and per `pii_result.id`; it would need reconsideration only if a future
  feature tried to reuse a decision across documents or across re-runs (Review L13), which is
  explicitly out of scope here.
- No pseudonymization, placeholder generation, text replacement, or export happens as a result of
  any decision. This ADR only establishes the reviewable grouping/decision layer that a future
  pseudonymization engine would consume.
- Frontend highlighting (`piiHighlights.ts`, `PiiTextViewer`) now accepts an optional per-occurrence
  review-status map: a `rejected` entity is excluded from highlighting entirely (in both raw and
  reading-text modes), while `accepted`/`ignored` entities keep their highlight with a
  distinguishable style. Layout-text mode is unaffected — it was and remains unhighlighted.
