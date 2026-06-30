# privacy-deidentification-pilot

A pilot for a document **de-identification pipeline**. Users upload documents
(PDF / DOCX / PNG / JPG); the system will extract text, detect sensitive data (PII), and
return an anonymized version. GDPR-focused ("DSGVO-konform").

> **Step 1 (this version):** the Docker-first foundation plus a fully working **upload
> page**. Upload via click, drag & drop, or paste (Ctrl+V); the backend validates the file
> (type + size) and stores it. The de-identification pipeline and the document/result views
> come in later steps.

## Architecture

```
Browser ──http://localhost:8080──▶  frontend (nginx)
                                      ├─ /          → React/Vite SPA (static)
                                      └─ /api/*      → reverse-proxy ─▶ backend (FastAPI :8000)
                                                                          └─ stores uploads in the
                                                                             "uploads" Docker volume
```

- **frontend** — React 18 + Vite + TypeScript + Tailwind, served by nginx. Adds security
  headers and proxies API calls so the app has a single origin.
- **backend** — Python 3.12 + FastAPI. Validates and accepts uploads; exposes health checks.
  Not published to the host — reachable only on the internal Docker network.

See [`docs/adr/0001-stack-and-architecture.md`](docs/adr/0001-stack-and-architecture.md) for
the rationale.

## Requirements

- Docker Engine with the Compose plugin (`docker compose`). Nothing else is installed on the
  host — all tooling runs in containers.

## Quick start

```bash
cp .env.example .env        # optional; sensible defaults are built in
docker compose up -d --build
```

Then open <http://localhost:8080> and upload a document.

Stop the stack:

```bash
docker compose down
```

## API

| Method | Path                 | Description                                         |
| ------ | -------------------- | --------------------------------------------------- |
| GET    | `/api/health/live`   | Liveness — the process is running.                  |
| GET    | `/api/health/ready`  | Readiness — the upload directory is writable.       |
| POST   | `/api/uploads`       | Upload one document (`multipart/form-data`, `file`).|

`POST /api/uploads` returns `201` with `{ id, filename, size, status }`. Invalid uploads
return a clean error (`415` wrong type, `413` too large, `400` empty/missing) with a
correlation id — never a stack trace.

## Configuration

All configuration is via environment variables (12-factor). See
[`.env.example`](.env.example) for the full list (upload size limit, allowed extensions,
upload directory, log level).

## Development & quality

Everything runs in containers via the `Makefile`:

```bash
make lint        # Ruff (Python) + ESLint (TypeScript)
make typecheck   # mypy (Python) + tsc (TypeScript)
make test        # pytest (backend)
make build       # build both images
make up / down   # start / stop the stack
```

## Project conventions

This repo adopts the AI-collaboration parts of
[ai-project-standard](https://github.com/rubennati/ai-project-standard): the `.ai/`
operational workspace, `AGENTS.md` (source of truth for AI tools) with `CLAUDE.md` as a
pointer, and shared quality commands. See `AGENTS.md` for the workflow and approval rules.
