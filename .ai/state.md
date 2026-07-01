# Current State

> If this file conflicts with current git state (branch, commits), trust git.

- Current phase: **Step 5 — Manual document review UI**
- Current objective: Let users inspect one document, explicitly run Audit/OCR/PII, and review
  lineage-safe PII highlights without modifying text or source documents.

## Snapshot

- Two-service architecture: `frontend` (nginx serving the React/Vite SPA + reverse-proxy
  `/api`) and `backend` (FastAPI). Backend is not published to the host.
- Pages: `/` landing, `/upload` upload, `/documents` list + delete, and
  `/documents/{id}` manual workstation control + review.
- Upload validates extension whitelist **and** magic-byte content signature, plus size; stores
  only UUID-named originals under `./volumes/uploads` and per-document `document.json` plus
  `artifacts/` under the separate `./volumes/document-data` bind mount.
- New uploads compute SHA-256 while streaming, record a server-verified MIME type, and embed an
  independently identified original artifact in `document.json`.
- Audit v1 verifies original integrity and records per-page PDF text-layer statistics, DOCX
  paragraph statistics, or PNG/JPEG dimensions as immutable JSON artifacts. Each PDF page also gets
  a text-layer quality verdict (`text_quality_status`/`score`/`reasons`, `recommended_text_source`,
  `needs_ocr`) from a pure, dependency-free heuristic (`services/text_quality.py`) — metrics only,
  never the page text. See [ADR-0009](../docs/adr/0009-text-layer-quality-routing.md).
- OCR/Text v1 reverifies the original, routes PDF pages individually on the audit's per-page
  `needs_ocr` (GOOD/LOW_CONFIDENCE keep the text layer; BROKEN/EMPTY use the lazy PaddleOCR
  adapter), extracts DOCX text via a shared table-aware helper (paragraphs, tables, and
  section headers/footers in document order), and stores immutable text artifacts. A broken text
  layer is never silently used: an OCR-required page with no OCR runtime still returns `503`. Audits
  predating the quality gate fall back to routing on `has_text_layer`.
- Audit and OCR/Text share one DOCX extraction helper (`services/docx_extraction.py`) so their
  DOCX character counts cannot diverge (see [ADR-0006](../docs/adr/0006-docx-extraction-and-pii-precision.md)).
- PDF rendering is isolated behind a pdf2image/Poppler adapter; PaddleOCR/PaddlePaddle are an
  optional image build extra so standard quality gates remain model-free.
- OCR render workspaces live only on `/tmp` tmpfs. PaddleOCR requires explicitly provisioned local
  detection/recognition models and never intentionally downloads models as a fallback.
- OCR models are provisioned reproducibly via `scripts/fetch-ocr-models.sh` (`make ocr-models`)
  into `volumes/ocr-models/{text_detection,text_recognition}`, mounted read-only at `/models/ocr`.
  Default models: `PP-OCRv5_mobile_det` + `latin_PP-OCRv5_mobile_rec` (German/Latin). The adapter
  passes model names and disables CPU MKL-DNN; OCR images add libGL/glib/libgomp. Build profiles
  slim/pii/ocr/full via make targets; `make ocr-smoke`/`pii-smoke` test the real runtimes. See
  [ADR-0007](../docs/adr/0007-ocr-runtime-and-model-provisioning.md).
- PII v1 analyzes page text separately where available, preserves exact page-local and global
  offsets, and stores immutable `pii_result` artifacts. It performs no anonymization or redaction.
- Audit, OCR/Text, and PII JSON artifacts live under
  `document-data/{document_id}/artifacts/{artifact_id}.json`; delete removes the original and only
  that document's validated data directory. Old co-located dev data is never migrated or deleted
  automatically and must be re-uploaded or moved manually.
- PII defaults to the high-precision `structured-only` profile (EMAIL_ADDRESS, PHONE_NUMBER,
  IBAN_CODE, CREDIT_CARD, IP_ADDRESS, URL); PERSON/ORGANIZATION/LOCATION and DATE_TIME stay
  supported but opt-in via broader profiles or `PII_ENTITY_TYPES`. The `presidio-analyzer` logger
  is capped at WARNING.
