# Privacy De-Identification

## Windows Quick Start

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/rubennati/privacy-deidentification/main/scripts/windows/install.ps1 | iex
```

The following commands are then available:

```powershell
& "$HOME\PrivacyDeID\deid.ps1" start
& "$HOME\PrivacyDeID\deid.ps1" update
& "$HOME\PrivacyDeID\deid.ps1" stop
& "$HOME\PrivacyDeID\deid.ps1" status
```

The app runs at <http://localhost:8080>. See [Windows Local App](docs/windows-local-app.md) for
details.

## Branch workflow

Feature and documentation PRs target `dev`, the integration branch. `main` is the curated,
user-stable local-app branch and receives only intentional promotions from `dev` or explicit
hotfixes. Windows installation and update scripts always use `main`.

A Docker-first application foundation for privacy-focused document preparation and de-identification workflows.

Users can upload documents through a web interface. The backend validates each upload, stores
only the original bytes under `./volumes/uploads`, and keeps metadata and processing artifacts
separately under `./volumes/document-data`.

> **Step 5:** This version provides upload/document management, structural Audit v1, the
> synchronous OCR/Text and detection-only PII workstations, plus a manual document review UI.
> Anonymization and redaction remain separate later steps.

## Approach: tool-first / adapter-bound

Core OCR, NER, redaction, and pseudonymization intelligence comes from **proven open-source tools
behind adapters**. Extraction/OCR (for example OCRmyPDF, Tesseract, or MinerU), PII/PHI detection
(Presidio/noirdoc), and future redaction (PyMuPDF) remain replaceable behind ports. Narrow Presidio
recognizers, context rules, candidate validation, and deterministic domain heuristics are allowed
when documented, tested, benchmarkable, reviewable, and auditable. See [`AGENTS.md`](AGENTS.md).

## Engine capability model

The core of the project is the engine: local OCR/Text, local PII/sensitive-data, review/feedback,
and optional (later) local AI assist. [`docs/engine/`](docs/engine/README.md) defines what each
central engine should do on a **0–19 maturity scale**, the artifacts and metrics, the runtime
settings, the tool strategy, the target architecture (including the database and optional-local-AI
questions), and the roadmap. See [ADR-0011](docs/adr/0011-engine-capability-model.md) and
[ADR-0016](docs/adr/0016-engine-maturity-levels-0-19.md). Current standing (summary): OCR/Text
**L14**, PII **L11** (L10 partial), Review **L2 production / L6 done / L7-L9 partial**,
Benchmark **L8**, Redaction **L0**.

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
* **runtime data** — `/data/uploads` is bind-mounted from `./volumes/uploads` for originals only; `/data/document-data` is bind-mounted from `./volumes/document-data` for metadata, artifacts, review sidecars, and the default SQLite job DB (`jobs.sqlite3`). Neither host directory is committed (see `.gitignore`).

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
| `make up-ocr` | ✓ | – | in-process OCR; needs `make ocr-models` first |
| `make up-full` | ✓ | ✓ | in-process OCR; needs `make ocr-models` first |
| `make up-ocr-worker` | ✓ (worker) | – | isolated OCR worker; needs `make ocr-models` first |
| `make up-full-worker` | ✓ (worker) | ✓ | isolated OCR worker + PII; needs `make ocr-models` first |

`make build`, `build-pii`, `build-ocr`, `build-full` build the matching images without starting
them. Text PDFs and DOCX (including tables) are extracted **without** OCR; only image documents
and scanned PDF pages need the OCR runtime plus provisioned models.

**OCR worker mode (ADR-0023 Phase 3, opt-in).** By default OCR runs in-process
(`OCR_EXECUTION_MODE=sync`): `POST /api/documents/{id}/ocr` returns the text artifact with `201`. The
`make up-*-worker` targets set `OCR_EXECUTION_MODE=worker` and start an isolated `ocr-worker`
container (behind the `worker` Compose profile) that shares the job DB and document volumes with the
API. In worker mode the endpoint instead **enqueues** an OCR job and returns `202` with the job's
status; poll `GET /api/jobs/{job_id}` and read the result via `GET /api/documents/{id}/ocr` once it
succeeds. Because OCR then runs out-of-process with its own memory ceiling, an OCR OOM/crash can no
longer take the API down. PII stays synchronous. The frontend currently uses the default `sync` mode.

`INSTALL_OCR=true` pulls in PaddleOCR/PaddlePaddle/MKL and makes backend images significantly
larger on disk. For PDF-text-layer development (`layout_text_result`, `pii_input_text`), the slim
`make up`/`make up-pii` profiles are usually enough; real scanned-document OCR needs
`INSTALL_OCR=true` (`make up-ocr`/`make up-full`) plus provisioned models. See
[Docker disk cleanup](#docker-disk-cleanup) if repeated OCR/full builds accumulate old images.

## API

| Method | Path                   | Description                                                |
| ------ | ---------------------- | ---------------------------------------------------------- |
| GET    | `/api/health/live`     | Liveness check                                             |
| GET    | `/api/health/ready`    | Readiness check for both persistent storage directories    |
| GET    | `/api/config`          | Effective upload limits, safe PII defaults, and dev gate   |
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
| POST   | `/api/documents/{id}/pii/feedback` | Append gated dev-only entity feedback          |
| GET    | `/api/documents/{id}/pii/feedback`  | Restore gated dev-only feedback by artifact    |

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

New documents use three deliberately separate roots:

```text
volumes/
├── uploads/
│   └── <document_id>.<validated_extension>
├── document-data/
│   ├── jobs.sqlite3
│   └── <document_id>/
│       ├── document.json
│       ├── artifacts/
│       │   └── <artifact_id>.json
│       ├── feedback/
│       │   └── pii_feedback.jsonl
│       └── review/
│           └── pii_review_decisions.jsonl
└── pii-feedback-archive/
    └── pii_feedback.jsonl
