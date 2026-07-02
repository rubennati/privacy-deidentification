# Review / Feedback Engine — Levels 0–10

The review engine puts a **human in the loop** over immutable PII labels: inspect, correct, and
eventually *teach* the pipeline — auditable throughout. It is the third sub-engine in the
[north star](README.md#north-star) and the bridge to trustworthy redaction later.

Two constraints shape every level:

- **Lineage safety.** A review decision is always bound to the exact `pii_result` and `text_result`
  it acted on. If text is re-extracted, prior decisions become *stale*, never silently reapplied.
- **Controlled blast radius.** Manual decisions must not silently become global truth. Scope
  (this document / this profile / global) is explicit, and global effects require deliberate opt-in.

Level numbers are cumulative and **not** comparable to the OCR or PII ladders.

---

## Level 0 — Display only  ✅ *done*

- **Human can:** open a document and read the extracted text.
- **Persisted:** nothing beyond existing artifacts.
- **Needs later DB:** no.
- **Feedback loop:** none.
- **Acceptance:** the detail page renders text without mutating anything.

## Level 1 — Candidate list  ✅ *current baseline*

- **Human can:** see the list of detected PII candidates and lineage-safe highlights overlaid on the
  text (only when the highlight's input text artifact matches the displayed text).
- **Persisted:** nothing new; the view is read-only.
- **Needs later DB:** no (reads existing `pii_result`).
- **Feedback loop:** none yet.
- **Acceptance:** candidates render with correct offsets; stale/missing lineage is surfaced; no HTML
  injection, no source-text logging.

### Dev-only feedback capture (analysis side-channel, not L2)

A small **dev-only** control set on each entity card records structured review feedback so
recurring detection errors can be analysed later. It is deliberately **not** the L2
`review_result` model and **not** a learning system — it never changes detection, never mutates
the immutable `pii_result`, and applies no rules.

- **Gated:** available only when `ENABLE_DEV_ENGINE_SETTINGS=true` (same dev gate as per-run engine
  overrides). With the gate off, the UI hides the controls and `POST …/pii/feedback` returns `403`.
- **Persisted:** append-only JSONL at `document-data/{document_id}/feedback/pii_feedback.jsonl`
  (under the git-ignored `volumes/` mount; removed with the document). Each line carries a
  timestamp, document/artifact ids, the entity fingerprint (type + offsets + recognizer + score),
  the verdict/issue_type/optional comment, the artifact's engine settings, and app/schema version.
- **Privacy:** no document text, OCR full text, or raw entity value is stored — offsets and types
  are enough for analysis; an optional opaque `text_hash` field exists but the UI does not send it.
- **Not a level:** production stays gated off; promoting this into the auditable L2 `review_result`
  overlay (below) is separate, future work.

## Level 2 — Confirm / reject a candidate  ⛔ *open (next)*

- **Human can:** mark a candidate **confirmed** or **rejected**.
- **Persisted:** a `review_result` artifact keyed to `pii_result.id` + `text_result.id`, listing
  per-candidate decisions. The `pii_result` stays immutable; the decision is an overlay.
- **Needs later DB:** file-based first (a `review_result` JSON artifact); DB when query/history
  matters.
- **Feedback loop:** none yet (decisions are recorded, not generalised).
- **Acceptance:** a decision persists against the exact lineage and is re-rendered on reload;
  re-extraction marks it stale rather than reapplying it.

## Level 3 — Add a candidate manually  ⛔ *open*

- **Human can:** select a span the engine missed and add it as a PII entity (with a type).
- **Persisted:** manual additions in `review_result` with offsets into the canonical text and
  `origin = human`.
- **Needs later DB:** file-based first.
- **Feedback loop:** additions become recall data for the benchmark (missed-entity signal).
- **Acceptance:** a human-added span round-trips with valid offsets and is distinguishable from
  machine detections.

## Level 4 — Store reason / comment  ⛔ *open*

- **Human can:** attach a reason/comment to a confirm/reject/add (why it is/ isn't PII).
- **Persisted:** reason text + actor + timestamp on each decision in `review_result`.
- **Needs later DB:** file-based works; DB helps search/aggregate reasons.
- **Feedback loop:** reasons categorise false positives/negatives (feeds
  [quality-metrics](quality-metrics.md#pii-metrics) FP/FN categories).
- **Acceptance:** decisions carry an auditable reason; reasons never contain raw PII beyond the span
  already stored.

## Level 5 — Local suppression / allowlist rules  ⛔ *open*

- **Human can:** turn a repeated decision into a rule ("token X is never PERSON in this document" /
  "this label is always a claim number").
- **Persisted:** a scoped rules store; each rule records scope + reason + author.
- **Needs later DB:** rules are a good early DB candidate (lookup, versioning) but can start
  file-based.
- **Feedback loop:** rules feed **PII L8** (feedback rules) — the engine applies them at detection
  post-processing (candidate validation).
- **Acceptance:** a rule applies consistently within its declared scope; a document-scoped rule
  never leaks to other documents; global rules require explicit opt-in.

## Level 6 — Reusable review decisions  ⛔ *open*

- **Human can:** carry decisions/rules across re-runs and similar documents deliberately.
- **Persisted:** decision/rule identity stable across artifact versions; re-application is an
  explicit, logged action, not automatic.
- **Needs later DB:** yes, in practice (state + history across runs).
- **Feedback loop:** stronger — the same reviewer effort is not repeated per re-extraction.
- **Acceptance:** re-running OCR/PII offers to re-apply prior decisions with a visible diff; nothing
  is reapplied silently.

## Level 7 — Benchmark feedback  ⛔ *open*

- **Human can:** promote confirmed/rejected/added decisions into the benchmark's ground-truth
  signal (locally, privately).
- **Persisted:** review-derived corrections exported into the private benchmark inputs under
  `volumes/benchmark/` (never committed).
- **Needs later DB:** helpful, not required.
- **Feedback loop:** closes the loop — human corrections improve the *candidate ground truth* and
  make regression numbers more trustworthy.
- **Acceptance:** a reviewer can turn corrections into private benchmark data without exporting any
  PII outside `volumes/`.

## Level 8 — Profile / policy-based review  ⛔ *open*

- **Human can:** review under a policy (e.g. GDPR/insurance) that defines which types *must* be
  reviewed, with required-field checks and sign-off.
- **Persisted:** policy + per-policy review completeness in `review_result`.
- **Needs later DB:** yes (policy state, completeness tracking).
- **Feedback loop:** ties review coverage to a
  [PII profile](pii-engine-levels.md#profiles-the-configuration-axis).
- **Acceptance:** review completeness is measurable against a named policy before a document is
  considered "reviewed".

## Level 9 — Local AI review assist  ⛔ *open, optional*

- **Human can:** get **local**, assistive suggestions ("likely false positive", "possible missed
  person") that speed review — never auto-applied.
- **Persisted:** assist suggestions flagged `assistive = true`, distinct from human decisions.
- **Needs later DB:** same as L6+.
- **Feedback loop:** AI proposes, human disposes; acceptance rate is tracked.
- **Acceptance:** suggestions are local, labelled, and only change state through an explicit human
  action. See the
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding).

## Level 10 — Auditable human-in-the-loop workflow  ⛔ *open*

- **Human can:** run a complete, auditable review workflow: assignment → review → sign-off, with a
  full decision trail feeding redaction.
- **Persisted:** immutable decision log, actor/time/reason for every action, review state machine.
- **Needs later DB:** yes.
- **Feedback loop:** full — review outcomes drive both regression metrics and (eventually) redaction.
- **Acceptance:** every de-identification decision is traceable to a reviewer, a reason, and the
  exact artifact lineage; the trail is exportable for audit.

---

## What must be answered before building this engine

The PR spec calls these out explicitly; they are design constraints, not features:

- **What actions can a human take?** confirm, reject, add, comment, and (later) rule-ify — always
  against a specific `pii_result`/`text_result` lineage.
- **What is persisted?** decisions and rules, as a `review_result` overlay; the `pii_result` stays
  immutable.
- **What later needs a DB?** review state, decision history, and rules (lookup/versioning/history).
  See the [DB chapter](target-architecture.md#database-considerations).
- **What can stay file-based for now?** first-cut `review_result` JSON artifacts and small rule
  files under the document-data root — mirroring how audit/OCR/PII artifacts already work.
- **How does feedback improve the PII engine?** rules feed candidate validation (PII L8); corrections
  feed the benchmark (L7). The engine consumes rules at post-processing time — it does not retrain.
- **How is uncontrolled global effect prevented?** every decision/rule has an explicit scope; the
  default scope is the single document; global scope is a deliberate, logged opt-in.

## Where the project stands (Review/Feedback)

| Level | State | Evidence |
| --- | --- | --- |
| 0 Display only | ✅ done | detail page renders text |
| 1 Candidate list | ✅ done | entity list + lineage-safe highlights (`piiHighlights.ts`) |
| 2 Confirm/reject | ⛔ open | no persisted decisions |
| 3 Manual add | ⛔ open | — |
| 4 Reason/comment | ⛔ open | — |
| 5 Suppression rules | ⛔ open | — |
| 6 Reusable decisions | ⛔ open | — |
| 7 Benchmark feedback | ⛔ open | benchmark inputs are hand-authored today |
| 8 Policy-based review | ⛔ open | — |
| 9 Local AI assist | ⛔ open | — |
| 10 Auditable workflow | ⛔ open | — |

**What is missing for the next level (L1 → L2):** a `review_result` artifact model + endpoints to
persist confirm/reject decisions bound to lineage, and UI actions to create them. This is the first
place a **database** becomes genuinely useful (review state and history) — see Engine-6 and Engine-7
in [`roadmap.md`](roadmap.md).
