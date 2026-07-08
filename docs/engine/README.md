# Engine Capability Model

This directory defines **what the de-identification engine is supposed to do**, level by level,
independent of upload, UI, or infrastructure work. It is a target picture and a roadmap, not an
implementation by itself.

The engine is the core of the product. Everything else (upload, storage, audit plumbing, the
review page) exists to feed it or to expose it. The engine is four cooperating sub-engines:

```text
local OCR / Text engine            document → best possible text
local PII / sensitive-data engine  text → labelled sensitive spans
review / feedback engine           human confirms / corrects / teaches
optional local AI / vision assist  hard pages & plausibility, assistive only
```

## North star

```text
document in
  → best possible text out          (OCR/Text engine)
  → structure preserved as far as possible
  → PII / sensitive data detected as reliably as possible   (PII engine)
  → a human can review and correct  (Review/Feedback engine)
  → redaction / de-identification builds reliably on top     (later, out of scope here)
```

De-identification (masking/redaction/pseudonymisation) is deliberately **not** part of this model
yet. It is the payoff that a trustworthy text + PII + review foundation earns. Getting text and PII
right, and making both human-reviewable, comes first.

## How these documents fit together

| Document | Question it answers |
| --- | --- |
| [`ocr-engine-levels.md`](ocr-engine-levels.md) | What should the OCR/Text engine do at level 0…19? |
| [`pii-engine-levels.md`](pii-engine-levels.md) | What should the PII/sensitive-data engine do at level 0…19? |
| [`review-feedback-levels.md`](review-feedback-levels.md) | What should the review/human-in-the-loop engine do at level 0…19? |
| [`benchmark-engine-levels.md`](benchmark-engine-levels.md) | What should the benchmark/regression engine do at level 0…19? |
| [`redaction-engine-levels.md`](redaction-engine-levels.md) | What should the redaction/de-identification engine do at level 0…19? |
| [`entity-taxonomy.md`](entity-taxonomy.md) | What do we detect — business categories, entity types, risk classes P0–P5, detection strategies, and coverage? |
| [`engine-settings.md`](engine-settings.md) | How do runtime settings map to engine maturity, artifacts, and dev/prod sourcing? |
| [`engine-artifacts.md`](engine-artifacts.md) | Which artifacts flow between the engines, and their privacy rules? |
| [`quality-metrics.md`](quality-metrics.md) | Which metrics measure quality, and which are measured today? |
| [`tool-strategy.md`](tool-strategy.md) | Which tools are core, which are spikes, which are deferred? |
| [`target-architecture.md`](target-architecture.md) | Target architecture, the DB question, and the optional local-AI question. |
| [`roadmap.md`](roadmap.md) | Which PRs come next, in which order, with scope and acceptance criteria. |
| [`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md) | Operative OCR/PII PR sequence, cadence, and the checkpoint loop that re-validates the plan after each PR. |
| [`ocr-layout-text-contract.md`](ocr-layout-text-contract.md) | The canonical / PII-input / readable / layout text-layer contract, the lineage map, and invariants, fixed before layout implementation. |

**OCR/Text and PII/Sensitive-Data are the core engines**; the other engines (Review, Feedback,
Benchmark, Audit, Redaction) support and measure them. The operative plan that keeps OCR/Text ahead
of PII/Redaction and re-validates after every PR is
[`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md).

The architecture decision behind this model is
[ADR-0011](../adr/0011-engine-capability-model.md); the migration to the 0–19 maturity scale is
[ADR-0016](../adr/0016-engine-maturity-levels-0-19.md); the entity taxonomy and P0–P5 risk classes
are [ADR-0017](../adr/0017-entity-taxonomy-and-risk-classes.md); the OCR/PII implementation plan and
checkpoint loop are [ADR-0018](../adr/0018-ocr-pii-implementation-plan.md).

## Guiding principles (carried over, not invented here)

- **Tool-first / adapter-bound.** Core OCR, NER, redaction, and pseudonymization intelligence comes
  from established tools behind ports/adapters. Small deterministic domain rules are allowed only
  under the documented quality and auditability constraints in [`AGENTS.md`](../../AGENTS.md).
