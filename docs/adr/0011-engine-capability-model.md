# ADR-0011: Engine capability model

## Status

Accepted — 2026-07-01

## Context

Through PR #7, the project has built a lot of *infrastructure*: upload/core, storage separation,
audit, OCR runtime + model provisioning, the text-layer quality gate and page-level OCR fallback,
detection-only PII, a manual review UI, and a private local OCR/PII benchmark runner
([ADR-0010](0010-private-benchmark-runner.md)). What was missing was a shared, explicit definition of
**what the actual engine is supposed to become** — the OCR/Text engine, the PII/sensitive-data
engine, the review/feedback engine, and any optional local AI assist — and how today's state maps
onto that target.

Without that, roadmap decisions were implicit and it was hard to say, for any capability, "where are
we, what is the next level, and which PR gets us there". The first private benchmark run also
produced concrete, aggregate signals (structured recall gaps on AT/DE data, NER over-tagging, zero
coverage of domain-sensitive identifiers) that should *drive* the roadmap rather than being
rediscovered ad hoc.

## Decision

- Add a `docs/engine/` capability model that defines, for each sub-engine, a **0–10 level ladder**
  (name, goal, required capability, artifacts, metrics, tests/benchmarks, tools, non-scope,
  acceptance criteria), plus cross-cutting documents for artifacts, quality metrics, tool strategy,
  target architecture, and a reframed roadmap:
  - [`ocr-engine-levels.md`](../engine/ocr-engine-levels.md),
    [`pii-engine-levels.md`](../engine/pii-engine-levels.md),
    [`review-feedback-levels.md`](../engine/review-feedback-levels.md),
  - [`engine-artifacts.md`](../engine/engine-artifacts.md),
    [`quality-metrics.md`](../engine/quality-metrics.md),
    [`tool-strategy.md`](../engine/tool-strategy.md),
    [`target-architecture.md`](../engine/target-architecture.md),
    [`roadmap.md`](../engine/roadmap.md),
    with an index in [`README.md`](../engine/README.md).
- Establish the engine **north star**: document in → best possible text out → structure preserved →
  PII detected reliably → human review/correct → redaction builds on top later.
- Fix key model invariants: a **canonical** `best_text_result` (the only PII/review input) separate
  from a **human-readable** `layout_text_result`; **detection-only** until a redaction phase is
  explicitly designed; **candidate validation is a subtractive post-processing step**, not a new
  detector; and any future AI must be **local, assistive, labelled, and auditable**, never silently
  overwriting canonical text.
- Anchor the current-state assessment in the repo and one private benchmark run (aggregate figures
  only): OCR/Text at **L3 done / L4 partial**, PII at **L1 done / L4 foundation** (structured
  recognizers + env allowlist, no AT/DE or domain packs, no validation), Review at **L1**, benchmark
  at **L2**, storage sufficient, DB not yet needed.
- Reframe the roadmap around the engine (Engine-0…9), mark **Engine-1 done** (delivered by PR #7),
  and prioritise the gaps the benchmark exposed: AT/DE + insurance/legal recognizers (Engine-4), then
  candidate validation (Engine-5), then review persistence (Engine-6), with DB, local-AI, and
  redaction as later spikes/phases.
- Keep the DB question explicitly **framed but unimplemented** (SQLite-first for local MVP, Postgres
  only at multi-user/server/concurrency; raw text/PII never move into a DB).

## Consequences

- Every future engine PR can state its level transition, affected artifacts, metrics, and acceptance
  criteria against a shared reference, and the roadmap order is justified by measured benchmark
  signals rather than intuition.
- This PR changes **no** OCR/PII/review behaviour and adds **no** dependency; it is documentation
  plus pointer updates in `README.md`, `.ai/state.md`, and `.ai/decisions.md`.
- The privacy posture is reinforced in the model itself: metrics-only artifacts never hold text/PII,
  text/PII artifacts stay under the git-ignored document-data root, and no private document names,
  extracted text, or PII values are reproduced in these docs — only aggregated benchmark figures.
- The model is a living target: level assessments are expected to move as Engine-2+ land, and the
  documents (not this ADR) are the place to keep the current-level snapshot current.
