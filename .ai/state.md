# Current State

> If this file conflicts with current git state (branch, commits), trust git.

- Current phase: **Step 2 — Audit station**
- Current objective: Analyze verified originals into immutable structural audit artifacts without
  performing OCR or de-identification.

## Snapshot

- Two-service architecture: `frontend` (nginx serving the React/Vite SPA + reverse-proxy
  `/api`) and `backend` (FastAPI). Backend is not published to the host.
- Pages: `/` landing, `/upload` upload, `/documents` list + delete (top-aligned, consistent).
- Upload validates extension whitelist **and** magic-byte content signature, plus size; stores
  file + JSON metadata sidecar under `./volumes/uploads` (host bind mount).
- New uploads compute SHA-256 while streaming, record a server-verified MIME type, and embed an
  independently identified original artifact in the JSON sidecar.
- Audit v1 verifies original integrity and records per-page PDF text-layer statistics, DOCX
  paragraph statistics, or PNG/JPEG dimensions as immutable JSON artifacts.
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

1. Use Audit v1 results to define routing into an OCR/extraction adapter.
2. Add a detection adapter (Presidio/noirdoc) + a review step before any export.
3. Add CI/CD gates (lint/typecheck/test/SAST/SCA).

## Active constraints

- Docker-first: no host-local installs; everything runs in containers.
- No custom detection/OCR intelligence — integrate proven tools via adapters only.
- Keep `.ai/` files concise. For commit/push/merge rules see "Approval" in `AGENTS.md`.
