# Privacy De-Identification

A Docker-first application foundation for privacy-focused document preparation and de-identification workflows.

Users can upload documents through a web interface. The backend validates each upload, stores
only the original bytes under `./volumes/uploads`, and keeps metadata and processing artifacts
separately under `./volumes/document-data`.

> **Step 5:** This version provides upload/document management, structural Audit v1, the
> synchronous OCR/Text and detection-only PII workstations, plus a manual document review UI.
> Anonymization and redaction remain separate later steps.

## Approach: tool-first / adapter-only

The de-identification capability will be delivered by **integrating proven open-source tools
behind adapters** — not by building custom intelligence. Extraction/OCR (e.g. OCRmyPDF,
Tesseract, MinerU), PII/PHI detection (e.g. Presidio, noirdoc) and redaction (e.g. PyMuPDF)
are integrated behind a port/interface. Our own code is orchestration, the review UI, file
handling, export logic and secure integration. See [`AGENTS.md`](AGENTS.md).

## Engine capability model

The core of the project is the engine: local OCR/Text, local PII/sensitive-data, review/feedback,
and optional (later) local AI assist. [`docs/engine/`](docs/engine/README.md) defines what each
sub-engine should do level 0→10, the artifacts and metrics, the tool strategy, the target
architecture (including the database and optional-local-AI questions), and the reframed roadmap.
See [ADR-0011](docs/adr/0011-engine-capability-model.md). Current standing (summary): OCR/Text at
Level 3 (Level 4 partial), PII at Level 1 (Level 4 foundation), review at Level 1.

## Architecture

```text
Browser ──http://localhost:8080──▶ frontend (nginx)
                                     ├─ /       → React/Vite SPA
                                     └─ /api/*  → reverse proxy ─▶ backend (FastAPI :8000)
                                                                    ├─ originals
                                                                    │  ./volumes/uploads
                                                                    └─ metadata + artifacts
                                                                       ./volumes/document-data
```

* **frontend** — React 18 + Vite + TypeScript + Tailwind, served by nginx. The frontend is the only public entry point and proxies API calls to the backend.
* **backend** — Python 3.12 + FastAPI. Validates uploads, stores originals, and manages document metadata and immutable result artifacts in separate storage roots.
* **networking** — the backend is not published to the host. It is reachable only inside the Docker Compose network through the frontend proxy.
* **runtime data** — `/data/uploads` is bind-mounted from `./volumes/uploads` for originals only; `/data/document-data` is bind-mounted from `./volumes/document-data` for metadata and artifacts. Neither host directory is committed (see `.gitignore`).

See [`docs/adr/0001-stack-and-architecture.md`](docs/adr/0001-stack-and-architecture.md) for the stack decision and rationale.

## Requirements

* Docker Engine with the Compose plugin (`docker compose`)

No local Python or Node.js installation is required for normal development commands. Tooling runs in containers.

## Quick start

```bash
cp .env.example .env        # optional; defaults are built in
make up                     # slim stack — no OCR/PII runtime
```

Open:

```text
http://localhost:8080
```

Stop the stack:

```bash
make down
```

### Runtime profiles

The optional OCR and PII runtimes are heavy, so the default image is slim. The profile is chosen
by the make target (not by `.env`), so `make up` is always slim:

| Target | OCR runtime | PII runtime | Notes |
| --- | --- | --- | --- |
| `make up` | – | – | default, slim/CI |
| `make up-pii` | – | ✓ | Presidio/spaCy |
| `make up-ocr` | ✓ | – | needs `make ocr-models` first |
| `make up-full` | ✓ | ✓ | needs `make ocr-models` first |

`make build`, `build-pii`, `build-ocr`, `build-full` build the matching images without starting
them. Text PDFs and DOCX (including tables) are extracted **without** OCR; only image documents
and scanned PDF pages need the OCR runtime plus provisioned models.

## API

| Method | Path                   | Description                                                |
| ------ | ---------------------- | ---------------------------------------------------------- |
| GET    | `/api/health/live`     | Liveness check                                             |
| GET    | `/api/health/ready`    | Readiness check for both persistent storage directories    |
| GET    | `/api/config`          | Effective upload constraints (size limit, allowed types)   |
| POST   | `/api/uploads`         | Upload one document via `multipart/form-data` field `file` |
| GET    | `/api/documents`       | List uploaded documents, newest first                      |
| GET    | `/api/documents/{id}`  | Get one uploaded document                                  |
| DELETE | `/api/documents/{id}`  | Delete a document's file and metadata                      |
| POST   | `/api/documents/{id}/audit` | Create an immutable Audit v1 result (per-page text-quality) |
| GET    | `/api/documents/{id}/audit`  | Get the newest Audit v1 result                       |
| POST   | `/api/documents/{id}/ocr`   | Create an immutable text result (per-page text-layer/OCR) |
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

