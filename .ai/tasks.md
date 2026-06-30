# Tasks

## Step 1 — Foundation + Upload page (current)

- [x] Repo conventions (`.ai/`, `AGENTS.md`, docs, ADR).
- [x] FastAPI backend: health + upload endpoints with validation.
- [x] Backend tests (validation paths).
- [x] React/Vite upload page (Screenshot 1): click / drag&drop / paste.
- [x] docker-compose + Makefile; end-to-end verification.

## Backlog (next steps)

- [ ] Text extraction from uploaded documents.
- [ ] PII detection + anonymization pipeline.
- [ ] Screen 2: document list with job status.
- [ ] Screen 3: extracted vs. anonymized side-by-side + downloads.
- [ ] Persistence (database), async worker/queue.
- [ ] CI/CD gates (lint/typecheck/test/SAST/SCA/SBOM).
- [ ] Magic-byte content sniffing for uploads.
