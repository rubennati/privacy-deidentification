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

- A decision (`pseudonymize | keep | false_positive`, optional `note`) targets either an
  `entity_group` or a single `occurrence` (a `PiiEntity.id`). Occurrence-level decisions override
  the group-level decision for that one occurrence; everything else in the group inherits the
  group decision. No decision ever mutates `start_offset`/`end_offset`/`reading_start_offset`/
  `reading_end_offset` on any entity.
- **A freshly detected entity is assumed `pseudonymize` by default — there is no separate
  "pending"/undecided state.** A reviewer only has to act to opt an entity *out* of
  pseudonymization: `keep` it as-is (still PII, but don't touch it), or mark it `false_positive`
  (it was never PII). This default was chosen deliberately over an initial "pending until reviewed"
  design: for a tool whose whole purpose is preparing documents for pseudonymization, assuming the
  common case (pseudonymize) and asking the reviewer to opt out of the exceptions is less friction
  than requiring an explicit decision on every single entity.
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
- A coarse `review_status` (`accepted | kept | rejected`) is derived from the decision for display:
  no explicit decision, or `pseudonymize` → `accepted`; `keep` → `kept`; `false_positive` →
  `rejected`. `accepted` is therefore both the implied default *and* the explicit-pseudonymize
  outcome — there is no way to distinguish "nobody has looked at this yet" from "a reviewer
  confirmed pseudonymize" in the current model, which is an intentional simplification (see
  Consequences).
- `GET …/pii/review` returns the merged, request-time view (groups + occurrences with resolved
  decisions); `POST …/pii/review/decisions` appends one decision and returns a small
  acknowledgement. An unknown group/occurrence id returns `404`; an invalid `decision`/`target_type`
  value returns `422` via normal Pydantic validation. Both endpoints 404 cleanly when a document has
  no PII result yet, and legacy documents with no decisions file simply show every entity as
  `accepted` (the assumed-pseudonymize default).

## Consequences

- This is a **lighter persistence shape than the `review_result` artifact originally sketched** in
  `review-feedback-levels.md` Level 8 (a single immutable JSON artifact per run, "the first place a
  database becomes genuinely useful"). It satisfies that level's *practical* intent — decisions
  persist, restore on reload, and never silently reapply across a re-run — without yet introducing
  a database or a formal artifact-file model. Formalizing this into a proper `review_result`
  artifact (with actor/reason metadata at Review L11, scoped suppression rules at L12, and reusable
  cross-run decisions at L13) remains explicitly open.
- The decision vocabulary (`pseudonymize/keep/false_positive`) differs from the plain confirm/reject
  binary in the original Review L9 sketch: it is pseudonymization-oriented (opt out of the default,
  rather than confirm/reject every candidate) and has no distinct "pending" status. This means the
  API cannot today tell a caller "no one has reviewed this yet" apart from "a reviewer explicitly
  chose pseudonymize" — both read as `accepted`. If a future requirement needs that distinction
  (e.g. a completeness/coverage report of what a human has actually looked at), it needs a separate
  signal, since `review_status`/`review_decision` alone cannot answer it.
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
  reading-text modes); a `kept` entity keeps its highlight with a distinguishable (dashed/dimmed)
  style; an `accepted` entity — the default, expected case for most entities — renders as a normal
  highlight with no extra modifier, so the common case does not look visually "flagged." Layout-text
  mode is unaffected — it was and remains unhighlighted.
- The review-decision panel (`PiiReviewGroupList`) shows in both Dev View (full detail: reading-text
  projection coverage, per-occurrence offsets/overrides) and User View (simplified: type, count,
  status, and the group-level decision only) next to the extracted text, in its own
  independently-scrolling area. Each occurrence's offset is a clickable jump-to-highlight control,
  matching the existing per-entity list.
