# Current State

> If this file conflicts with current git state (branch, commits), trust git.

- Current phase: **Step 1 — Foundation + Upload page**
- Current objective: Ship the Docker-first base structure and a fully working upload page
  (Screenshot 1) that accepts and validates documents via the backend.

## Snapshot

- Two-service architecture: `frontend` (nginx serving the React/Vite SPA + reverse-proxy
  `/api`) and `backend` (FastAPI). Backend is not published to the host.
- Upload endpoint validates file type (PDF/DOCX/PNG/JPG) and size, stores to a volume.

## Immediate next steps

1. Build the de-identification pipeline (text extraction → PII detection → anonymization).
2. Add Screen 2 (document list with job status) and Screen 3 (extracted vs. anonymized).
3. Add CI/CD gates (lint/typecheck/test/SAST/SCA) once a remote exists.

## Active constraints

- Docker-first: no host-local installs; everything runs in containers.
- Keep `.ai/` files concise. For commit/push/merge rules see "Approval" in `AGENTS.md`.
