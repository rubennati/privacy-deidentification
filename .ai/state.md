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
  file + JSON metadata sidecar under `./volumes/uploads` (host bind mount).
- New uploads compute SHA-256 while streaming, record a server-verified MIME type, and embed an
  independently identified original artifact in the JSON sidecar.
- Audit v1 verifies original integrity and records per-page PDF text-layer statistics, DOCX
  paragraph statistics, or PNG/JPEG dimensions as immutable JSON artifacts.
- OCR/Text v1 reverifies the original, routes PDF pages individually between pypdf and a lazy
  PaddleOCR adapter, extracts DOCX text via a shared table-aware helper (paragraphs, tables, and
  section headers/footers in document order), and stores immutable text artifacts.
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
- PII defaults to high-precision structured recognizers only (EMAIL_ADDRESS, PHONE_NUMBER,
  IBAN_CODE, CREDIT_CARD, IP_ADDRESS, URL); PERSON/ORGANIZATION/LOCATION and DATE_TIME stay
  supported but opt-in via `PII_ENTITY_TYPES`. The `presidio-analyzer` logger is capped at WARNING.
- Presidio/spaCy are isolated behind a lazy adapter and optional `pii` image extra; the pinned
  German model is installed at image build time and never downloaded during a request.
- The document detail UI invokes each workstation manually, surfaces missing/stale/current
  lineage, and overlays only PII results matching the displayed text artifact.
- PII highlighting validates Python Unicode-codepoint offsets in a pure tested helper; overlapping
  entities are resolved deterministically while the entity list retains every detection.
- `GET /api/config` exposes the effective limits so the frontend mirrors the backend.
- Security headers owned by nginx; backend emits structured JSON request logs with a
  correlation id (surfaced to users on errors).

## Approach (tool-first / adapter-only)

The de-identification capability will be delivered by integrating **proven open-source tools
via adapters** — OCR/extraction (e.g. OCRmyPDF, Tesseract, MinerU), PII/PHI detection (e.g.
Presidio, noirdoc) and redaction (e.g. PyMuPDF). We do **not** build custom OCR/PII/NER/
redaction intelligence. Our own code is orchestration, the review UI, file handling, export
logic and secure integration. See [`AGENTS.md`](../AGENTS.md).

## Immediate next steps

1. Define human review decisions over immutable PII labels.
2. Design a separate redaction/export station after review approval.
3. Add CI/CD gates (lint/typecheck/test/SAST/SCA).

## Active constraints

- Docker-first: no host-local installs; everything runs in containers.
- No custom detection/OCR intelligence — integrate proven tools via adapters only.
- Keep `.ai/` files concise. For commit/push/merge rules see "Approval" in `AGENTS.md`.
