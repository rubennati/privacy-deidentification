# Current State

> If this file conflicts with current git state (branch, commits), trust git.

- Current phase: **Step 5 — Manual document review UI**
- Current objective: Let users inspect one document, explicitly run Audit/OCR/PII, and review
  lineage-safe PII highlights without modifying text or source documents.

## Snapshot

- Branch policy: feature PRs target `dev`; `main` is the curated user-stable local-app branch and
  receives only intentional promotions from `dev` or explicit hotfixes. Windows install/update
  tooling always follows `main`.
- Windows users can bootstrap the local Docker Compose app under `$HOME\PrivacyDeID` with
  `scripts/windows/install.ps1`, then use the generated `deid.ps1` launcher for safe
  `start`/`update`/`stop`/`status` operations. Updates refuse dirty working trees and never delete
  local data.
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
- Deterministic `ADDRESS`/`CONTACT_LINE`/`CUSTOMER_LINE` recognizers (street shape + labelled-line
  capture with content-shape checks) extend the pack; the types form the `ADDRESS_CONTACT_TYPES`
  group in `insurance-at-de`/`broad-review`/`review-heavy` and the benchmark's
  `address_contact_types` group. See
  [ADR-0015](../docs/adr/0015-structured-address-contact-line-recognizers.md).
- Presidio/spaCy are isolated behind a lazy adapter and optional `pii` image extra; the pinned
  German model is installed at image build time and never downloaded during a request.
- The document detail UI invokes each workstation manually, surfaces missing/stale/current
  lineage, and overlays only PII results matching the displayed text artifact.
- `GET /api/config` now also exposes safe, read-only PII defaults plus the
  `ENABLE_DEV_ENGINE_SETTINGS` gate. The gate defaults to off; when enabled, the document detail
  UI may override the named PII profile for one local PII run only. `.env`/backend defaults remain
  authoritative and are never written from the UI.
- `docker-compose.yml` now forwards `ENABLE_DEV_ENGINE_SETTINGS` explicitly to the backend
  container, still defaulting to `false` unless local `.env` opts in.
- New `pii_result` artifacts record effective non-sensitive engine settings under
  `content.engine_settings` (`pii_profile`, candidate validation, score threshold, source) so
  dev-mode runs remain traceable without storing extra text or raw PII.
- Dev-only PII review feedback: gated by `ENABLE_DEV_ENGINE_SETTINGS`. `POST
  /api/documents/{id}/pii/feedback` appends one privacy-safe line; `GET
  /api/documents/{id}/pii/feedback?artifact_id=…` returns the latest verdict per entity key
  (type+start+end+recognizer), no comment/raw value, so the UI restores per-entity state and
  locks a card once feedback exists. Gate off ⇒ both endpoints `403` and the UI hides the
  controls. Entity cards carry a header "Passt" button, an issue picker with per-reason
  explanations, an entity-type legend, and clickable offsets that jump/flash the span in the
  extracted-text view. Analysis input only — not a learning system, never mutates `pii_result`,
  no rules. No document/OCR/entity text is stored.
  Dev review feedback storage is file-based and local:
  `volumes/document-data/<document_id>/feedback/pii_feedback.jsonl` (host side of the existing
  `document-data` bind mount; created on first write, survives `docker compose down`, removed with
  the document, git-ignored). Follow-ups tracked in docs: entity grouping (next review level),
  "Entity Resolution / Overlap Precedence Rules" (separate PR), and display-ordering by
  precise-vs-NER types. See
  [`docs/engine/review-feedback-levels.md`](../docs/engine/review-feedback-levels.md).
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
- An engine capability model under [`docs/engine/`](../docs/engine/README.md) defines the central
  engines on a **0–19 maturity scale** (standard going forward; superseding the earlier 0–10/0–14
  ladders — [ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md)): OCR/Text,
  PII/Sensitive-Data, Review/Human-Feedback, Benchmark/Regression, and Redaction, each with a name,
  description, testable acceptance criteria, and boundary to the next level, plus the artifact model,
  quality metrics, `engine-settings.md`, tool strategy, target architecture (DB + optional local-AI
  questions), and the Engine-0…9 roadmap. Every engine doc has a legacy 0–10 → 0–19 mapping table;
  cross-cutting docs keep legacy citations under a migration-note banner (renumbering tracked).
  Docs-only, no behaviour/dependency change. **Current standing (0–19):**
  - OCR/Text: **L5 done** (text extraction, lineage, OCR runtime, text-layer quality gate, per-page
    routing); L6 OCR confidence / L7 `quality_report` next.
  - PII/Sensitive-Data: **L9 done, L10 partial** — structured + AT/DE + domain recognizers, profiles,
    benchmark, candidate validation (own pipeline stage), context hardening, address/contact-line,
    reproducible `engine_settings`; **dev-only** human feedback capture landed (L10); entity grouping
    (L11) / overlap resolution (L12) / binding review (L13) open.
  - Review/Human-Feedback: **L2 in production**; L3–L5 delivered **dev-only** behind
    `ENABLE_DEV_ENGINE_SETTINGS` (clickable offsets + legend, dev engine-settings override, per-entity
    feedback capture); L6 grouping / L8 `review_result` overlay next.
  - Benchmark/Regression: **L8 done** (matching, routing correctness, PII P/R/F1, privacy guard,
    determinism, validation counts); L9 per-profile-in-one-run next.
  - Redaction/De-Identification: **L0** by design (detection-only); blocked on PII L17–L18, Review
    L8–L9, OCR L10/L15.
  See [ADR-0011](../docs/adr/0011-engine-capability-model.md) and
  [ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md).

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
3. Per-profile benchmark reporting (address/contact-line coverage landed via ADR-0015; the
   remaining unsupported labels are BIRTH_DATE/BIRTH_PLACE/FAMILY_NAME/GIVEN_NAME).
4. Add CI/CD gates (lint/typecheck/test/SAST/SCA) and a benchmark regression gate.

## Active constraints

- Docker-first: no host-local installs; everything runs in containers.
- No custom detection/OCR intelligence — integrate proven tools via adapters only.
- Keep `.ai/` files concise. For commit/push/merge rules see "Approval" in `AGENTS.md`.
