# Backend — De-Identification Pilot API

FastAPI service that accepts, validates, and structurally audits document uploads. Part of the
`privacy-deidentification-pilot` stack; see the repository root `README.md` for the full
picture and how to run everything with Docker Compose.

## Endpoints

- `GET /api/health/live` — liveness.
- `GET /api/health/ready` — readiness (upload directory writable).
- `POST /api/uploads` — upload one document (`multipart/form-data`, field `file`).
- `POST /api/documents/{id}/audit` — verify and audit an original artifact.
- `GET /api/documents/{id}/audit` — return the newest audit result.
- `GET /api/docs` — OpenAPI / Swagger UI.

## Layout

- `app/config.py` — environment-based settings (`pydantic-settings`).
- `app/api/` — HTTP routers (health, uploads, documents, audits).
- `app/services/upload_service.py` — validation + safe storage (trust boundary).
- `app/services/audit_service.py` — synchronous PDF/DOCX/image structural analysis.
- `app/services/artifact_service.py` — atomic file-based derived artifact storage.
- `app/main.py` — app factory, middleware (security headers, correlation id), error handling.
- `tests/` — pytest suite (validation paths, health).

## Local quality commands

Run from the repository root via the `Makefile` (`make lint`, `make typecheck`, `make test`),
which executes these inside the backend container.
