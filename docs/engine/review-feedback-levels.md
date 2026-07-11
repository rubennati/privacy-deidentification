# Review / Human-Feedback Engine — Levels 0–19

The review engine puts a **human in the loop** over immutable PII labels: inspect, correct, and
eventually *teach* the pipeline — auditable throughout. It is the third sub-engine in the
[north star](README.md#north-star) and the bridge to trustworthy redaction later.

Two constraints shape every level:

- **Lineage safety.** A review decision is always bound to the exact `pii_result` and `text_result`
  it acted on. If text is re-extracted, prior decisions become *stale*, never silently reapplied.
- **Controlled blast radius.** Manual decisions must not silently become global truth. Scope
  (this document / this profile / global) is explicit, and global effects require deliberate opt-in.

Level numbers are cumulative and **not** comparable to the OCR, PII, Benchmark, or Redaction
ladders. This engine uses the **0–19 maturity scale** ([why 0–19](README.md#maturity-scale)); a
mapping from the previous 0–10 ladder is in
[Legacy scale mapping](#legacy-scale-mapping-010--019).

**Current standing:** **L2 solid in production; L3–L5 delivered as dev-only capabilities behind
`ENABLE_DEV_ENGINE_SETTINGS`; L6–L10 delivered.** The detail page renders text, lists candidates with
lineage-safe highlights, offers clickable offsets + a legend, exposes a gated per-run
engine-settings override, and captures **per-entity dev feedback** (analysis input, not learning).
Grouped occurrences (L6, mirroring [PII L11](pii-engine-levels.md#level-11--entity-grouping--repeated-occurrences---done))
are now delivered, paired with a lineage-bound review-decision overlay (every entity defaults to
`pseudonymize`; a reviewer opts one out via `keep` or `false_positive`, at group or occurrence
scope), immutable `review_result` snapshots, direct PII/text lineage for new decisions, and an
explicit stale indicator. See [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)
and [ADR-0034](../adr/0034-review-l8-review-result-artifact.md). **Manual add (L10)** is now
delivered: a reviewer selects a missed span in the canonical reading-text view, tags it with a
type, and it round-trips as a distinct `origin=human` `manual_addition`, never merged into
`pii_result` or the anchor-bound entity contract — see
[ADR-0035](../adr/0035-pii-l14-review-l10-manual-add-scope.md). Actor/reason metadata L11,
suppression rules L12, and reusable cross-run decisions L13 remain open.

> **File note.** The 0–19 review/feedback ladder lives in this file (`review-feedback-levels.md`).
> It is the successor to the previous 0–10 review ladder; there is no separate
> `review-feedback-engine-levels.md`, to keep existing cross-links intact.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Read-only review | 0–2 | Text display, candidate list + lineage-safe highlights |
| Review aids + dev capture | 3–5 | Clickable offsets/legend, dev engine settings, per-entity dev feedback capture |
| Binding review | 6–11 | Grouping, stale detection, `review_result`, confirm/reject, manual add, reason/comment |
| Reusable feedback | 12–16 | Suppression rules, reusable decisions, feedback→regression, policy review, audit trail |
| Assisted & auditable | 17–19 | Local AI assist, multi-user workflow, full auditable human-in-the-loop |

---

## Level 0 — No review

- **Human can:** nothing; the pipeline runs headless.
- **Acceptance:** results exist as artifacts with no review surface.
- **Boundary to L1:** L1 renders the extracted text to a human.

## Level 1 — Read-only text display  ✅ *done*

- **Human can:** open a document and read the extracted text.
- **Persisted:** nothing beyond existing artifacts.
- **Acceptance:** the detail page renders text without mutating anything.
- **Boundary to L2:** L1 shows text; L2 overlays detected candidates.

## Level 2 — Candidate list + lineage-safe highlights  ✅ *done*

- **Human can:** see the list of detected PII candidates and lineage-safe highlights overlaid on the
  text — only when the highlight's input text artifact matches the displayed text.
- **Persisted:** nothing new; the view is read-only.
- **Acceptance:** candidates render with correct Unicode-codepoint offsets; stale/missing lineage is
  surfaced; no HTML injection, no source-text logging.
- **Boundary to L3:** L2 is a static overlay; L3 adds interaction aids.

## Level 3 — Review aids: clickable offsets + legend  ✅ *done*

- **Human can:** click an offset range to scroll/flash the corresponding span in the extracted-text
  view; read a collapsible legend explaining entity types, confidence, and recognizer.
- **Persisted:** nothing.
- **Acceptance:** clicking an entity's offsets highlights the exact span; the legend explains every
  entity type shown.
- **Boundary to L4:** L3 helps read results; L4 exposes engine configuration to a dev reviewer.

## Level 4 — Dev engine settings surface  ✅ *done (gated)*

- **Human can (dev):** with `ENABLE_DEV_ENGINE_SETTINGS=true`, see safe read-only PII defaults from
  `GET /api/config` and override the named PII **profile** for one local PII run only.
- **Persisted:** the override affects a single run; `.env`/backend defaults stay authoritative and
  are never written from the UI. The chosen settings are recorded in `pii_result.engine_settings`
  (PII L9).
- **Acceptance:** with the gate off, no override is possible and defaults apply; with it on, a
  one-run profile override works and is traceable in the artifact.
- **Boundary to L5:** L4 configures a run; L5 captures a human's per-entity verdict on the result.

## Level 5 — Per-entity dev feedback capture  ⏳ *partial — dev-only, current frontier*

- **Human can (dev):** on each entity card, press "Passt" (correct) or pick an issue (with a short
  per-reason explanation) and an optional comment. After submission the card locks to a status line
  so the same feedback is not submitted twice for one entity in one artifact.
- **Persisted (twice):**
  1. Append-only JSONL at `document-store/{document_id}/feedback/pii_feedback.jsonl` — the copy the
     UI reads back to restore per-entity review state. Deleted with the document (ADR-0008).
  2. The same line, unchanged (`document_id` retained), appended to the separate, cross-document
     `pii-feedback-archive/pii_feedback.jsonl` — **not** touched by document deletion, by design
     (see [Level 14](#level-14--feedback-to-regression-workflow--open)).

  Each line carries a timestamp, document/artifact ids, the entity fingerprint (type + offsets +
  recognizer + score), the verdict/issue_type/optional comment, the artifact's engine settings, and
  app/schema version. New feedback is accepted only when type, offsets, and recognizer match an
  entity in the referenced `pii_result`; the stored score comes from that artifact. On load,
  `GET …/pii/feedback?artifact_id=…` collapses the **document-store copy's** validated lines to the
  **latest verdict per entity key** (type + start + end + recognizer) and returns counts/verdicts
  only; the archive is write-only from the API's perspective (no read endpoint yet — read the
  JSONL directly for aggregate analysis, like the private benchmark runner does with its inputs).
- **Privacy boundary:** the structured fingerprint excludes document text, OCR full text, and raw
  entity values. Optional `text_hash` values must be lowercase SHA-256 digests. Comments are short
  reviewer notes: do not copy document text, OCR text, or raw PII into them — this now matters even
  more, since the archive copy is designed to outlive the source document.
- **Gated:** available only when `ENABLE_DEV_ENGINE_SETTINGS=true`; with the gate off, the UI hides
  the controls and both `POST …/pii/feedback` and `GET …/pii/feedback` return `403`; neither copy is
  written.
- **Explicitly not:** a learning system. It never changes detection, never mutates the immutable
  `pii_result`, and applies no rules. It is an **analysis side-channel**, not the binding L8
  `review_result` overlay.
- **Why partial:** production stays gated off; the binding overlay is separate, future work.
- **Acceptance:** with the gate on, a per-entity verdict persists within the documented local
  feedback boundary and is restored + locked on reload; a write also lands in the cross-document
  archive and survives that document's deletion; with the gate off, the endpoints `403` and
  controls are hidden and neither copy is written.
- **Boundary to L6:** L5 captures feedback on a *flat list*; L6 groups repeated occurrences.

### Feedback storage (local dev)

- **Per-document copy:** append-only JSONL under the host side of the existing `document-store` bind
  mount (`volumes/document-store/<document_id>/feedback/pii_feedback.jsonl`; inside the container
  `/data/document-store/<id>/feedback/…`). Created on first write. Survives `docker compose down`
  (host bind mount), removed with the document's directory.
- **Cross-document archive:** append-only JSONL under its own bind mount, `PII_FEEDBACK_ARCHIVE_DIR`
  (default `/data/pii-feedback-archive`, host side `volumes/pii-feedback-archive/pii_feedback.jsonl`).
  A single shared file across all documents — deliberately not partitioned per document, since its
  purpose is aggregate analysis after the source documents (and their own copy) may already be
  gone. Survives `docker compose down` **and** the deletion of any/every document. Configured as a
  root separate from both `UPLOAD_STORAGE_DIR` and `DOCUMENT_DATA_DIR` (rejected at startup if it
  overlaps either).
- Local development/review data: **not** committed (`volumes/` is git-ignored) and never to be
  committed. Use it only for controlled local or aggregate analysis. The structured fingerprint
  contains no document/OCR/entity text, but optional comments remain sensitive input and must not
  contain copied document text or raw PII — in either copy.

## Level 6 — Grouped occurrences  ✅ *done*

- **Human can:** see each distinct entity once with its occurrences/offsets collected beneath it
  (`PERSON Max Mustermann → 0–14, 220–234, 540–554`), with clickable offsets and feedback per
  occurrence or per group.
- **Delivered:** the `PiiReviewGroupList` review panel renders one row per entity group (type,
  occurrence count, reading-text projection coverage, current decision/status) with an expandable
  per-occurrence list; clicking a highlighted span in the text view reveals its group. Grouping
  itself stores nothing new (a derived view over existing detections, see
  [PII L11](pii-engine-levels.md#level-11--entity-grouping--repeated-occurrences---done)); a
  lineage-bound decision overlay is additionally delivered ahead of the later L8/L9 steps — see
  [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).
- **Acceptance:** repeated mentions render as one group with correct per-occurrence offsets and
  jump-to-text; grouping never drops or invents a detection.
- **Boundary to L7:** L6 groups mentions; L7 makes a recorded decision lineage-aware and stale-safe.

## Level 7 — Stale review detection  ✅ *done*

- **Human can:** trust that any recorded feedback/decision is bound to the exact
  `pii_result`/`text_result` it acted on; re-extraction surfaces it as **stale**, never silently
  reapplied.
- **Persisted:** lineage keys on every decision; a stale flag when the input artifact changes.
- **Delivered:** every new decision line records the exact `pii_result.id` and `text_result.id` it
  was made against. `GET …/pii/review` only considers decisions matching the current PII artifact,
  while explicit stale-decision counts surface superseded decisions in the API and UI; no decision
  is ever reapplied automatically. Legacy lines without a direct text id remain readable.
- **Acceptance:** re-running OCR/PII marks prior decisions stale and shows it in the UI; nothing is
  reapplied automatically.
- **Boundary to L8:** L7 protects lineage; L8 introduces the persisted decision overlay itself.

## Level 8 — `review_result` artifact model  ✅ *done*

- **Human can:** have decisions persisted as an overlay (still read-only actions at this level:
  the model + endpoints exist).
- **Persisted:** a `review_result` artifact keyed to `pii_result.id` + `text_result.id`; the
  `pii_result` stays immutable; file-based first (see
  [target-architecture](target-architecture.md#database-considerations)).
- **Delivered:** a file-based, lineage-bound decision overlay exists
  (`document-store/<id>/review/pii_review_decisions.jsonl`, an append-only log collapsed to the
  latest decision per target on read), and an immutable, versioned `review_result` snapshot is
  persisted after every decision. `pii_result` is never mutated; JSONL remains the append-only
  write model while snapshots are the durable read model (ADR-0034).
- **Acceptance:** a `review_result` can be created, stored immutably, referenced by lineage, and
  re-rendered on reload. This is the first place a **database** becomes genuinely useful.
- **Boundary to L9:** L8 is the storage model; L9 adds the first binding action (confirm/reject).

## Level 9 — Confirm / reject  ✅ *done*

- **Human can:** mark a candidate **confirmed** or **rejected**.
- **Delivered:** `POST …/pii/review/decisions` lets a reviewer set a binding decision
  (`pseudonymize/keep/false_positive`, pseudonymize-by-default rather than a plain confirm/reject —
  a reviewer opts an entity *out* of pseudonymization) at group or occurrence scope; it persists,
  restores on reload, and resolves to a coarse `accepted/kept/rejected` status. See
  [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md).
- **Persisted:** per-candidate decisions in `review_result`, with direct `pii_result.id` +
  `text_result.id` lineage on new decision lines and immutable snapshots. Mirrors
  [PII L13](pii-engine-levels.md#level-13--review-confirm--reject---done).
- **Acceptance:** met. A decision persists against exact lineage and re-renders on reload;
  re-extraction marks it stale rather than reapplying it.
- **Boundary to L10:** L9 judges machine candidates; L10 lets a human add a missed one.

## Level 10 — Manual add  ✅ *done*

- **Human can:** select a span the engine missed and add it as a PII entity (with a type).
- **Persisted:** manual additions in `review_result` with canonical-text offsets and `origin = human`.
- **Acceptance:** met. A human-added span round-trips with valid offsets and is distinguishable from
  machine detections (visually, and via `origin: "human"`/its own `manual_additions` list); it
  becomes a missed-entity (recall) signal.
- **Delivered:** a new `manual_addition` record layered on the existing `pii_review_decisions.jsonl`
  log and an additive `PiiReviewResult.manual_additions` list — never merged into `pii_result` or
  the anchor-bound entity contract, since both structurally assume a detector-originated span
  (`AnchorBoundPiiEntityV1.source_observations` requires ≥1 detector observation). Canonical
  offsets are captured against `reading_text`; a best-effort reverse projection to a raw span
  reuses the Text Anchor Graph's existing raw↔canonical pairing (`pii_manual_addition.py`,
  exact/partial/unmapped, never a new matching heuristic). Staleness keys off `text_artifact_id`,
  not a `pii_result` artifact id, since a manual addition has no detector origin to scope against.
  Once created, an addition's own accept/keep/reject reuses the existing decision endpoint
  (`target_type: "manual_addition"`) rather than a new edit/delete action. The frontend adds three
  primitives that didn't exist before: text-selection capture (`getCharacterOffsetsFromSelection`,
  reading-mode only), an entity-type picker sourced from the run's own
  `configured_entity_types`, and a visually distinct highlight ring for human-added spans. See
  [ADR-0035](../adr/0035-pii-l14-review-l10-manual-add-scope.md).
- **Boundary to L11:** L10 records what/where; L11 records *why*.

## Level 11 — Reason / comment  ⛔ *open*

- **Human can:** attach a reason/comment to a confirm/reject/add.
- **Persisted:** reason text + actor + timestamp on each decision.
- **Acceptance:** decisions carry an auditable reason; reasons never contain raw PII beyond the span
  already stored. Feeds FP/FN categories in [quality-metrics](quality-metrics.md#pii-metrics).
- **Boundary to L12:** L11 records single reasons; L12 generalises a repeated decision into a rule.

## Level 12 — Local suppression / allowlist rules  ⛔ *open*

- **Human can:** turn a repeated decision into a scoped rule ("token X is never PERSON in this
  document" / "this label is always a claim number").
- **Persisted:** a scoped rules store (scope + reason + author). Feeds PII candidate validation as a
  post-processing input (not retraining).
- **Acceptance:** a rule applies consistently within its declared scope; a document-scoped rule never
  leaks; global rules require explicit opt-in.
- **Boundary to L13:** L12 defines rules; L13 carries decisions/rules across re-runs deliberately.

## Level 13 — Reusable review decisions  ⛔ *open*

- **Human can:** carry decisions/rules across re-runs and similar documents deliberately.
- **Persisted:** stable decision/rule identity across artifact versions; re-application is explicit
  and logged, never automatic.
- **Acceptance:** re-running OCR/PII offers to re-apply prior decisions with a visible diff; nothing
  is reapplied silently.
- **Boundary to L14:** L13 reuses decisions; L14 exports them into the benchmark ground truth.

## Level 14 — Feedback-to-regression workflow  ⛔ *open*

- **Human can:** promote confirmed/rejected/added decisions into the private benchmark's ground-truth
  signal (locally, privately).
- **Persisted:** review-derived corrections exported under `volumes/benchmark/` (never committed).
  The L5 `pii-feedback-archive` (survives document deletion, cross-document) is the raw input this
  level would draw from; L14 itself is the still-open step that turns those entries into curated
  benchmark ground truth. Mirrors [PII L15](pii-engine-levels.md#level-15--feedback-derived-regression-sets---open).
- **Acceptance:** a reviewer can turn corrections into private benchmark data without exporting any
  PII outside `volumes/`.
- **Boundary to L15:** L14 improves the ground truth; L15 governs review by policy.

## Level 15 — Policy / profile-based review  ⛔ *open*

- **Human can:** review under a policy (e.g. GDPR/insurance) that defines which types *must* be
  reviewed, with required-field checks and sign-off.
- **Persisted:** policy + per-policy review completeness in `review_result`; ties to a
  [PII profile](pii-engine-levels.md#profiles-the-configuration-axis).
- **Acceptance:** review completeness is measurable against a named policy before a document counts as
  "reviewed".
- **Boundary to L16:** L15 measures completeness; L16 makes the whole trail exportable/auditable.

## Level 16 — Review audit trail / export  ⛔ *open*

- **Human can:** export an auditable trail of every decision (actor/time/reason/lineage).
- **Persisted:** an immutable decision log exportable for audit.
- **Acceptance:** every decision is traceable to actor, reason, and exact artifact lineage; the trail
  exports without leaking raw PII beyond stored spans.
- **Boundary to L17:** L16 records human decisions; L17 adds assistive machine suggestions.

## Level 17 — Local AI review assist  ⛔ *open, optional*

- **Human can:** get **local**, assistive suggestions ("likely false positive", "possible missed
  person") that speed review — never auto-applied.
- **Persisted:** assist suggestions flagged `assistive = true`, distinct from human decisions.
- **Acceptance:** suggestions are local, labelled, and only change state through an explicit human
  action. See the
  [local-AI chapter](target-architecture.md#optional-local-ai--vision--document-understanding).
- **Boundary to L18:** L17 assists one reviewer; L18 coordinates several.

## Level 18 — Multi-user assignment / workflow state  ⛔ *open*

- **Human can:** be assigned documents; the system tracks review state across reviewers.
- **Persisted:** assignment + review state machine (needs a DB in practice).
- **Acceptance:** documents move through assigned → in-review → reviewed with per-user attribution.
- **Boundary to L19:** L18 coordinates work; L19 closes the loop to sign-off and redaction.

## Level 19 — Auditable human-in-the-loop workflow  ⛔ *open*

- **Human can:** run a complete, auditable review workflow: assignment → review → sign-off, with a
  full decision trail feeding redaction.
- **Persisted:** immutable decision log, actor/time/reason for every action, review state machine.
- **Acceptance:** every de-identification decision is traceable to a reviewer, a reason, and the exact
  artifact lineage; the trail is exportable for audit and drives
  [Redaction](redaction-engine-levels.md).
- **Boundary:** top of the ladder; further work is workflow/UX refinement within this envelope.

---

## What must be answered before building the binding overlay

Design constraints (not features) for L8+:

- **What actions can a human take?** confirm, reject, add, comment, and (later) rule-ify — always
  against a specific `pii_result`/`text_result` lineage.
- **What is persisted?** decisions and rules, as a `review_result` overlay; the `pii_result` stays
  immutable.
- **What later needs a DB?** review state, decision history, and rules (lookup/versioning/history).
  See the [DB chapter](target-architecture.md#database-considerations).
- **What can stay file-based for now?** first-cut `review_result` JSON artifacts and small rule files
  under the document-store root — mirroring how audit/OCR/PII artifacts already work.
- **How does feedback improve the PII engine?** rules feed candidate validation (PII post-processing);
  corrections feed the benchmark. The engine consumes rules at post-processing time — it does not
  retrain.
- **How is uncontrolled global effect prevented?** every decision/rule has an explicit scope; default
  scope is the single document; global scope is a deliberate, logged opt-in.

## Where the project stands (Review/Feedback)

| Level | State | Evidence |
| --- | --- | --- |
| 0 No review | n/a | — |
| 1 Read-only text display | ✅ done | detail page renders text |
| 2 Candidate list + highlights | ✅ done | entity list + lineage-safe highlights (`piiHighlights.ts`) |
| 3 Review aids (offsets + legend) | ✅ done | clickable offsets jump/flash; entity-type legend |
| 4 Dev engine settings surface | ✅ done (gated) | `GET /api/config` PII defaults + `ENABLE_DEV_ENGINE_SETTINGS` per-run profile override |
| 5 Per-entity dev feedback capture | ⏳ partial (dev-only) | append-only JSONL, latest-verdict restore + lock; analysis-only |
| 6 Grouped occurrences | ✅ done | `PiiReviewGroupList` + derived `pii_grouping.py` ([ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) |
| 7 Stale review detection | ✅ done | direct PII/text lineage for new decisions, explicit stale API/UI state, never automatic reapply |
| 8 `review_result` model | ✅ done | immutable, versioned snapshot after every decision; JSONL remains append-only write model |
| 9 Confirm / reject | ✅ done | pseudonymize-by-default `pseudonymize/keep/false_positive` decisions at group/occurrence scope |
| 10 Manual add | ✅ done | `manual_addition` record + `manual_additions` list ([ADR-0035](../adr/0035-pii-l14-review-l10-manual-add-scope.md)) |
| 11 Reason / comment | ⛔ open | — |
| 12 Suppression rules | ⛔ open | — |
| 13 Reusable decisions | ⛔ open | — |
| 14 Feedback → regression | ⛔ open | benchmark inputs hand-authored today |
| 15 Policy-based review | ⛔ open | — |
| 16 Audit trail / export | ⛔ open | — |
| 17 Local AI review assist | ⛔ open | — |
| 18 Multi-user workflow | ⛔ open | — |
| 19 Auditable workflow | ⛔ open | — |

**What is missing for the next real step:** actor/reason metadata (L11), scoped suppression rules
(L12), and reusable cross-run decisions (L13); see the
[later engine work](roadmap.md#later-engine-work) in the roadmap.

---

## Legacy scale mapping (0–10 → 0–19)

The engine previously used a 0–10 ladder. The new scale splits the former "candidate list" level
into read-only + review-aid + dev-capture levels and expands the tail.

| Old (0–10) | Meaning | New (0–19) |
| --- | --- | --- |
| L0 Display only | read text | **L1** |
| L1 Candidate list | list + highlights (+ dev feedback side-channel) | **L2** (+ **L3–L5** aids/dev/feedback) |
| L2 Confirm / reject | binding decision | **L8** model + **L9** confirm/reject |
| L3 Manual add | add missed span | **L10** |
| L4 Reason / comment | decision reason | **L11** |
| L5 Suppression / allowlist rules | scoped rules | **L12** |
| L6 Reusable review decisions | reuse across runs | **L13** |
| L7 Benchmark feedback | feed ground truth | **L14** |
| L8 Policy / policy-based review | policy coverage | **L15** |
| L9 Local AI review assist | assistive suggestions | **L17** |
| L10 Auditable workflow | full trail + sign-off | **L19** (+ **L16** audit export, **L18** multi-user) |

New levels with no old equivalent: **L3** (clickable offsets + legend), **L4** (dev engine settings
surface), **L5** (per-entity dev feedback capture), **L6** (grouped occurrences), **L7** (stale
review detection).