- **Local-first / privacy-first.** Everything runs locally. No document bytes, extracted text, or
  PII values leave the machine. This constrains every "AI assist" idea (see the local-AI chapter of
  [`target-architecture.md`](target-architecture.md#optional-local-ai--vision--document-understanding)).
- **Immutable, lineage-aware artifacts.** Each station appends an immutable JSON artifact that
  references its input artifact; nothing is silently overwritten.
- **Detection-only, for now.** The pipeline labels; it never anonymises or alters source documents.
- **Never silently trust broken input.** A broken/encoded PDF text layer is routed to OCR, not
  used blindly; a missing OCR runtime fails loudly (`503`) instead of returning garbage.

## Maturity scale

Every central engine is planned on a **0–19 maturity scale**. The previous 0–10 (and informal 0–14)
ladders were too coarse to plan finer PR steps against, so OCR/Text, PII/Sensitive-Data,
Review/Human-Feedback, Benchmark/Regression, and Redaction are each defined and assessed on 0–19.

- Level numbers are **cumulative** within an engine (each level assumes the ones below it) and
  **not** comparable across engines — OCR L9 and PII L9 are unrelated milestones.
- Each level states a name, description, testable acceptance criteria, and a clear boundary to the
  next level, so a PR can declare exactly which level it advances.
- Every per-engine document ends with a **legacy 0–10 → 0–19 mapping table** so older citations can
  be translated.

New engine PRs should state which level they advance. The current roadmap, metrics, artifact model,
and level documents use the 0–19 scale; historical ADRs and explicitly labelled legacy mapping
sections or migration banners retain older numbers where needed for traceability. The decision is
recorded in
[ADR-0016](../adr/0016-engine-maturity-levels-0-19.md) (which extends
[ADR-0011](../adr/0011-engine-capability-model.md)).

## Current level snapshot (0–19)

Assessed against the local `dev` branch at the time of writing and against one local private
benchmark run (12-document corpus; aggregate figures only, see
[`quality-metrics.md`](quality-metrics.md)).

| Area | Current level (0–19) | Basis | Next level |
| --- | --- | --- | --- |
| OCR / Text engine | **L12 done** | text extraction, lineage, OCR runtime, quality routing, OCR confidence, lineage-bound metrics-only `quality_report`, additive readable/layout views, L10 geometry, L11 structured content, and L12 multi-column reading-order reconstruction shipped | PII L12 overlap resolution |
| PII / sensitive-data engine | **L11 done, L10 partial** | structured + AT/DE + domain recognizers, profiles, benchmark, candidate validation, context hardening, address/contact-line, reproducible `engine_settings`; **dev-only** feedback capture landed; derived entity grouping + a review-decision overlay ([ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md)) | L12 overlap resolution |
| Review / human-feedback engine | **L2 done; L3–L5 dev-only; L6 done; L7–L9 partial** | read-only review + lineage-safe highlights (prod); clickable offsets, legend, dev engine-settings override, per-entity dev feedback capture (behind `ENABLE_DEV_ENGINE_SETTINGS`); grouped occurrences + a lineage-bound decision overlay | formal `review_result` artifact model |
| Benchmark / regression | **L8 done; L10 slice delivered out of order** | matching, routing correctness, PII P/R/F1, privacy guard, determinism, validation counts, safe OCR confidence/coverage columns | L9 per-profile in one run |
| Redaction / de-identification | **L0 by design** | detection-only; blocked on PII L17–L18, Review L8–L9, OCR L10/L15 | L1 requirements/threat model, deliberately last |
| Storage / core | **Sufficient for MVP** | separated roots, immutable artifacts, validated deletes | — |
| Database | **Not implemented; architecture open** | everything file-based today | decide only when a binding review workflow requires it |

See [`roadmap.md`](roadmap.md) for the full per-area justification and the ordered PR plan, and each
engine's own document for the full 0–19 ladder.
