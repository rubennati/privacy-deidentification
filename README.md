# Privacy De-Identification

A Docker-first application foundation for privacy-focused document preparation and de-identification workflows.

Users can upload documents through a web interface. The backend validates the upload, stores the file safely under `./volumes/uploads` on the host, and exposes health checks for local operation and development.

> **Step 2:** This version provides the application foundation, upload/document management and
> a structural Audit v1 station. OCR, review, de-identification and redaction will be added in
> later steps through dedicated tool integrations.

## Approach: tool-first / adapter-only

The de-identification capability will be delivered by **integrating proven open-source tools
behind adapters** — not by building custom intelligence. Extraction/OCR (e.g. OCRmyPDF,
Tesseract, MinerU), PII/PHI detection (e.g. Presidio, noirdoc) and redaction (e.g. PyMuPDF)
are integrated behind a port/interface. Our own code is orchestration, the review UI, file
handling, export logic and secure integration. See [`AGENTS.md`](AGENTS.md).

## Architecture

```text
Browser ──http://localhost:8080──▶ frontend (nginx)
                                     ├─ /       → React/Vite SPA
                                     └─ /api/*  → reverse proxy ─▶ backend (FastAPI :8000)
                                                                    └─ stores uploads under
                                                                       ./volumes/uploads
```

* **frontend** — React 18 + Vite + TypeScript + Tailwind, served by nginx. The frontend is the only public entry point and proxies API calls to the backend.
* **backend** — Python 3.12 + FastAPI. Validates and accepts uploads, exposes health checks and writes accepted files to the upload directory.
* **networking** — the backend is not published to the host. It is reachable only inside the Docker Compose network through the frontend proxy.
* **runtime data** — uploaded files are bind-mounted from the container's `/data/uploads` to `./volumes/uploads` on the host, not committed to the repository (see `.gitignore`).

See [`docs/adr/0001-stack-and-architecture.md`](docs/adr/0001-stack-and-architecture.md) for the stack decision and rationale.

## Requirements

* Docker Engine with the Compose plugin (`docker compose`)

No local Python or Node.js installation is required for normal development commands. Tooling runs in containers.

## Quick start

```bash
cp .env.example .env        # optional; defaults are built in
docker compose up -d --build
```

Open:

```text
http://localhost:8080
```

Stop the stack:

```bash
docker compose down
```

## API

| Method | Path                   | Description                                                |
| ------ | ---------------------- | ---------------------------------------------------------- |
| GET    | `/api/health/live`     | Liveness check                                             |
| GET    | `/api/health/ready`    | Readiness check, including upload directory access         |
| GET    | `/api/config`          | Effective upload constraints (size limit, allowed types)   |
| POST   | `/api/uploads`         | Upload one document via `multipart/form-data` field `file` |
| GET    | `/api/documents`       | List uploaded documents, newest first                      |
| DELETE | `/api/documents/{id}`  | Delete a document's file and metadata                      |
| POST   | `/api/documents/{id}/audit` | Create an immutable Audit v1 result                   |
| GET    | `/api/documents/{id}/audit`  | Get the newest Audit v1 result                       |

`POST /api/uploads` returns `201` with:

```json
{
  "id": "uuid",
  "filename": "document.pdf",
  "size": 12345,
  "status": "received",
  "sha256": "64-character lowercase hex digest",
  "detected_mime_type": "application/pdf",
  "original_artifact": {
    "id": "artifact uuid",
    "document_id": "uuid",
    "kind": "original",
    "storage_filename": "uuid.pdf",
    "sha256": "64-character lowercase hex digest",
    "mime_type": "application/pdf",
    "size_bytes": 12345,
    "created_at": "2026-06-30T18:00:00Z"
  }
}
```

Invalid uploads return clean JSON errors with a correlation ID:

* `400` for missing or empty uploads
* `413` for files exceeding the configured size limit
* `415` for unsupported file types

Stack traces are not exposed to clients.

## Configuration

Configuration is handled through environment variables.

See [`.env.example`](.env.example) for available settings, including:

* upload size limit
* allowed file extensions
* upload directory
* log level

## Development and quality

Common commands are available through the `Makefile`:

```bash
make lint        # Ruff and ESLint
make typecheck   # mypy and TypeScript
make test        # backend tests
make build       # build Docker images
make up          # start the stack
make down        # stop the stack
```

## Repository structure

```text
.
├─ .ai/                  # AI collaboration workspace
├─ backend/              # FastAPI backend
├─ frontend/             # React/Vite frontend served by nginx
├─ docs/adr/             # Architecture decision records
├─ docker-compose.yml
├─ Makefile
├─ AGENTS.md             # Source of truth for AI-assisted development
└─ CLAUDE.md             # Pointer to AGENTS.md and .ai/
```

## Project conventions

This repository adopts the AI-collaboration parts of [`ai-project-standard`](https://github.com/rubennati/ai-project-standard):

* `.ai/` workspace for project state, decisions and task tracking
* `AGENTS.md` as the source of truth for AI-assisted development
* `CLAUDE.md` as a thin pointer to the project rules
* shared quality commands through the `Makefile`

See [`AGENTS.md`](AGENTS.md) for workflow, approval and quality rules.
