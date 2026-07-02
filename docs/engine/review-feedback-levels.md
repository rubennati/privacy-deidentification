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
`ENABLE_DEV_ENGINE_SETTINGS`.** The detail page renders text, lists candidates with lineage-safe
highlights, offers clickable offsets + a legend, exposes a gated per-run engine-settings override,
and captures **per-entity dev feedback** (analysis input, not learning). The binding review overlay
(`review_result`), entity grouping, confirm/reject, and manual add are **open** — the next real step
is the L8 `review_result` model.

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
- **Persisted:** append-only JSONL at `document-data/{document_id}/feedback/pii_feedback.jsonl`. Each
  line carries a timestamp, document/artifact ids, the entity fingerprint (type + offsets +
  recognizer + score), the verdict/issue_type/optional comment, the artifact's engine settings, and
  app/schema version. New feedback is accepted only when type, offsets, and recognizer match an
  entity in the referenced `pii_result`; the stored score comes from that artifact. On load,
  `GET …/pii/feedback?artifact_id=…` collapses validated lines to the **latest verdict per entity
  key** (type + start + end + recognizer) and returns counts/verdicts only.
- **Privacy boundary:** the structured fingerprint excludes document text, OCR full text, and raw
  entity values. Optional `text_hash` values must be lowercase SHA-256 digests. Comments are short
  reviewer notes: do not copy document text, OCR text, or raw PII into them. The JSONL remains
  protected document data.
- **Gated:** available only when `ENABLE_DEV_ENGINE_SETTINGS=true`; with the gate off, the UI hides
  the controls and both `POST …/pii/feedback` and `GET …/pii/feedback` return `403`.
- **Explicitly not:** a learning system. It never changes detection, never mutates the immutable
  `pii_result`, and applies no rules. It is an **analysis side-channel**, not the binding L8
  `review_result` overlay.
- **Why partial:** production stays gated off; the binding overlay is separate, future work.
- **Acceptance:** with the gate on, a per-entity verdict persists within the documented local
  feedback boundary and is restored + locked on reload; with the gate off, the endpoints `403` and
  controls are hidden.
- **Boundary to L6:** L5 captures feedback on a *flat list*; L6 groups repeated occurrences.

### Feedback storage (local dev)

- Append-only JSONL under the host side of the existing `document-data` bind mount
  (`volumes/document-data/<document_id>/feedback/pii_feedback.jsonl`; inside the container
  `/data/document-data/<id>/feedback/…`). No separate Docker volume; created on first write.
- Survives `docker compose down` (host bind mount), removed with the document's directory.
- Local development/review data: **not** committed (`volumes/` is git-ignored) and never to be
  committed. Use it only for controlled local or aggregate analysis. The structured fingerprint
  contains no document/OCR/entity text, but optional comments remain sensitive input and must not
  contain copied document text or raw PII.

## Level 6 — Grouped occurrences  ⛔ *open (next)*

- **Human can:** see each distinct entity once with its occurrences/offsets collected beneath it
  (`PERSON Max Mustermann → 0–14, 220–234, 540–554`), with clickable offsets and feedback per
  occurrence or per group.
- **Persisted:** nothing new (a UI grouping over existing detections); detection is unchanged.
- **Acceptance:** repeated mentions render as one group with correct per-occurrence offsets and
  jump-to-text; grouping never drops or invents a detection. Mirrors
  [PII L11](pii-engine-levels.md#level-11--entity-grouping--repeated-occurrences---open-next).
- **Boundary to L7:** L6 groups mentions; L7 makes a recorded decision lineage-aware and stale-safe.

## Level 7 — Stale review detection  ⛔ *open*

- **Human can:** trust that any recorded feedback/decision is bound to the exact
  `pii_result`/`text_result` it acted on; re-extraction surfaces it as **stale**, never silently
  reapplied.
- **Persisted:** lineage keys on every decision; a stale flag when the input artifact changes.
- **Acceptance:** re-running OCR/PII marks prior decisions stale and shows it in the UI; nothing is
  reapplied automatically.
- **Boundary to L8:** L7 protects lineage; L8 introduces the persisted decision overlay itself.

## Level 8 — `review_result` artifact model  ⛔ *open (first binding step)*

- **Human can:** have decisions persisted as an overlay (still read-only actions at this level:
  the model + endpoints exist).
- **Persisted:** a `review_result` artifact keyed to `pii_result.id` + `text_result.id`; the
  `pii_result` stays immutable; file-based first (see
  [target-architecture](target-architecture.md#database-considerations)).
- **Acceptance:** a `review_result` can be created, stored immutably, referenced by lineage, and
  re-rendered on reload. This is the first place a **database** becomes genuinely useful.
- **Boundary to L9:** L8 is the storage model; L9 adds the first binding action (confirm/reject).

## Level 9 — Confirm / reject  ⛔ *open*

- **Human can:** mark a candidate **confirmed** or **rejected**.
- **Persisted:** per-candidate decisions in `review_result`. Mirrors
  [PII L13](pii-engine-levels.md#level-13--review-confirm--reject---open).
- **Acceptance:** a decision persists against the exact lineage and re-renders on reload;
  re-extraction marks it stale rather than reapplying it.
- **Boundary to L10:** L9 judges machine candidates; L10 lets a human add a missed one.

## Level 10 — Manual add  ⛔ *open*

- **Human can:** select a span the engine missed and add it as a PII entity (with a type).
- **Persisted:** manual additions in `review_result` with canonical-text offsets and `origin = human`.
- **Acceptance:** a human-added span round-trips with valid offsets and is distinguishable from
  machine detections; it becomes a missed-entity (recall) signal.
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
  Mirrors [PII L15](pii-engine-levels.md#level-15--feedback-derived-regression-sets---open).
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
  under the document-data root — mirroring how audit/OCR/PII artifacts already work.
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
| 6 Grouped occurrences | ⛔ open (next) | documented follow-up; flat list today |
| 7 Stale review detection | ⛔ open | lineage surfaced for highlights; no decision store yet |
| 8 `review_result` model | ⛔ open | no persisted decision overlay |
| 9 Confirm / reject | ⛔ open | — |
| 10 Manual add | ⛔ open | — |
| 11 Reason / comment | ⛔ open | — |
| 12 Suppression rules | ⛔ open | — |
| 13 Reusable decisions | ⛔ open | — |
| 14 Feedback → regression | ⛔ open | benchmark inputs hand-authored today |
| 15 Policy-based review | ⛔ open | — |
| 16 Audit trail / export | ⛔ open | — |
| 17 Local AI review assist | ⛔ open | — |
| 18 Multi-user workflow | ⛔ open | — |
| 19 Auditable workflow | ⛔ open | — |

**What is missing for the next real step (→ L6/L8):** entity **grouping** (L6, the documented next
review level) and the binding `review_result` overlay (L8) with confirm/reject (L9) bound to
lineage. This is the first place a **database** becomes genuinely useful; see the
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
