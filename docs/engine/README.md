# Engine Capability Model

This directory defines **what the de-identification engine is supposed to do**, level by level,
independent of upload, UI, or infrastructure work. It is a target picture and a roadmap, not a new
feature. No OCR/PII behaviour changes in the PR that introduces these documents.

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
| [`ocr-engine-levels.md`](ocr-engine-levels.md) | What should the OCR/Text engine do at level 0…10? |
| [`pii-engine-levels.md`](pii-engine-levels.md) | What should the PII/sensitive-data engine do at level 0…10? |
| [`review-feedback-levels.md`](review-feedback-levels.md) | What should the review/human-in-the-loop engine do at level 0…10? |
| [`engine-artifacts.md`](engine-artifacts.md) | Which artifacts flow between the engines, and their privacy rules? |
| [`quality-metrics.md`](quality-metrics.md) | Which metrics measure quality, and which are measured today? |
| [`tool-strategy.md`](tool-strategy.md) | Which tools are core, which are spikes, which are deferred? |
| [`target-architecture.md`](target-architecture.md) | Target architecture, the DB question, and the optional local-AI question. |
| [`roadmap.md`](roadmap.md) | Which PRs come next, in which order, with scope and acceptance criteria. |

The architecture decision behind this model is
[ADR-0011](../adr/0011-engine-capability-model.md).

## Guiding principles (carried over, not invented here)

- **Tool-first / adapter-only.** We integrate proven open-source tools behind ports/adapters; we
  do not build bespoke OCR/NER/redaction intelligence. See [`AGENTS.md`](../../AGENTS.md).
- **Local-first / privacy-first.** Everything runs locally. No document bytes, extracted text, or
  PII values leave the machine. This constrains every "AI assist" idea (see the local-AI chapter of
  [`target-architecture.md`](target-architecture.md#optional-local-ai--vision--document-understanding)).
- **Immutable, lineage-aware artifacts.** Each station appends an immutable JSON artifact that
  references its input artifact; nothing is silently overwritten.
- **Detection-only, for now.** The pipeline labels; it never anonymises or alters source documents.
- **Never silently trust broken input.** A broken/encoded PDF text layer is routed to OCR, not
  used blindly; a missing OCR runtime fails loudly (`503`) instead of returning garbage.

## Levels at a glance

Each engine has its own 0–10 ladder (details in the linked documents). Level numbers are **not**
comparable across engines — OCR L5 and PII L5 are unrelated milestones.

## Current level snapshot

Assessed against the local `main` at the time of writing (through PR #7, the private benchmark
runner) and against one local private benchmark run (12-document corpus; aggregate figures only,
see [`quality-metrics.md`](quality-metrics.md)).

| Area | Current level | Basis | Next level | Next PR |
| --- | --- | --- | --- | --- |
| OCR / Text engine | **L3 reached, L4 partial** | Per-page text-layer quality gate + page-level OCR routing shipped; quality *verdicts* + routing metrics exist, but no CER/WER/confidence/runtime metrics | L4 → L5 | Engine-2 |
| PII / sensitive-data engine | **L3 reached, L4 partial** | AT/DE + insurance/legal recognizers and named coverage profiles run; address and candidate validation remain open | L5 | Engine-5 |
| Review / feedback engine | **L1 reached** | Detail page lists candidates and overlays lineage-safe highlights; no persisted human decisions | L2 | Engine-6 |
| Benchmark / regression | **L2 (reproducible metrics)** | `make benchmark-private` produces routing + PII P/R/F1 from existing artifacts; single snapshot, no trend/CI gate | L3 (trend + CI hook) | Engine-1 (done) → later |
| Storage / core | **Sufficient for MVP** | Separated upload/document-data roots, immutable artifacts, validated deletes | — | — |
| Database | **Not implemented; architecture open** | Everything file-based today | Decide SQLite-first index | Engine-7 (spike) |

See [`roadmap.md`](roadmap.md) for the full per-area justification and the ordered PR plan.
