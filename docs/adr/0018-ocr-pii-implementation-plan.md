# ADR-0018: OCR/PII implementation plan, core-engine ordering, and checkpoint loop

## Status

Accepted — 2026-07-02. Builds on [ADR-0011](0011-engine-capability-model.md) (capability model) and
[ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 maturity scale). Docs-only.

## Context

The 0–19 maturity scale (ADR-0016) says how mature each engine is, and the per-engine level documents
say what each level means, but there was no binding *operative* plan tying the two core engines —
OCR/Text and PII/Sensitive-Data — into an ordered PR sequence with a re-validation loop. Without one,
autonomous agents (Codex, Claude Code, others) tend to add locally convenient features ad hoc, and
PII/review/redaction work risks outrunning the OCR/Text text-quality, structure, lineage, confidence,
and geometry it depends on.

## Decision

- **OCR/Text and PII/Sensitive-Data are the core engines.** Review, Feedback, Benchmark, Audit, and
  later Redaction exist to support and measure these two.
- **OCR/Text stays 2–3 maturity levels ahead of PII/Redaction.** A PII/review/redaction step that
  depends on an OCR capability not yet at the required level is blocked until that OCR level lands;
  Redaction stays at L0 until reviewed decisions (Review L8–L9), stable/resolved PII spans
  (PII L17–L18), and OCR text-to-geometry mapping (OCR L10/L15) all exist.
- **Adopt a checkpoint loop after every engine PR** (which level changed, is OCR still sufficiently
  ahead, did benchmark/feedback shift priorities, any config/artifact drift, are docs/state updated,
  is the next PR still valid) and a deeper review after every third PR (confirm/adjust the next three
  PRs against feedback and benchmark evidence).
- Record the operative sequence, cadence (standard **2 OCR/Text : 1 PII/Review**), and the concrete
  next-12-PR list in [`docs/engine/ocr-pii-implementation-plan.md`](../engine/ocr-pii-implementation-plan.md),
  which stays consistent with the authoritative [`roadmap.md`](../engine/roadmap.md) and invents no
  new level numbers.

## Consequences

- Engine work becomes systematic and reviewable: each PR states the 0–19 level it advances (or the
  explicit non-level hardening it does), and the checkpoint loop keeps the plan honest after each PR.
- **Docs-only, no behaviour change:** no OCR/PII implementation, no recognizer/profile change, no
  API/frontend/DB/benchmark/redaction change, and no new dependency. The plan is planning material;
  each listed capability becomes real only through its own engine PR.
- The plan and `roadmap.md` must be kept in sync; `roadmap.md` remains the authoritative near-term
  order and the plan is its OCR/PII-focused operative companion.
- Privacy posture unchanged: no private data or `volumes/` content is referenced.
