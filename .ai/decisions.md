# Decisions

Architecture decisions are recorded as ADRs under `docs/adr/`.

- [ADR-0001](../docs/adr/0001-stack-and-architecture.md) — Docker-first FastAPI + React/Vite
  architecture behind nginx.
- [ADR-0002](../docs/adr/0002-upload-core-artifact-metadata.md) — Upload integrity metadata and
  the embedded original artifact.
- [ADR-0003](../docs/adr/0003-audit-station.md) — Synchronous Audit v1 with immutable JSON
  artifacts.
- [ADR-0004](../docs/adr/0004-ocr-workstation.md) — Per-page OCR/Text routing behind replaceable
  adapters.
- [ADR-0005](../docs/adr/0005-pii-workstation.md) — Detection-only PII over immutable text
  artifacts.
- [ADR-0006](../docs/adr/0006-docx-extraction-and-pii-precision.md) — Shared DOCX extraction and
  precision-first PII defaults.
- [ADR-0007](../docs/adr/0007-ocr-runtime-and-model-provisioning.md) — Reproducible optional OCR
  runtime and model provisioning.
- [ADR-0008](../docs/adr/0008-separate-upload-and-document-data-storage.md) — Separate original and
  document-data storage roots.
- [ADR-0009](../docs/adr/0009-text-layer-quality-routing.md) — Text-layer quality gate and
  per-page OCR fallback.
- [ADR-0010](../docs/adr/0010-private-benchmark-runner.md) — Local private benchmark runner with a
  guarded aggregate report boundary.
- [ADR-0011](../docs/adr/0011-engine-capability-model.md) — Engine capability model; its original
  level numbering is superseded by ADR-0016.
- [ADR-0012](../docs/adr/0012-insurance-at-de-pii-recognizers.md) — Presidio-based AT/DE and domain
  recognizers with named profiles.
- [ADR-0013](../docs/adr/0013-pii-candidate-validation.md) — Auditable, subtractive PII candidate
  validation.
- [ADR-0014](../docs/adr/0014-pii-candidate-validation-context-hardening.md) — Context hardening for
  candidate validation.
- [ADR-0015](../docs/adr/0015-structured-address-contact-line-recognizers.md) — Structured address
  and contact-line recognizers.
- [ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md) — Canonical 0–19 maturity scales for
  OCR, PII, Review, Benchmark, and Redaction.
- [ADR-0017](../docs/adr/0017-entity-taxonomy-and-risk-classes.md) — Entity taxonomy, detection
  strategies, and risk/protection classes P0–P5.
- [ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md) — OCR/Text and PII/Sensitive-Data are
  the core engines; OCR/Text stays 2–3 levels ahead of PII/Redaction; a checkpoint loop re-validates
  the plan after each engine PR. Operative sequence in
  [`ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md).
- [ADR-0019](../docs/adr/0019-canonical-reading-text-and-technical-raw-contract.md) — Preserve
  `text_result.text` as technical raw/PII offset text and add versioned canonical `reading_text` as
  the product-facing main document view; any future PII switch remains lineage-gated.
- [ADR-0021](../docs/adr/0021-pii-entity-grouping-and-review-decisions.md) — Conservative,
  derived (non-persisted) PII entity grouping plus a lineage-bound, JSONL-based review-decision
  overlay (default `pseudonymize`; opt out via `keep`/`false_positive`) that never mutates
  `pii_result`.
- [ADR-0022](../docs/adr/0022-ocr-l12-multi-column-layout-reconstruction.md) — OCR/Text L12 is
  deterministic multi-column layout reconstruction inside canonical `reading_text`; the older
  multi-engine-selection placeholder is deferred and technical raw text/active PII input remain
  unchanged.
- [ADR-0023](../docs/adr/0023-runtime-worker-architecture.md) — *Proposed for the overall worker
  architecture; Phases 1-3.6 implemented.* Staged move from in-process synchronous OCR/PII to an
  isolated worker boundary: internal job model, SQLite-backed metadata-only job state + safe status
  API, isolated `ocr-worker`, and a simplified default Compose stack (`frontend`, `api`,
  `ocr-worker`) with OCR worker mode as the normal runtime. Artifacts stay file-based; no
  Kubernetes/microservices/broker near-term.
- [ADR-0024](../docs/adr/0024-ocr-l13-table-form-reconstruction-v2.md) — OCR/Text L13 is table/form
  reconstruction v2 (geometry-only table detection, partially fused header recovery, multiline
  label/value continuation) inside `reading_text`/`structured_content`; the older
  document-understanding placeholder is deferred and technical raw text/active PII input remain
  unchanged.
- [ADR-0025](../docs/adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md) — OCR/Text L14 is
  additive, metrics-only `quality_evidence` and lineage coverage on `text_result`; the older local
  AI assist placeholder is deferred and technical raw text/active PII input remain unchanged.
- [ADR-0026](../docs/adr/0026-ocr-l15-noise-token-artifact-evidence.md) — OCR/Text L15 is
  deterministic noise/token artifact *evidence* (glyph artifacts, suspicious token shapes,
  character-confusion candidates, spacing candidates) folded into the same `quality_evidence` list;
  the older redaction-ready-geometry placeholder is deferred, and no OCR text is ever corrected,
  removed, or rewritten.
- [ADR-0027](../docs/adr/0027-ocr-output-contract-v1-strategy.md) — Implemented additively as the
  **OCR Output Contract v1 / Document Text Package** (`contract_version = "1.0"`): a derived
  package of raw/canonical/layout/structured/evidence layers plus source roles and
  `contract_status` (`valid`/`degraded`/`invalid`), so PII and future consumers depend on the
  contract rather than OCR internals. PII is not migrated yet; existing OCR endpoints remain
  backward-compatible. Cross-cutting stabilization milestone, not a numbered level; the 0–19 scale
  (ADR-0016) is unchanged.
- [ADR-0028](../docs/adr/0028-pii-intake-document-text-package-v1.md) — **PII intake via the
  Document Text Package + PII L12 overlap resolution.** PII consumes `DocumentTextPackageV1`
  through the `pii_input` intake adapter (`PiiInputDocumentV1`) instead of `TextContent` internals:
  raw stays the primary/only active detection input, canonical is contextual, structured content is
  a hint layer, quality/noise evidence is trust context, a structurally invalid package is rejected
  (`422`) while empty raw text stays the benign empty-result path, and a degraded package with raw
  text still processes. Deterministic `pii_overlap` resolution merges exact/same-type/nested
  duplicates (recording superseded ids) and flags cross-type overlaps for review without dropping
  them. Additive optional `pii_result` fields (`PiiEntity.provenance`, `PiiContent.input_contract`,
  `PiiContent.overlap_resolution`) carry the outcome; no raw text enters that metadata. Existing PII
  API/frontend behavior and the active-input separation gate are unchanged.