- Engine-4 adds a lazy Presidio `insurance-at-de` pattern/context pack for AT/DE regional and
  insurance/legal/business identifiers, plus named `structured-only` (default), `insurance-at-de`,
  `broad-review`, and `review-heavy` profiles. `PII_ENTITY_TYPES` remains a `custom` override;
  artifacts record the effective profile. See
  [ADR-0012](../docs/adr/0012-insurance-at-de-pii-recognizers.md).
- Engine-5 adds candidate validation: a dependency-free KEEP/SCORE_DOWN/DROP post-processing pass
  (`pii_candidate_validation.py`/`pii_validation_rules.py`) over already-detected candidates,
  applied inside `pii_service.py` before entities are persisted. `pii_result` gains additive
  per-entity `original_score`/`validation_status`/`validation_reasons` and a content-level
  `validation` summary (counts + reason codes only). A `PII_CANDIDATE_VALIDATION_ENABLED` setting
  (default on) is an escape hatch. Validation intensity follows entity type, not profile, so
  PERSON/ORGANIZATION/LOCATION/DATE_TIME stay opt-in exactly as before. See
  [ADR-0013](../docs/adr/0013-pii-candidate-validation.md).
- Presidio/spaCy are isolated behind a lazy adapter and optional `pii` image extra; the pinned
  German model is installed at image build time and never downloaded during a request.
- The document detail UI invokes each workstation manually, surfaces missing/stale/current
  lineage, and overlays only PII results matching the displayed text artifact.
- PII highlighting validates Python Unicode-codepoint offsets in a pure tested helper; overlapping
  entities are resolved deterministically while the entity list retains every detection.
- `GET /api/config` exposes the effective limits so the frontend mirrors the backend.
- Security headers owned by nginx; backend emits structured JSON request logs with a
  correlation id (surfaced to users on errors).
- A private, stdlib-only local benchmark runner (`scripts/benchmark/`, `make benchmark-private`)
  reads existing audit/text/pii artifacts and matches them against private benchmark
  metadata/candidate PII ground truth kept only under `volumes/benchmark/` (git-ignored). It never
  triggers processing and its `privacy_guard.py` blocks report generation if a raw text/value
  field or PII-shaped string would otherwise be written. See
  [ADR-0010](../docs/adr/0010-private-benchmark-runner.md) and
  [`scripts/benchmark/README.md`](../scripts/benchmark/README.md).
- An engine capability model under [`docs/engine/`](../docs/engine/README.md) defines the OCR/Text,
  PII/sensitive-data, and review/feedback sub-engines as 0–10 level ladders, plus the artifact
  model, quality metrics, tool strategy, target architecture (DB + optional local-AI questions),
  and an Engine-0…9 roadmap. Docs-only, no behaviour/dependency change. Current standing: OCR/Text
  **L3 done / L4 partial**, PII **L5 done**, review **L1**, benchmark **L2**. See
  [ADR-0011](../docs/adr/0011-engine-capability-model.md).

## Approach (tool-first / adapter-only)

The de-identification capability will be delivered by integrating **proven open-source tools
via adapters** — OCR/extraction (e.g. OCRmyPDF, Tesseract, MinerU), PII/PHI detection (e.g.
Presidio, noirdoc) and redaction (e.g. PyMuPDF). We do **not** build custom OCR/PII/NER/
redaction intelligence. Our own code is orchestration, the review UI, file handling, export
logic and secure integration. See [`AGENTS.md`](../AGENTS.md).

## Immediate next steps

Driven by the engine roadmap ([`docs/engine/roadmap.md`](../docs/engine/roadmap.md)); benchmark
signals prioritise closing PII detection gaps before review/redaction:

1. Engine-6 — Review/feedback model: persist human confirm/reject/add over immutable PII labels.
2. Engine-2 — OCR L4–L5 hardening (OCR confidence + `quality_report` + human-readable text).
3. Add address/contact-line coverage and per-profile benchmark reporting.
4. Add CI/CD gates (lint/typecheck/test/SAST/SCA) and a benchmark regression gate.

## Active constraints

- Docker-first: no host-local installs; everything runs in containers.
- No custom detection/OCR intelligence — integrate proven tools via adapters only.
- Keep `.ai/` files concise. For commit/push/merge rules see "Approval" in `AGENTS.md`.
