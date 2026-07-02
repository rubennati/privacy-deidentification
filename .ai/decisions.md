# Decisions

Architecture decisions are recorded as ADRs under `docs/adr/`.

- [ADR-0001](../docs/adr/0001-stack-and-architecture.md) — Stack and architecture
  (Docker-first, FastAPI backend, React/Vite SPA behind nginx).
- [ADR-0002](../docs/adr/0002-upload-core-artifact-metadata.md) — Upload/Core integrity
  metadata and embedded original artifact in the existing JSON sidecar.
- [ADR-0003](../docs/adr/0003-audit-station.md) — Synchronous Audit v1 with immutable,
  file-based JSON result artifacts.
- [ADR-0004](../docs/adr/0004-ocr-workstation.md) — Synchronous per-page OCR/text routing with
  replaceable PaddleOCR and PDF-rendering adapter boundaries.
- [ADR-0005](../docs/adr/0005-pii-workstation.md) — Synchronous, detection-only PII labeling over
  immutable text artifacts with a lazy Presidio/spaCy adapter.
- [ADR-0006](../docs/adr/0006-docx-extraction-and-pii-precision.md) — Shared table-aware DOCX
  extraction for Audit and OCR/Text, precision-first PII default allowlist (spaCy NER opt-in), and
  Presidio log hardening.
- [ADR-0007](../docs/adr/0007-ocr-runtime-and-model-provisioning.md) — OCR runtime hardening
  (native libs, CPU MKL-DNN off, model names), idempotent PaddleOCR model provisioning under
  `volumes/ocr-models`, and slim/pii/ocr/full build profiles with smoke tests.
- [ADR-0008](../docs/adr/0008-separate-upload-and-document-data-storage.md) — Separate original
  uploads from per-document metadata and immutable artifacts, with validated deletion boundaries
  and no automatic migration of old local development data.
- [ADR-0009](../docs/adr/0009-text-layer-quality-routing.md) — Text-layer quality gate: a pure,
  dependency-free per-page heuristic (`text_quality.py`) classifies GOOD/LOW_CONFIDENCE/BROKEN/
  EMPTY, audit records it additively (metrics only, no page text), and OCR/Text routes each page on
  `needs_ocr` so broken/encoded text layers fall back to OCR instead of being used blindly.
- [ADR-0010](../docs/adr/0010-private-benchmark-runner.md) — Private local OCR/PII benchmark
  runner (`scripts/benchmark/`, stdlib-only): reads existing audit/text/pii artifacts, matches
  them to private-only benchmark metadata and candidate PII ground truth under
  `volumes/benchmark/` (git-ignored, never committed), and writes a markdown/JSON report guarded
  by `privacy_guard.py` so it can never contain raw text or PII values. Never triggers
  processing; missing artifacts are reported, not generated.
- [ADR-0011](../docs/adr/0011-engine-capability-model.md) — Engine capability model
  (`docs/engine/`): originally 0–10 level ladders for the OCR/Text, PII/sensitive-data, and
  review/feedback sub-engines (level **numbering superseded by [ADR-0016](#adr-0016)**), plus
  artifact model, quality metrics, tool strategy, target architecture (DB + optional local-AI
  questions), and a reframed Engine-0…9 roadmap. Docs-only, no behaviour/dependency change.
  Establishes north star, canonical vs human-readable text split, detection-only, and
  local/assistive/auditable AI guardrails.
- <a id="adr-0016"></a>[ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md) — Engine maturity
  levels are now **0–19** (extends ADR-0011). OCR/Text and PII/Sensitive-Data use 0–19 as the
  primary planning scale, alongside Review/Human-Feedback, Benchmark/Regression, and Redaction. Each
  level has a name, description, testable acceptance criteria, and a boundary to the next; each
  engine doc carries a legacy 0–10 → 0–19 mapping table. Adds `benchmark-engine-levels.md`,
  `redaction-engine-levels.md`, and `engine-settings.md` (runtime vs maturity, artifact-recorded,
  dev-selectable vs prod-only-from-`.env`; `PII_CANDIDATE_VALIDATION_ENABLED` is a pipeline stage,
  not just a flag). New engine PRs state which level they advance; agents must not mix older
  0–10/0–14 scales without a migration note. Docs-only, no behaviour/dependency change. Current
  standing: OCR/Text **L5**, PII **L9 / L10 partial**, Review **L2 (dev-only through L5)**, Benchmark
  **L8**, Redaction **L0**.
- [ADR-0012](../docs/adr/0012-insurance-at-de-pii-recognizers.md) — Presidio-based AT/DE and
  insurance/legal/business identifier pack, stable structured/domain/NER type groups, four named
  coverage profiles with a precision-first default, and immediate-label context for generic domain
  values. Candidate validation remains a separate follow-up.
- [ADR-0013](../docs/adr/0013-pii-candidate-validation.md) — PII candidate validation (Engine-5):
  a dependency-free KEEP/SCORE_DOWN/DROP post-processing filter over already-detected candidates,
  delivered as additive fields/summary on the existing `pii_result` artifact (not a separate
  `pii_validation_result`), a `PII_CANDIDATE_VALIDATION_ENABLED` escape hatch, and a benchmark
  aggregation of validation counts. PERSON/ORGANIZATION/LOCATION stay opt-in; no new recognizer,
  entity type, or dependency.
