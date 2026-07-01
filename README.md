# Privacy De-Identification

A Docker-first application foundation for privacy-focused document preparation and de-identification workflows.

Users can upload documents through a web interface. The backend validates the upload, stores the file safely under `./volumes/uploads` on the host, and exposes health checks for local operation and development.

> **Step 4:** This version provides upload/document management, structural Audit v1, the
> synchronous OCR/Text Workstation v1, and detection-only PII Workstation v1. Review,
> anonymization and redaction remain separate later steps.

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
| POST   | `/api/documents/{id}/ocr`   | Create an immutable routed text result                |
| GET    | `/api/documents/{id}/ocr`    | Get the newest text result                            |
| POST   | `/api/documents/{id}/pii`   | Detect and label PII in the newest text result         |
| GET    | `/api/documents/{id}/pii`    | Get the newest PII result                              |

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

### Optional OCR runtime

PDF text layers and DOCX body text are extracted without PaddleOCR. Image documents and PDF
pages without a text layer require the optional PaddleOCR/PaddlePaddle runtime:

```bash
INSTALL_OCR=true docker compose build backend
```

The regular image deliberately omits those heavy packages and returns `503` only when a request
actually needs PaddleOCR. Imports and model initialization are lazy, so startup and all quality
gates remain model-free. Poppler is installed in the backend runtime for the encapsulated
`pdf2image` PDF-page renderer. Rendered pages use the container's `/tmp` tmpfs and are never
written to the persistent upload volume.

Installing the optional packages is not sufficient to enable OCR. Approved model files must be
prepared separately, made available inside the container, and selected with `OCR_MODEL_DIR`.
The directory must contain both model directories:

```text
/models/ocr/
├── text_detection/
└── text_recognition/
```

The adapter passes both local paths to PaddleOCR and returns `503` before importing PaddleOCR if
the configuration or directories are missing. It never intentionally falls back to downloading
models. A deployment can bake those directories into a dedicated OCR runtime image or mount them
read-only through a Compose override. PaddlePaddle's published platform wheels determine which
CPU architectures can build the optional image; on ARM hosts an amd64 container/emulation may be
required.

With compatible, locally provisioned models under `./models/ocr`, the optional runtime can be
built and smoke-tested without a test-suite model download:

```bash
INSTALL_OCR=true docker compose build backend

docker compose run --rm --no-deps \
  -e OCR_MODEL_DIR=/models/ocr \
  -v "$PWD/models/ocr:/models/ocr:ro" \
  backend python -c "from pathlib import Path; from PIL import Image, ImageDraw, ImageFont; from app.services.ocr_adapters import PaddleOcrAdapter; p=Path('/tmp/ocr-smoke.png'); image=Image.new('RGB', (320, 80), 'white'); font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 32); ImageDraw.Draw(image).text((10, 20), 'OCR smoke', fill='black', font=font); image.save(p); text=PaddleOcrAdapter(Path('/models/ocr')).extract_text(p); print(text); assert text.strip(), 'OCR returned no text'"
```

This smoke test is deliberately separate from `make test`: it requires platform-compatible
PaddlePaddle wheels, sufficient RAM, and explicitly provisioned model files.

### Optional PII runtime

PII Workstation v1 uses Microsoft Presidio Analyzer and spaCy behind a lazy adapter. The regular
image omits both packages. Build a PII-capable image explicitly:

```bash
INSTALL_PII=true docker compose build backend
```

The optional `pii` dependency extra pins Presidio, spaCy, and the German
`de_core_news_sm` model wheel, so the model is installed reproducibly during image build. Requests
never download a model. Missing packages, an unavailable model, or a language/model mismatch
returns `503`; normal tests replace the adapter and load no model.

The runtime can be smoke-tested separately from the standard quality gates:

```bash
INSTALL_PII=true docker compose build backend
docker compose run --rm --no-deps backend python -c "from app.services.pii_adapters import PresidioAnalyzerAdapter; a=PresidioAnalyzerAdapter('de', 'de_core_news_sm'); r=a.analyze('Kontakt: max@example.at', 'de', ('EMAIL_ADDRESS',), 0.5); print(r); assert any(x.entity_type == 'EMAIL_ADDRESS' for x in r)"
```

PII v1 only detects and labels spans in the persisted text artifact. It does not anonymize,
mask, redact, or alter source documents. Detected entity text is stored in a cleartext JSON
artifact under the same protected document artifact directory and is not written to logs.

## Configuration

Configuration is handled through environment variables.

See [`.env.example`](.env.example) for available settings, including:

* upload size limit
* allowed file extensions
* upload directory
* optional local OCR model directory
* optional PII runtime, language, model, score threshold, and entity allowlist
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