```

`UPLOAD_STORAGE_DIR` contains byte-identical originals only. Storage filenames are generated
from a server-side UUID; the user-visible Unicode filename is retained only in `document.json`
and never used as a path. `DOCUMENT_DATA_DIR` contains one validated UUID-named directory per
document. Audit, OCR/Text, and PII results are all immutable JSON files in that document's
`artifacts/` directory. Deleting a document removes its UUID-named original and exactly its own
document-data directory — including `feedback/pii_feedback.jsonl`.

`PII_FEEDBACK_ARCHIVE_DIR` is a third, separate root: one shared, cross-document JSONL log that
every recorded feedback entry is *also* appended to, unchanged (`document_id` retained). Unlike
the per-document copy, it is never touched by document deletion — by design, so review feedback
can outlive its source document and later feed PII-quality improvement or the private benchmark
(see [review-feedback-levels.md, Level 14](docs/engine/review-feedback-levels.md#level-14--feedback-to-regression-workflow--open)).

Both feedback copies are a local, dev-gated analysis side-channel, not an immutable engine artifact
or a binding review result. Their structured fingerprint excludes raw document/entity text, but
optional comments can still contain sensitive input; treat both as protected data and never commit
them.

ADR-0023 also keeps durable job metadata in SQLite. By default `JOB_STORE_DB_PATH` is empty and the
backend resolves it to `${DOCUMENT_DATA_DIR}/jobs.sqlite3`; in Docker/Compose that is
`/data/document-data/jobs.sqlite3`, bind-mounted from `./volumes/document-data/jobs.sqlite3`. The API
and isolated `ocr-worker` use the same environment and volume mounts, so API-created pending jobs,
worker status updates, and worker-produced artifact references are visible through the same status
API. If `JOB_STORE_DB_PATH` is overridden, it must still point at a path mounted into both services.
For backup/restore, treat `./volumes/uploads` and `./volumes/document-data` as one unit and stop the
stack before copying SQLite files, including any `jobs.sqlite3-wal` and `jobs.sqlite3-shm` sidecars.

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
- **Memory (502 during OCR).** PaddleOCR runs in-process in the backend and needs headroom to load
  models and run inference. `make up-ocr`/`make up-full` set `BACKEND_MEMORY_LIMIT=2g` for this.
  Running the OCR-enabled image under the slim 512M default (e.g. plain `docker compose up` or
  `make bf` with `INSTALL_OCR=true` in `.env`) OOM-kills the backend mid-OCR, which the browser
  sees as an nginx **502 Bad Gateway**. Fix: use `make up-ocr`/`make up-full`, or set
  `BACKEND_MEMORY_LIMIT=2g`. The user-view analysis then shows an OCR-specific error instead of a
  generic one.
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

`structured-only` is the conservative **code fallback** if `PII_PROFILE` is left completely unset
(see `backend/app/config.py`, `docker-compose.yml`); it is intentionally narrow — high precision,
low coverage. [`.env.example`](.env.example) instead sets the **recommended local review default**,
`PII_PROFILE=review-heavy`, for broadest coverage when a human reviews the results. Use
`insurance-at-de` for fewer false positives. The spaCy NER types remain **opt-in** (via
`broad-review`/`review-heavy`) because the small German model over-tags them at a fixed score that
the score threshold cannot filter.
`PII_ENTITY_TYPES` remains a backwards-compatible explicit allowlist override — set, it replaces
`PII_PROFILE` entirely and is recorded as profile `custom`; unset **or empty**, it has no effect
and the selected profile applies. The score threshold stays `0.5`. The `presidio-analyzer` logger
is capped at WARNING so its initialization messages do not flood logs, while genuine warnings
still surface.

After detection, **candidate validation** (PII L6) inspects every already-detected candidate and
keeps, downgrades, or drops it — a subtractive post-processing filter, never a new recognizer. Full
lexical/context rules run on `PERSON`/`ORGANIZATION`/`LOCATION`/`DATE_TIME` (the dominant NER
false-positive source); a lighter context-presence check runs on `BIC` and a handful of domain
identifiers; every other type is an intentional pass-through. A dropped candidate never appears in
`pii_result.entities`; a downgraded candidate's score is capped at `0.3` (below the default `0.5`
threshold, so it is excluded from the final list unless the threshold is deliberately lowered).
`pii_result` additively records, per surviving entity, `original_score`/`validation_status`/
`validation_reasons`, plus a document-level `validation` summary (`kept`/`dropped`/`score_down` and
reason-code counts — never a candidate's text). Set `PII_CANDIDATE_VALIDATION_ENABLED=false` to
fall back to raw detection output. See
[ADR-0013](docs/adr/0013-pii-candidate-validation.md) for the full rule set and rationale.

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

The default User View shows **Kanonischer Lesetext** when a new OCR/Text artifact provides it.
Dev View keeps separate **Technischer Rohtext**, **Kanonischer Lesetext**, and **Layout-Text** modes.
Current PII detection and highlights still use the byte-stable technical raw text; reading text is a
future input candidate only after a tested lineage map exists.

With `ENABLE_DEV_ENGINE_SETTINGS=true`, the detail page also exposes one-run PII profile selection
and per-entity feedback. Feedback is restored from the local side-channel described above; it does
not alter `pii_result`, train a model, or create the future binding `review_result` artifact.

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
* named PII profile, candidate-validation toggle, and dev-only settings/feedback gate
* log level

### Environment profiles

For normal local testing, copy [`.env.example`](.env.example) to `.env` — it is heavily commented
and is the source of truth for every setting below.

**Recommended local mode:** `PII_PROFILE=review-heavy` with
`PII_CANDIDATE_VALIDATION_ENABLED=true`, run via `make up-full` (needs `make ocr-models` once).
This is what `.env.example` sets by default.

**PII profile quick guide:**

* `review-heavy` — default for local human review, broadest coverage
* `broad-review` — broad NER without DATE_TIME
* `insurance-at-de` — structured + AT/DE/domain IDs, fewer false positives
* `structured-only` — minimal smoke-test profile

If too little is detected, use `review-heavy` and rerun PII.
If too much is detected, use `insurance-at-de`.

Leave `PII_ENTITY_TYPES` commented out unless you intentionally want a custom allowlist instead of
a named profile — see `.env.example` section 7 for exactly how it interacts with `PII_PROFILE`.

**Common debugging steps:** after any `.env` change, recreate the containers (the relevant
`make up*` target again) and re-run the affected station for the document you're checking —
existing artifacts are immutable and never reflect a config change retroactively. If PII detection
looks empty, see the "If PII detects nothing" checklist in `.env.example` section 8 before
assuming something is broken.

## Development and quality

Common commands are available through the `Makefile`:

```bash
make lint        # Ruff and ESLint
make typecheck   # mypy and TypeScript
make test        # backend and frontend tests
make build       # build Docker images
make up          # start the stack
make down        # stop the stack
make benchmark-private   # private local OCR/PII benchmark report (see above)
make benchmark-test      # synthetic-data unit tests for the benchmark runner
```

### Docker disk cleanup

Repeated local `--build --force-recreate` cycles leave behind dangling (`<none>:<none>`) images
and build cache that can grow to tens of GB over time. Safe cleanup targets:

```bash
make docker-df              # show current Docker disk usage
make docker-prune           # remove dangling images/containers/networks + build cache
make docker-prune-project   # same, filtered to this project's labeled images (best-effort)
make dev-rebuild            # down + up --build --force-recreate + docker-prune (safe default)
```

These never delete volumes, uploads, or document data, and never stop running containers other
than during `dev-rebuild`'s `docker compose down`. `make docker-prune-project` is best-effort:
Docker's dangling-image filter does not reliably match unlabeled build-stage layers, so
`make docker-prune` remains the reliable default.

If you want to reclaim disk space more aggressively and are fine affecting *other* local Docker
projects too, you can manually run `docker image prune -af`. This is **not** wired into any make
target — run it explicitly, and never combine it with `--volumes` (that would delete Docker
volumes, which is unrelated to and unnecessary for cleaning up this project's `./volumes/`
bind-mounted directories, but destroys any named volumes from other projects on the machine).

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