### Storage layout

New documents use two deliberately separate roots:

```text
volumes/
├── uploads/
│   └── <document_id>.<validated_extension>
└── document-data/
    └── <document_id>/
        ├── document.json
        └── artifacts/
            └── <artifact_id>.json
```

`UPLOAD_STORAGE_DIR` contains byte-identical originals only. Storage filenames are generated
from a server-side UUID; the user-visible Unicode filename is retained only in `document.json`
and never used as a path. `DOCUMENT_DATA_DIR` contains one validated UUID-named directory per
document. Audit, OCR/Text, and PII results are all immutable JSON files in that document's
`artifacts/` directory. Deleting a document removes its UUID-named original and exactly its own
document-data directory.

#### Existing local development data

There is no automatic migration and startup never moves or deletes existing files. Data created
by older versions (`<id>.meta.json` and `artifacts/<id>/` below `volumes/uploads`) is intentionally
not discovered by the new layout. For local development, re-upload those documents if they are
still needed, or copy them manually only after backing up `volumes/` and reshaping them to the
layout above. Old files remain untouched until a developer removes them explicitly.

### Text-layer quality gate and page-level OCR fallback

`has_text_layer` alone is not enough. Some PDFs ship a formally present but **broken/encoded**
text layer: many characters, almost no letters, mostly digits/symbols/control characters.
Extracting that layer yields garbage that pollutes PII detection, while OCR of the same page
produces usable text. Audit therefore assesses each PDF page's *character/token plausibility* with
a dependency-free heuristic (no ML, no dictionary; see
[`text_quality.py`](backend/app/services/text_quality.py)) and records the verdict additively on
the page — only aggregate metrics, **never the page text**:

```json
{
  "page_number": 1,
  "has_text_layer": true,
  "text_char_count": 6183,
  "text_quality_status": "BROKEN_TEXT_LAYER",
  "text_quality_score": 0,
  "text_quality_reasons": ["very_low_letter_ratio", "high_symbol_or_digit_ratio", "few_word_tokens"],
  "recommended_text_source": "ocr",
  "needs_ocr": true
}
```

| Status | Meaning | OCR/Text routing |
| ------ | ------- | ---------------- |
| `GOOD_TEXT_LAYER` | Enough text, plausible characters/tokens | Use text layer |
| `LOW_CONFIDENCE_TEXT_LAYER` | Sparse or mixed signals (e.g. a short line, or a partly-usable scan page) | Use text layer (conservative) |
| `BROKEN_TEXT_LAYER` | Enough characters, but clearly implausible | **OCR** |
| `EMPTY_TEXT_LAYER` | No meaningful text (blank or scanned page) | **OCR** |

A high digit ratio alone never means "broken": tables and invoices are number-heavy. The decisive
signal is the near-total absence of **real words** — broken pages extract as digit/symbol tokens
with `letter_ratio ≈ 0` and no word tokens, while even the most number-heavy legitimate page keeps
its label words (`letter_ratio ≥ 0.64` on the local corpus). A hard fail therefore requires a
symbol/digit-dominated page together with almost no letters (or essentially no real words).
Thresholds are deliberately conservative and covered by unit tests
([`test_text_quality.py`](backend/tests/test_text_quality.py)).

Consequences:

- OCR/Text decides **per page**. A clean text-layer PDF never renders a page or initializes
  PaddleOCR; a mixed PDF OCRs only the empty/broken pages.
- A broken text layer is **never silently used** as the result. If a page needs OCR and the OCR
  runtime/models are missing, the request fails cleanly with `503` (the existing behavior) instead
  of falling back to garbage.
- Audit artifacts written before this gate carry no `needs_ocr`; routing then falls back to the
  original rule (OCR only pages without any text layer).

### Optional OCR runtime

