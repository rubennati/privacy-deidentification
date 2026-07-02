# ADR-0016: Engine maturity levels are 0–19

## Status

Accepted — 2026-07-02. Extends [ADR-0011](0011-engine-capability-model.md) (engine capability
model), whose 0–10 ladders this ADR replaces with a 0–19 scale.

## Context

[ADR-0011](0011-engine-capability-model.md) introduced a `docs/engine/` capability model with a
**0–10** level ladder per sub-engine. As the OCR/Text and PII/sensitive-data engines matured, the
0–10 granularity proved too coarse to plan individual PRs against: a single "level" bundled several
distinct, independently shippable capabilities (e.g. the PII "candidate validation" level actually
covered validation, context hardening, and address/contact-line coverage; the OCR "page-level
routing" level bundled the quality gate and the routing that acts on it). Some notes had also drifted
to an informal 0–14 phrasing.

OCR/Text and PII/sensitive-data are the heart of the product, and Review/Human-Feedback, Benchmark/
Regression, and Redaction/De-Identification each need the same finer planning surface. A coarse scale
made it hard to say precisely "which level does this PR advance" and to record testable acceptance
criteria per step.

## Decision

- Adopt a **0–19 maturity scale** as the primary planning scale for the central engines: OCR/Text,
  PII/Sensitive-Data, Review/Human-Feedback, Benchmark/Regression, and Redaction/De-Identification.
- Each level defines a **name, description, testable acceptance criteria, and an explicit boundary to
  the next level**, so a PR can state exactly which level it advances.
- Restructure the per-engine documents onto 0–19 and add, to each, a **legacy 0–10 → 0–19 mapping
  table**:
  - [`ocr-engine-levels.md`](../engine/ocr-engine-levels.md),
    [`pii-engine-levels.md`](../engine/pii-engine-levels.md),
    [`review-feedback-levels.md`](../engine/review-feedback-levels.md),
  - new [`benchmark-engine-levels.md`](../engine/benchmark-engine-levels.md) and
    [`redaction-engine-levels.md`](../engine/redaction-engine-levels.md),
  - new [`engine-settings.md`](../engine/engine-settings.md) classifying each runtime setting as
    runtime vs maturity, artifact-recorded vs not, dev-selectable vs prod-only-from-`.env`, and its
    precision/recall, OCR-quality, and reproducibility impact.
- **`PII_CANDIDATE_VALIDATION_ENABLED`** is treated as a distinct **pipeline stage** (PII L6), not a
  mere flag, and is a first-class maturity step.
- Anchor the current standing on the 0–19 scale: **OCR/Text L5 done** (confidence + `quality_report`
  next), **PII L9 done / L10 partial** (dev-only human feedback capture landed; entity grouping,
  overlap resolution, and the binding review overlay open), **Review L2 done with L3–L5 delivered
  dev-only**, **Benchmark L8 done**, **Redaction L0** (detection-only by design).
- **Process rules:** new engine PRs state which level they advance; PR summaries mention the affected
  engine level where relevant; agents must not mix the older 0–10/0–14 numbering without a migration
  note. Feature/documentation PRs target `dev`, not `main`.

## Consequences

- Planning is finer and each level has testable acceptance criteria, so PR scope maps cleanly to a
  single level transition.
- This is a **documentation/planning** change only: **no** OCR/PII/review behaviour changes, **no**
  API/frontend/DB/redaction changes, and **no** new dependency. The privacy posture is unchanged and
  no private data appears in these docs.
- Cross-cutting engine documents ([`engine-artifacts.md`](../engine/engine-artifacts.md),
  [`quality-metrics.md`](../engine/quality-metrics.md), [`tool-strategy.md`](../engine/tool-strategy.md),
  [`target-architecture.md`](../engine/target-architecture.md), [`roadmap.md`](../engine/roadmap.md))
  and the roadmap's `Engine-N` PR ids retain their legacy per-engine level citations for now; each
  carries a migration-note banner and the per-engine mapping tables allow translation. Full
  renumbering of those citations is a tracked follow-up.
- [ADR-0011](0011-engine-capability-model.md) remains the record of *why* the capability model
  exists; this ADR supersedes only its **0–10 numbering**.
