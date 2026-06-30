# Backend — De-Identification Pilot API

FastAPI service that accepts, validates, audits, and extracts text from document uploads. Part of the
`privacy-deidentification-pilot` stack; see the repository root `README.md` for the full
picture and how to run everything with Docker Compose.

## Endpoints

- `GET /api/health/live` — liveness.
- `GET /api/health/ready` — readiness (upload directory writable).
- `POST /api/uploads` — upload one document (`multipart/form-data`, field `file`).
- `POST /api/documents/{id}/audit` — verify and audit an original artifact.
- `GET /api/documents/{id}/audit` — return the newest audit result.
- `POST /api/documents/{id}/ocr` — route text extraction from the original and latest audit.
- `GET /api/documents/{id}/ocr` — return the newest text result.
- `GET /api/docs` — OpenAPI / Swagger UI.

## Layout

- `app/config.py` — environment-based settings (`pydantic-settings`).
- `app/api/` — HTTP routers (health, uploads, documents, audits).
- `app/services/upload_service.py` — validation + safe storage (trust boundary).
- `app/services/audit_service.py` — synchronous PDF/DOCX/image structural analysis.
- `app/services/ocr_service.py` — per-page text-layer/OCR routing and text artifact creation.
- `app/services/ocr_adapters.py` — lazy PaddleOCR adapter boundary.
- `app/services/pdf_renderer.py` — replaceable pdf2image/Poppler page renderer.
- `app/services/artifact_service.py` — atomic file-based derived artifact storage.
- `app/main.py` — app factory, middleware (security headers, correlation id), error handling.
- `tests/` — pytest suite (validation paths, health).

## Local quality commands

Run from the repository root via the `Makefile` (`make lint`, `make typecheck`, `make test`),
which executes these inside the backend container.

PaddleOCR and PaddlePaddle are an optional `ocr` dependency extra. Docker Compose builds without
it by default; set `INSTALL_OCR=true` when image/scanned-page OCR is required. Text-only PDFs and
DOCX extraction do not initialize or require PaddleOCR. Real OCR additionally requires an
`OCR_MODEL_DIR` with local `text_detection/` and `text_recognition/` directories; missing or
uninitializable models return `503` without an intentional download fallback. See the root README
for the read-only model-volume layout and smoke-test command.