PDF text layers and DOCX text are extracted without PaddleOCR. DOCX extraction is table-aware: a
shared helper walks the document body in order and captures paragraphs, table cells (rows
newline-separated, cells tab-separated), and defined section headers/footers, so table content is
no longer dropped. Audit and OCR/Text use the same helper and therefore report the same DOCX
character count. Image documents and PDF pages without a text layer require the optional PaddleOCR/PaddlePaddle
runtime **plus** locally provisioned models. The regular image deliberately omits those heavy
packages and returns `503` only when a request actually needs PaddleOCR. Imports and model
initialization are lazy, so startup and all quality gates remain model-free. Poppler is installed
for the encapsulated `pdf2image` PDF-page renderer; rendered pages use the container's `/tmp`
tmpfs and are never written to the persistent upload volume.

#### 1. Provision the models (once)

```bash
make ocr-models
```

This idempotent script downloads the default models from the official Hugging Face
`PaddlePaddle/*` repositories into `./volumes/ocr-models`, in the layout the adapter expects:

```text
volumes/ocr-models/
├── text_detection/     # PP-OCRv5_mobile_det
└── text_recognition/   # latin_PP-OCRv5_mobile_rec
```

**Model choice.** The default is the CPU-friendly **mobile** PP-OCRv5 pair (~13 MB total):
`PP-OCRv5_mobile_det` for detection and `latin_PP-OCRv5_mobile_rec` for recognition. The Latin
recognizer covers German and other Latin-script European languages, including umlauts and `ß`,
which the default (Chinese/English) recognizer does not. The heavier `*_server_*` variants offer
higher accuracy at a much larger CPU/memory cost and are a documented future option, not the
default. Override the models via `OCR_DET_MODEL` / `OCR_REC_MODEL` for the script and the matching
`OCR_DETECTION_MODEL_NAME` / `OCR_RECOGNITION_MODEL_NAME` for the backend. The models are never
committed (`.gitignore: /volumes/*`) and never downloaded at request time.

#### 2. Build and run the OCR runtime

```bash
make up-ocr        # or: make up-full  (OCR + PII)
```

Compose mounts the models read-only at `/models/ocr` and sets `OCR_MODEL_DIR=/models/ocr`. The
adapter passes both directories **and** the model names to PaddleOCR (PaddleOCR 3.x rejects a
non-default local model without its name) and returns `503` before importing PaddleOCR if the
directories are missing. It never falls back to downloading models.

#### 3. Smoke-test the runtime

```bash
make ocr-smoke     # builds the OCR image, renders a synthetic image, asserts text is recognized
make pii-smoke     # equivalent for the PII runtime
```

The smoke tests are deliberately separate from `make test`: they need the heavy runtime, and
`ocr-smoke` also needs the provisioned models. They fail with a clear message when models or
packages are missing.

#### Notes and caveats

- **CPU inference.** MKL-DNN (oneDNN) is disabled in the adapter: PaddlePaddle 3.x enables it by
  default for CPU, but its oneDNN path crashes on the PP-OCRv5 models
  (`ConvertPirAttribute2RuntimeAttribute not support`). Disabling it trades a little speed for a
  stable CPU path.
- **Speed.** OCR is synchronous by design (no queue). CPU OCR of a multi-page scan can take a few
  minutes; the nginx `/api/` proxy timeout is raised to 600 s so browser requests do not 504.
- **Apple Silicon / ARM.** PaddlePaddle's published wheels determine which CPU architectures can
  build the OCR image. It builds and runs natively on `linux/amd64`; on ARM hosts (Apple Silicon)
  an `amd64` build/emulation may be required and has not been verified here.
- **buildx warning.** `docker compose build` may print a legacy-builder warning; it is benign.
  Set `DOCKER_BUILDKIT=1` to silence it.

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

PII coverage is selected with `PII_PROFILE`:

| Profile | Coverage |
| --- | --- |
| `structured-only` | EMAIL, PHONE, IBAN, CREDIT_CARD, IP, URL — precision-first default |
| `insurance-at-de` | structured + AT/DE and insurance/legal/business identifiers |
| `broad-review` | insurance-at-de + PERSON, ORGANIZATION, LOCATION |
| `review-heavy` | broad-review + DATE_TIME |

