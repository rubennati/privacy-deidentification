# ADR-0031: Text Identity, Anchor Lineage, and De-Identification State Architecture

## Status

**Proposed** — 2026-07-09. **Design / architecture only.** This ADR introduces **no** schema code,
service, API endpoint, database, migration, frontend change, OCR change, PII change,
pseudonymization, reconstruction, or runtime change. It defines the target *identity layer* that
later, separately-approved phases (see [Staged plan](#13-staged-implementation-plan)) implement one
small PR at a time.

> **ADR number note.** The task brief asked for `0030-text-identity-anchor-lineage-architecture.md`,
> but `0030` was already taken by
> [ADR-0030](0030-runtime-job-ux-notifications-v1.md) (Runtime Job UX). This design therefore lands
> as **ADR-0031**.

This builds on and makes concrete the still-open `text_lineage_map` from the
[OCR/Layout text contract](../engine/ocr-layout-text-contract.md#6-lineage-map), and extends
[ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 scale),
[ADR-0018](0018-ocr-pii-implementation-plan.md) (OCR stays ahead of PII),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md) (technical-raw vs
canonical-reading contract),
[ADR-0027](0027-ocr-output-contract-v1-strategy.md) (Document Text Package),
[ADR-0028](0028-pii-intake-document-text-package-v1.md) (PII intake + overlap resolution), and
[ADR-0029](0029-pii-review-ready-entity-contract.md) (review-ready entity contract). It is the
design substrate for **PII L17 — "Stable entity model with lineage"**
([`pii-engine-levels.md`](../engine/pii-engine-levels.md)) and for any future Redaction/
Pseudonymization/Reconstruction engine.

## Product North Star and Golden Path

**North Star.** This system is **not** "OCR plus PII detection." It is a **local-first
de-identification pipeline** whose purpose is to make document information **stable, reviewable,
replaceable, and reconstructable** — so a document can be pseudonymized locally, sent to an external
AI, and have the AI's output **re-identified locally when policy allows**. Originals never leave the
machine; only pseudonymized renders do. The text-anchor identity layer this ADR defines is the spine
that makes that round-trip consistent and reversible.

**Golden Path.** Every capability below serves one end-to-end flow:

> Source document → **OCR/Text Package** ([ADR-0027](0027-ocr-output-contract-v1-strategy.md)) →
> **Text Anchor Identity Layer** → **PII Detection + Entity Binding** → **Review Decision** →
> **Replacement Plan** → **Pseudonymized Render** → **External AI usage** *(only pseudonymized
> surrogates cross this boundary)* → **Reconstruction Map / re-identification, if allowed**.

The **External-AI boundary** is the privacy line: pseudonymized surrogates (`PERSON_001`, …) cross
it; originals and the reconstruction map never do. Anchor identity is what keeps every stage before
and after that boundary referring to the *same* information unit, so the round-trip is deterministic
rather than a fuzzy re-match.

## 1. Context

OCR/Text produces several text layers for one document: **Technical Raw Text** (`text_result.text`,
the authoritative offset system and today's only active PII input), **Canonical Reading Text**
(`reading_text`), **Layout Text** (`layout_text_result`), and **Structured Content**
(`structured_content`) — now packaged behind the **Document Text Package v1**
([ADR-0027](0027-ocr-output-contract-v1-strategy.md)). Today those layers are tied together only by a
best-effort, offset-only, partial `reading_text_map` (`exact`/`normalized`/`partial`) plus an
in-memory unique-value text-match fallback, and by line-level `text_geometry` (raw span → page box).
The full married model — the `text_lineage_map` the contract has always reserved as "no islands"
work — is **not built**.

PII detects on raw text, resolves overlaps ([ADR-0028](0028-pii-intake-document-text-package-v1.md)),
and is surfaced review-ready with a **stable `entity_id`** (a hash of `document_id` + `entity_type` +
raw span) and an explicit per-entity `mapping_status`
(`exact`/`projected`/`partial`/`missing`/`ambiguous`/`not_applicable`)
([ADR-0029](0029-pii-review-ready-entity-contract.md)). Review decisions live in a lineage-bound
JSONL overlay keyed to the exact `pii_result.id`
([ADR-0021](0021-pii-entity-grouping-and-review-decisions.md)).

A concrete symptom triggered this review: **the same entity can be highlighted in the raw view but
not (or differently) in the canonical reading view.** The frontend builds highlights per string
(`buildHighlightSegments`) from that view's offsets; raw uses authoritative raw offsets, canonical
depends on the partial projection, so a `missing`/`partial`/`ambiguous` projection simply disappears
or shifts in the canonical view. This is **not** a highlight-rendering bug to patch in the UI.

## 2. Problem

**The system treats Technical Raw Text, Canonical Reading Text, and Layout Text as independent
strings that happen to be projected onto each other, rather than as different *views* of the same
underlying document information.** There is no first-class object that says *"this information unit is
the same thing in every view."* Consequences that compound downstream:

- **Cross-view inconsistency** (the observed highlight divergence) is inherent, not incidental: a
  view without a projected range has no way to know an entity belongs to it.
- **Missing/ambiguous mapping is resolved *at the edge*** (dropped from a view, or guessed by a
  unique-value match) instead of being a *stable, visible state* of a shared identity.
- **Identity is keyed to raw offsets**, so it is fragile to any future change in the authoritative
  layer and cannot express "detected in canonical, unmapped in raw."
- **Pseudonymization has no substrate.** Blind string replacement ("paint over the text") cannot be
  correct across views and cannot survive reconstruction.
- **Reconstruction has no substrate.** Restoring `PERSON_001` in a later AI output by fuzzy-matching
  private text is both unsafe and unreliable.

The fix is a **stable text identity layer** — an anchor graph — that every view, every PII entity,
every review decision, every replacement, and every reconstruction references.

## 3. Decision direction

Adopt a **text-anchor identity model** as the core of the system, owned by the OCR/Text /
Document-Text layer and consumed by everyone else:

1. **Text anchor = the stable identity of one document information unit** (a word/token/value/logical
   unit). It is created by OCR/Text from the Document Text Package, not by PII.
2. **Anchor graph (`text_anchor_map`)** generalizes today's `reading_text_map` + `text_geometry`:
   each anchor exposes **zero, one, or many ranges per view** plus optional source geometry. Missing
   mapping is **explicit**; ambiguous mapping is **explicit**; neither is silently dropped or guessed.
3. **PII binds entities to anchors, not to string offsets.** Detection may run on any view; every
   result resolves to an anchor set; raw offsets remain the authoritative coordinate expression of an
   anchor.
4. **Review operates over stable entities** (which point to anchors). A decision changes entity
   status; it never mutates raw/canonical/layout text.
5. **Pseudonymization renders output from accepted entities + anchors + replacement decisions.** It
   generates a new document from decisions; it never blind-replaces strings.
6. **Reconstruction maps placeholder → replacement group → entity → anchor → original value** via
   stored mappings, never fuzzy matching of private text.
7. **Persistence is hybrid (Option E):** immutable OCR/Text/anchor artifacts stay JSON; mutable,
   queryable de-identification state (entities-as-reviewed, review decisions, replacement plans,
   reconstruction map, audit) moves to **SQLite** when Review persistence needs it. The conceptual
   model is designed **SQLite-ready now**; no database is built by this ADR.

### Core principle

> **Text views are projections of stable document information units.
> Offsets are view-specific. Anchor identity is shared.**

Everything below follows from that one sentence.

## 4. Conceptual model

The layer boundary is: **OCR/Text owns document information and its views + anchors; PII and
downstream own *decisions about* those anchors.**

| Term | What it is | Owner | Mutability |
| --- | --- | --- | --- |
| **Source document** | the byte-identical original upload (`original_artifact`) | Upload | immutable |
| **OCR/Text artifact** | `text_result`: extraction + all derived text layers | OCR/Text | immutable per run |
| **Technical Raw Text** | `text_result.text`: authoritative extraction, the offset coordinate system, current active PII input | OCR/Text | immutable |
| **Canonical Reading Text** | `reading_text`: deterministic, block-aware human/AI reading view | OCR/Text | immutable per run |
| **Layout Text** | `layout_text_result`: visual-structure reconstruction (display) | OCR/Text | immutable per run |
| **Structured Content** | `structured_content`: tables/fields/sections referencing spans | OCR/Text | immutable per run |
| **DocumentTextPackageV1** | versioned package of all the above + status (ADR-0027) | OCR/Text | derived, not persisted |
| **Text identity** | the abstract fact that a unit of information is "the same thing" across views | OCR/Text (Anchor layer) | conceptual |
| **Text anchor** | the concrete, stable id of a text identity within one document run | OCR/Text (Anchor layer) | immutable per run |
| **Anchor graph (`text_anchor_map`)** | anchors + their per-view ranges + geometry + mapping states | OCR/Text (Anchor layer) | immutable per run (derived) |
| **Anchor range (source range)** | one `[start,end)` occurrence of an anchor **in a named view** (raw/canonical/layout/structured), optionally with page + geometry | OCR/Text | immutable per run |
| **Anchor group** | a *derived* grouping of anchors that carry the same normalized value (e.g. one person named 3×) — never a global merge of identical strings | Anchor layer / PII | derived |
| **PII candidate** | a raw detector hit before validation/overlap resolution | PII | transient |
| **PII entity** | a validated, overlap-resolved detection, expressed in raw offsets + provenance (`pii_result`) | PII | immutable per run |
| **Entity → anchors (`entity_anchors`)** | the binding from a PII entity to the anchor set it covers | PII | derived → later persisted |
| **Review-ready entity** | the entity presented for review with stable `entity_id`, mapping status, display model (ADR-0029) | PII | derived |
| **Review decision** | a reviewer's `pseudonymize`/`keep`/`false_positive` intent, keyed to entity identity | Review | mutable (append-only overlay → later SQLite) |
| **Replacement group** | a set of entities that must receive the **same** placeholder (e.g. every mention of one person) | Pseudonymization | future, mutable |
| **Replacement token / placeholder** | the rendered surrogate, e.g. `PERSON_001`, `ADDRESS_001`, `DATE_001` | Pseudonymization | future |
| **Pseudonymized render** | a generated output document/view built from accepted entities + anchors + tokens | Pseudonymization | future, immutable per render |
| **Reconstruction map** | placeholder → replacement group → entity → anchor → original value, access-gated | Reconstruction | future, mutable, access-controlled |

**Anchor granularity is deliberately open (a deferred decision, [§14](#14-deferred-decisions)):**
v1 can anchor at the **span/value unit** a PII entity needs (the smallest reliable unit today), with
word-level anchoring as a later refinement once `text_geometry` word boxes exist. The *contract* — a
stable id with per-view ranges and explicit mapping states — is independent of the chosen grain.

## 5. Architecture invariants

These hold for any implementation of this model:

1. **One stable anchor identity per information unit, where the unit can be reliably established.**
   Where it cannot, the anchor is still created with an explicit `unresolved`/`ambiguous` state — it
   is never omitted.
2. **A view may expose zero, one, or many ranges for an anchor.** Zero ranges in a view is a valid,
   first-class state (`missing_in_<view>`), not an error and not a reason to drop the anchor.
3. **Missing mapping is explicit, never silent.** An anchor absent from canonical text is recorded as
   `missing`, surfaced, and reviewable — never hidden.
4. **Ambiguous mapping is explicit, never guessed.** If a value maps to more than one candidate range
   in a view, the state is `ambiguous`; the system does not pick one silently.
5. **Repeated identical words are not globally married.** Two occurrences of the same string are two
   anchors unless a *derived* anchor-group step (value normalization + provenance) links them; string
   equality alone never merges identity. This preserves today's conservative
   [entity-grouping](0021-pii-entity-grouping-and-review-decisions.md) discipline.
6. **PII binds to anchors/entities, not only string offsets.** Raw offsets remain the authoritative
   *expression* of an anchor, but the durable reference downstream is anchor/entity identity.
7. **Technical Raw Text stays the offset authority and is never mutated.** Anchors and all views map
   *back* to it; the [separation gate](../engine/ocr-layout-text-contract.md#invariants) for changing
   the active PII detection input is unchanged by this ADR.
8. **Canonical text is never authoritative.** A missing canonical mapping never suppresses an entity
   (consistent with [ADR-0029](0029-pii-review-ready-entity-contract.md)).
9. **Pseudonymization renders from decisions, never blind string replacement.** No stage "paints
   over" text.
10. **Reconstruction uses placeholder mappings, never fuzzy text matching** of private values.
11. **Immutable artifacts are never mutated.** OCR/Text artifacts and the anchor graph are append-only
    per run; a re-run creates a new run and marks downstream state stale, never rewrites.
12. **No raw text crosses a metrics/lineage boundary it does not already cross.** Anchor ranges are
    offsets/ids/states; the anchor graph carries no new copied text beyond the text layers that
    already legitimately hold it.
13. **Private text is not duplicated into metadata.** Entity/anchor/review/replacement/audit metadata
    stores ids, offsets, fingerprints, states, and reason codes; free-form notes must not copy
    document text. The reconstruction map is the only new store that may hold original values, and it
    is isolated, access-gated, audited, and deletable.

## 6. Ownership matrix

| Layer | Creates | Persists | Consumes | Must never mutate |
| --- | --- | --- | --- | --- |
| **OCR/Text** | text layers, `text_result` | immutable `text_result` artifacts (JSON) | Document Text Package | prior artifacts |
| **Document Text Package** | versioned package + status | nothing (derived) | `text_result` | source artifact |
| **Text Anchor Layer** | **anchors + anchor graph (`text_anchor_map`)** | anchor graph (JSON now, SQLite-indexable later) | Document Text Package | text layers, raw offsets |
| **PII Detection** | candidates → entities (`pii_result`) | immutable `pii_result` | raw text (primary), anchors (binding) | text layers, anchor graph |
| **PII Entity Binding** | `entity_anchors` (entity ↔ anchor set) | derived now → persisted later | anchors + entities | anchors, entities' offsets |
| **Review** | review decisions | append-only overlay now → SQLite later | review-ready entities (stable id) | text, anchors, `pii_result` |
| **Pseudonymization** | replacement groups + tokens + renders | replacement plan + renders (later) | accepted entities + anchors | entities, anchors, source text |
| **Reconstruction** | reconstruction map | reconstruction map (SQLite, access-gated) | replacement plan + entities + anchors | everything upstream |
| **Runtime / Jobs** | job lifecycle metadata | SQLite (metadata only, ADR-0023) | job status | any artifact payload |
| **Frontend / UI** | nothing durable | local UI cache only (ADR-0030) | review-ready entities + anchor states | all server state |

**Explicit answers:**

- **Who creates anchors?** The **Text Anchor Layer inside OCR/Text**, derived from the Document Text
  Package. (See [§7](#7-who-owns-the-anchor-graph).)
- **Who persists anchors?** OCR/Text — as a derived JSON layer/artifact now; index/query moves to
  SQLite later without changing the contract.
- **Who consumes anchors?** PII (binding), Review (display consistency), Pseudonymization (render),
  Reconstruction (reverse map), and any future non-PII consumer (analysis/export/AI).
- **Who owns PII entities?** PII (`pii_result`, immutable).
- **Who owns review decisions?** Review (overlay now, SQLite later).
- **Who owns replacement plans?** Pseudonymization.
- **Who owns reconstruction mappings?** Reconstruction (access-controlled).
- **Which layers must never mutate prior artifacts?** All of them — OCR/Text artifacts, the anchor
  graph, `pii_result`, and any render are append-only per run; only *overlay/decision/plan* state is
  mutable, and it references immutable artifacts by id.

## 7. Who owns the anchor graph?

**Recommendation: the anchor graph is owned by the OCR/Text / Document-Text layer, not PII.** PII
*binds* entities to anchors; it does not invent them.

Rationale:

- **OCR/Text is the earliest point where raw/canonical/layout/structured are created**, and it is the
  only layer that knows *how* each view was derived (positions, geometry, reconstruction strategy). It
  already produces `reading_text_map` and `text_geometry` — the anchor graph is the natural
  generalization of those, not a new concern.
- **PII should consume text identity, not reconstruct it after the fact.** If PII built anchors, every
  other consumer (Review, pseudonymization, analysis, export, local AI) would either duplicate that
  logic or depend on PII — inverting the [ADR-0018](0018-ocr-pii-implementation-plan.md) boundary
  where OCR stays ahead of and independent from PII.
- **Future non-PII consumers benefit equally.** Invoice/contract analysis, summarization, and export
  all need "the same value across views"; that is a document-understanding capability, so it belongs
  with OCR/Text.
- **PII still enriches anchors** with entity bindings (`entity_anchors`) — that is the correct
  division: OCR/Text says *what the units are*; PII says *which units are sensitive*.

This keeps the contract clean: **OCR/Text → anchors (identity) → PII (binding) → Review (decision) →
Pseudonymization (render) → Reconstruction (reverse map).**

## 8. Persistence strategy

| Option | Shape | Verdict |
| --- | --- | --- |
| **A** | JSON artifacts only, forever | Rejected long-term. Fine for immutable detection; can't cross-query or version review/replacement/reconstruction state. |
| **B** | Anchor graph JSON + PII/review/replacement JSON | Good for *now*; JSON overlays already strain (JSONL review overlay, latest-per-target on read). Doesn't scale to reconstruction/audit queries. |
| **C** | Per-document SQLite under document-store | Rejected. Clean deletion, but no cross-document query, N databases to back up/migrate, and reconstruction/audit are inherently cross-document. |
| **D** | One shared SQLite for *all* identity + de-id state, incl. text | Rejected. Pulls large immutable raw text into a DB, muddying the "raw artifacts stay files" invariant and privacy boundary. |
| **E** | **Hybrid: immutable OCR/Text/anchor artifacts as JSON; mutable/queryable PII-review/replacement/reconstruction/audit state in SQLite** | **Recommended.** |

**Why E.** It matches the grain of the data and the invariants:

- *Simplicity / local-first:* immutable extraction stays zero-ops files; only genuinely mutable,
  queryable state needs a DB — exactly what
  [`target-architecture.md`](../engine/target-architecture.md#when-does-a-database-become-worthwhile)
  already concludes ("a DB becomes worthwhile once review decisions and rules must be listed,
  searched, versioned, and reapplied").
- *Portability / reproducibility:* JSON artifacts remain byte-reproducible and diff-able; SQLite is a
  single portable file that co-locates with `volumes/` (job state already does this, ADR-0023).
- *Queryability / audit:* replacement plans, reconstruction lookups, and audit events are relational
  and cross-document — SQL, not scattered JSONL.
- *Deletion / privacy:* per-document rows are deleted with the document boundary (as job rows already
  are); large raw text never enters the DB, so the DB stays low-sensitivity metadata + decisions +
  offsets/ids. The reconstruction map (which *does* hold original values) is a separate,
  access-gated, deletable table.
- *Backup / multi-user later:* SQLite-first, PostgreSQL-later stays open (already the stated
  direction) without re-modeling.

**Phased recommendation:**

- **Now:** anchor graph as an **immutable derived JSON layer** on/beside `text_result` (Option B-ish),
  reusing the existing `reading_text_map` + `text_geometry` inputs. Keep the review overlay as-is.
  **No DB.**
- **Near-term:** define the SQLite-ready **relational shape** ([§9](#9-future-data-model)) and move
  **review decisions** into it when the formal `review_result` model lands (Review L8) — the first
  state that genuinely needs list/search/version/reapply.
- **Later:** add **replacement plans**, **reconstruction map**, and **audit events** tables as those
  engines are built. Never introduce the DB before the data model is proven; never fuse immutable text
  artifacts into it.

The design goal is that **SQLite can be introduced cleanly later** — every conceptual entity below is
already expressible as either a JSON artifact (immutable) or a table (mutable) with a stable key.

## 9. Future data model (conceptual — not implemented)

Design only. "Artifact" = immutable JSON today; "Table" = SQLite when persistence lands.

| Entity | Purpose | Owner | Key fields | Mut. | Store | Privacy | Consumers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `documents` | document registry | Upload | `document_id`, created_at | mutable index | Table (later) / `document.json` today | filename may be sensitive | all |
| `document_text_packages` | which text run is current | OCR/Text | `package_id`, `text_artifact_id`, `contract_status` | immutable per run | Artifact | packages existing text | anchors, PII |
| `text_sources` | the named views (raw/canonical/layout/structured) of a run | OCR/Text | `source_id`, role, `text_artifact_id` | immutable | Artifact | holds text (already) | anchors, UI |
| `text_anchors` | **stable identity of a unit** | Anchor layer | `anchor_id`, `document_id`, `run_id`, kind, `resolution_state` | immutable per run | Artifact → indexable Table | ids/states only | all |
| `anchor_ranges` | one occurrence in one view | Anchor layer | `anchor_id`, `source_id`, `start`, `end`, `page`, `mapping_status` | immutable per run | Artifact → Table | offsets only | all |
| `anchor_groups` | derived same-value grouping | Anchor/PII | `group_id`, `normalized_fingerprint` (hash) | derived | computed | **hash only, never the value** | Review, pseudo. |
| `pii_candidates` | pre-resolution detector hits | PII | transient | transient | in-memory | spans | PII only |
| `pii_entities` | resolved detections | PII | `pii_result.id`, entity ids, raw span, provenance | immutable per run | Artifact (`pii_result`) | spans (sensitive) | Review, pseudo. |
| `entity_anchors` | entity ↔ anchor set binding | PII | `entity_id`, `anchor_id`, `source_role` | derived → Table | derived now | ids only | Review, pseudo. |
| `review_decisions` | reviewer intent per entity/group | Review | `entity_id`/`group_id`, decision, scope, actor, `pii_result.id` | **mutable** | JSONL overlay → **Table** | offsets/ids + optional no-copy free note | pseudo. |
| `replacement_groups` | entities sharing one placeholder | Pseudo. | `replacement_group_id`, entity_type, member `entity_id`s | mutable | Table (later) | ids | pseudo., reconstruction |
| `replacement_tokens` | the surrogate string | Pseudo. | `replacement_group_id`, `token` (`PERSON_001`), policy | mutable | Table (later) | token is non-sensitive | render, reconstruction |
| `rendered_outputs` | generated pseudonymized documents/views | Pseudo. | `render_id`, `pii_result.id`, plan id | immutable per render | Artifact/file | contains surrogates, not originals | export, UI |
| `reconstruction_map` | placeholder → original value | Reconstruction | `token`, `replacement_group_id`, `entity_id`, `anchor_id`s, **original value repr**, approval, access policy | **mutable, gated** | **Table (access-controlled)** | **holds originals — most sensitive; deletable** | authorized reconstruction only |
| `audit_events` | who did what, when, why | cross-cutting | `event_id`, actor, action, target ids, timestamp | append-only | Table (later) | ids/actions, no raw text | audit/compliance |

Notes: `anchor_groups` keeps the ADR-0021 discipline (SHA-256 fingerprint, never the normalized
value). The `reconstruction_map` is the **only** new store that holds original sensitive values by
design; it is isolated precisely so access control, audit, and deletion can be strict.

## 10. How PII, Review, Pseudonymization, and Reconstruction use anchors

### 10.1 PII → anchors

Detection may run on **Technical Raw Text** (today's active input), and later — behind the unchanged
[separation gate](../engine/ocr-layout-text-contract.md#invariants) — on Canonical Reading Text or
structured hints. For each hit:

- map the detection span to **anchor id(s)** via the anchor graph;
- **create or merge a PII candidate**, preserving detection **source/provenance** (which view, which
  recognizer) — reusing today's `PiiEntityProvenance`;
- if the **same anchor set** is detected from multiple sources, **merge provenance** (not text);
- if the mapping is **partial/missing/ambiguous**, **mark review-required** — **never drop** the
  entity because a canonical mapping is missing, and **never treat canonical as authoritative**.

This improves: **duplicate handling** (dedupe by anchor set, not by fragile string equality),
**overlap handling** (overlaps resolved over anchors, extending [ADR-0028](0028-pii-intake-document-text-package-v1.md)),
**provenance** (multi-source detection converges on one anchor with combined provenance), and
**raw/canonical display consistency** (both views highlight the same anchor identity).

### 10.2 Review → anchors

- Review is over **stable entities** (which point to anchors), not over any single view's string.
- The entity's stable `entity_id` already exists ([ADR-0029](0029-pii-review-ready-entity-contract.md));
  it gains an explicit **anchor binding**.
- A decision **does not mutate** raw/canonical/layout text — it changes **entity status**.
- Decisions are **stable across re-rendering** because they key on entity/anchor identity, not
  offsets. The future `review_result` artifact formalizes this (Review L8).

### 10.3 Pseudonymization → anchors

- An **accepted** PII entity carries **anchor ids**.
- A **replacement plan** assigns a **placeholder/replacement token** to a **replacement group**
  (`PERSON_001`, `ADDRESS_001`, `DATE_001` — one token per real-world referent, so every mention of
  the same person gets the same token).
- The **renderer builds output text by replacing anchor ranges / entity spans** in the chosen view —
  the output is **generated, not painted over**, so raw/canonical/layout renders stay consistent
  because they render from the *same* anchor + token decisions.
- **Partial/missing mapping in a target view** triggers **review or an explicit fallback policy**,
  never a silent gap.

### 10.4 Reconstruction → anchors

Flow: a later **AI output contains placeholders** like `PERSON_001` → the system maps the placeholder
to its **replacement group/entity** → the entity maps to **anchors / original value** → the original
value is **restored only if policy allows**.

- The original text **need not have existed in the AI output** — the **placeholder identity is
  enough**; there is no fuzzy matching of private text.
- An **audit trail is required** for every reconstruction.
- **Must store:** placeholder token, `replacement_group_id`, `entity_id`, entity `anchor_id`s, an
  original canonical/raw **value representation**, review approval, and access-policy/audit metadata —
  the `reconstruction_map` in [§9](#9-future-data-model), isolated and access-gated.

## 11. Frontend highlight consistency

- Today's inconsistency arises because raw/canonical/layout views are highlighted **independently**,
  each from its own offsets, so a view without a projected range silently loses the entity.
- The future UI **highlights by entity/anchor identity**: if an entity binds anchor `A`, **every view
  highlights `A` wherever that view has a range**.
- A **missing canonical range** becomes a **visible mapping state** (e.g. "detected, not located in
  reading view"), not a disappearance.
- An **ambiguous mapping** becomes a **review state**, not a silent guess.
- The **frontend must not invent its own independent PII entity sets** per view — it renders the
  server's anchor-bound entities. `buildHighlightSegments` becomes a renderer of shared identity, not
  an independent per-string detector.

## 12. Product / module implications

This identity layer turns the pipeline into **independently valuable modules**:

- **OCR/Text module** — standalone document-understanding output (text layers + anchors) usable
  beyond PII (analysis, export, AI).
- **PII / De-Identification module** — a **consumer of text identity**, not a re-deriver of it.
- **Review module** — a decision layer over stable entities.
- **Pseudonymization module** — a **renderer** from decisions + anchors + tokens.
- **Reconstruction module** — a reverse mapping from placeholder to original.
- **Runtime module** — processing/status, already contract-separated (ADR-0023/0030).

**Why this is a differentiator:** most tools "detect and mask." An anchor identity layer lets this
product (a) keep raw/canonical/layout perfectly consistent, (b) pseudonymize by *rendering* rather
than destroying text, and (c) *reconstruct* an AI-processed document deterministically and auditable —
a round-trip de-identification capability that string-replacement pipelines structurally cannot offer.

## 13. Staged implementation plan

Each phase is a separate, small, approved PR. OCR/Text stays ahead of PII throughout
([ADR-0018](0018-ocr-pii-implementation-plan.md)).

- **Phase A — Design / ADR (this document).** No code.
- **Phase B — Text Anchor Graph v1.** Derived from `DocumentTextPackageV1`, owned by OCR/Text,
  reusing `reading_text_map` + `text_geometry`. JSON artifact / derived endpoint first. **No DB.**
- **Phase C — PII entity anchor refs.** PII entities bind to anchors (`entity_anchors`); raw/canonical
  highlights share anchor ids. Detection input unchanged (raw); separation gate intact.
- **Phase D — Frontend highlight consistency via anchors.** One entity/anchor identity powers all
  views; missing/ambiguous become visible states.
- **Phase E — Persistence model proof.** Decide JSON vs SQLite per state; land the **SQLite-ready
  relational shape** — not necessarily a full migration.
- **Phase F — Review result artifact.** Stable review decisions over entity/anchor ids (Review L8);
  first state to move into SQLite if E recommends it.
- **Phase G — Replacement plan / Pseudonymized Text v1.** Accepted entities → placeholders; **rendered
  output from anchors/entities**, never blind replacement.
- **Phase H — Reconstruction Map v1.** Placeholders restored from the replacement/entity/anchor map,
  access-gated and audited.
- **Phase I — Runtime notifications / job UX.** User-visible status once the core entity/review flow is
  stable (extends ADR-0030); intentionally *last* so infra never front-runs the identity model.

**Recommended ordering note.** B → C → D first (they remove the observed inconsistency at the root and
cost no DB), *then* E before F/G/H (prove the persistence shape before any engine depends on it). This
front-loads the differentiator (consistent identity) and defers the DB decision until Review actually
needs it — matching the existing "DB when Review persistence needs it" guidance. Do **not** reorder G
before C/E.

## 14. Deferred decisions

- **Anchor granularity** (span/value vs. word-level) — start at the reliable span/value unit; refine
  to word-level when `text_geometry` word boxes exist.
- **Whether the anchor graph is a field on `text_result` or its own derived artifact/endpoint** —
  resolve in Phase B; the contract (stable id + per-view ranges + states) is the same either way.
- **Exact SQLite schema, indices, and the JSON→SQLite migration** — Phase E.
- **Cross-type overlap precedence over anchors** — still deferred from
  [ADR-0028](0028-pii-intake-document-text-package-v1.md); flag-for-review remains the policy.
- **Reconstruction access-control / policy model and audit retention** — Phase H, with its own ADR.
- **Making a non-raw view the active PII detection input** — unchanged; still gated by the
  [`text_lineage_map` separation gate](../engine/ocr-layout-text-contract.md#invariants). The anchor
  graph is a *prerequisite* for satisfying that gate, not a bypass of it.

## 15. Consequences

- OCR/Text gains a first-class **identity layer** that finally realizes the long-reserved
  `text_lineage_map` "no islands" goal, and unblocks **PII L17** (stable entity model with lineage).
- Cross-view PII inconsistency is fixed **at the model level**, so the frontend stops being able to
  diverge per view.
- Pseudonymization and reconstruction get a **correct substrate** (render + reverse-map) instead of an
  unsafe string-replacement shortcut.
- The persistence path is **explicit and staged**: files stay files, SQLite arrives only when Review
  persistence needs it, and the reconstruction map (the one store of originals) is isolated for
  access control and deletion.
- Cost: a new derived layer and, later, a real DB — both introduced incrementally, each behind its own
  approved PR, none of them in this ADR.

## 16. Explicitly not done yet

- **No pseudonymization** before stable entity/anchor binding exists.
- **No full DB migration** before the data model is proven (Phase E).
- **No global fuzzy word matching** — identity is by anchor, not string similarity.
- **No UI-only highlight patch** as the final solution — the fix is the anchor model.
- **No treating canonical text as authoritative** — raw remains the offset authority.
- **No suppressing a PII entity because a canonical mapping is missing** — it becomes a visible state.
- **No replacing the OCR/PII architecture with runtime infrastructure** — runtime (ADR-0023/0030) stays
  a separate, downstream contract and never front-runs the identity model.
