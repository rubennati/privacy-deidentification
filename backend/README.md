# Backend — De-Identification Pilot API

FastAPI service that accepts, validates, audits, and extracts text from document uploads. Part of the
`privacy-deidentification-pilot` stack; see the repository root `README.md` for the full
picture and how to run everything with Docker Compose. The service detects and labels PII; it does
not anonymize, redact, or pseudonymize documents.

## Endpoints

- `GET /api/health/live` — liveness.
- `GET /api/health/ready` — readiness (both persistent storage directories writable).
- `GET /api/config` — safe effective upload/PII defaults and the dev-settings gate.
- `POST /api/uploads` — upload one document (`multipart/form-data`, field `file`).
- `GET /api/documents` — list uploaded documents, newest first.
- `GET /api/documents/{id}` — return one uploaded document's metadata.
- `DELETE /api/documents/{id}` — delete one document and its validated local data directory.
- `POST /api/documents/{id}/audit` — verify and audit an original artifact.
- `GET /api/documents/{id}/audit` — return the newest audit result.
- `POST /api/documents/{id}/ocr` — route text extraction from the original and latest audit.
- `GET /api/documents/{id}/ocr` — return the newest text result.
- `POST /api/documents/{id}/pii` — detect and label PII in the newest text result.
- `GET /api/documents/{id}/pii` — return the newest PII result.
- `POST /api/documents/{id}/pii/feedback` — append gated dev-only entity feedback.
- `GET /api/documents/{id}/pii/feedback` — restore gated dev-only feedback for an artifact.
- `GET /api/docs` — OpenAPI / Swagger UI.

## Layout

- `app/config.py` — environment-based settings (`pydantic-settings`).
- `app/api/` — HTTP routers (health, config, uploads, documents, audits, OCR, PII, feedback).
- `app/services/upload_service.py` — validation + safe original storage (trust boundary).
- `app/services/document_service.py` — per-document metadata storage and deletion.
- `app/services/audit_service.py` — synchronous PDF/DOCX/image structural analysis.
- `app/services/ocr_service.py` — per-page text-layer/OCR routing and text artifact creation.
- `app/services/ocr_adapters.py` — lazy PaddleOCR adapter boundary.
- `app/services/pdf_renderer.py` — replaceable pdf2image/Poppler page renderer.
- `app/services/pii_service.py` — page-aware detection orchestration and PII artifact creation.
- `app/services/pii_adapters.py` — lazy Presidio/spaCy adapter boundary.
- `app/services/feedback_service.py` — gated local feedback side-channel and restore logic.
- `app/services/artifact_service.py` — atomic per-document derived artifact storage.
- `app/main.py` — app factory, correlation-id/logging middleware, and error handling.
- `tests/` — pytest suite for API, storage, OCR/Text, PII, and feedback behaviour.

nginx owns browser-facing security headers. The backend is private to the Compose network and
provides correlation IDs plus structured request/error logging.

## Local quality commands

Run from the repository root via the `Makefile` (`make lint`, `make typecheck`, `make test`),
which executes these inside the backend container.

The default Docker runtime image includes PaddleOCR/PaddlePaddle and Presidio/spaCy so the normal
Compose stack is functional without build-profile toggles. OCR model files are still provisioned
separately under `OCR_MODEL_DIR` (`make ocr-models`) and mounted read-only; missing or
uninitializable models return `503` without a request-time download fallback. Text-only PDFs and
DOCX extraction do not initialize PaddleOCR.

The default API mode enqueues OCR jobs for the isolated `ocr-worker`; `OCR_EXECUTION_MODE=sync`
remains a development/test fallback. PII still runs synchronously in the API. PII v1 stores labels
and exact text offsets only — it performs no anonymization or redaction.