The `insurance-at-de` pack adds `UID_AT`, `FN_AT`, `SVNR_AT`, `TAX_ID_AT`, `BIC`,
`LICENSE_PLATE_AT`, `PASSPORT_NUMBER`, `ID_CARD_NUMBER`, `POLICY_NUMBER`, `CLAIM_NUMBER`,
`CONTRACT_NUMBER`, `CASE_NUMBER`, `FILE_REFERENCE`, `REPORT_NUMBER`, `ASSESSMENT_NUMBER`,
`INVOICE_NUMBER`, `OFFER_NUMBER`, `CUSTOMER_NUMBER`, `PROJECT_ID`, `TRANSACTION_ID`, and `USER_ID`.
The last group includes sensitive document metadata, not only classical PII. Generic domain values
require an adjacent label; strong, type-specific formats can match directly. Presidio's existing
types are reused for AT/DE phone, IBAN, credit card, and URL improvements.

`structured-only` remains the default. The spaCy NER types remain **opt-in** because the small
German model over-tags them at a fixed score that the score threshold cannot filter. Select a
profile, for example `PII_PROFILE=insurance-at-de`. `PII_ENTITY_TYPES` remains a backwards-
compatible explicit allowlist override and is recorded as profile `custom` if it differs from the
selected profile. The score threshold stays `0.5`. Candidate validation/false-positive suppression
is deliberately not part of this pack. The `presidio-analyzer` logger is capped at WARNING so its
initialization messages do not flood logs, while genuine warnings still surface.

The runtime can be smoke-tested separately from the standard quality gates:

```bash
INSTALL_PII=true docker compose build backend
docker compose run --rm --no-deps backend python -c "from app.services.pii_adapters import PresidioAnalyzerAdapter; a=PresidioAnalyzerAdapter('de', 'de_core_news_sm'); r=a.analyze('Kontakt: max@example.at', 'de', ('EMAIL_ADDRESS',), 0.5); print(r); assert any(x.entity_type == 'EMAIL_ADDRESS' for x in r)"
```

PII v1 only detects and labels spans in the persisted text artifact. It does not anonymize,
mask, redact, or alter source documents. Detected entity text is stored in a cleartext JSON
artifact under the same protected document artifact directory and is not written to logs.

## Manual document review

Open a document from `/documents` to use the detail page at `/documents/{id}`. Audit, OCR/Text,
and PII are started explicitly and never trigger the next station automatically. The page keeps
artifact lineage visible, marks stale downstream results, and only overlays PII whose input text
artifact matches the displayed text. PII highlighting uses Unicode codepoint offsets and renders
plain React text nodes—no HTML injection or source-text logging.

## Private OCR/PII benchmark

`scripts/benchmark/` is a local-only, standard-library-only tool that measures OCR/text-layer
routing and PII precision/recall/F1 against a private local document corpus and a private
candidate PII ground truth, without generating or committing any of that data:

```bash
make benchmark-private          # markdown + JSON + CSV report under volumes/benchmark/reports/
make benchmark-private-json     # JSON only
```

It only **reads** existing `document.json`/`audit_result`/`text_result`/`pii_result` artifacts
under `volumes/document-data/` — it never triggers audit/OCR/PII processing, calls the API, or
modifies/deletes a document. Missing artifacts are reported as `missing`, not generated. The
private benchmark inputs (`volumes/benchmark/ocr_pii_benchmark_*.json`) and every generated
report live under `volumes/`, which is entirely git-ignored (`/volumes/*`) — real documents,
their metadata, and any extracted PII never reach the repository. A privacy guard
(`scripts/benchmark/privacy_guard.py`) blocks report generation if a forbidden field name or a
PII-shaped string is ever about to be written. See [`scripts/benchmark/README.md`](scripts/benchmark/README.md)
for the full matching/metrics design and `make benchmark-test` for its synthetic-data test suite.

## Configuration

Configuration is handled through environment variables.

See [`.env.example`](.env.example) for available settings, including:

* upload size limit
* allowed file extensions
* original-upload directory (`UPLOAD_STORAGE_DIR`)
* document metadata/artifact directory (`DOCUMENT_DATA_DIR`)
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
make benchmark-private   # private local OCR/PII benchmark report (see above)
make benchmark-test      # synthetic-data unit tests for the benchmark runner
```

## Repository structure

```text
.
├─ .ai/                  # AI collaboration workspace
├─ backend/              # FastAPI backend
├─ frontend/             # React/Vite frontend served by nginx
├─ scripts/benchmark/    # Private local OCR/PII benchmark runner (see scripts/benchmark/README.md)
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
