# Quality Gates

A change is ready when:

- Scope is clear and limited; change is reviewable and documented.
- `make lint`, `make typecheck`, `make test` pass.
- Input validation and security-relevant logic are covered by tests.
- No secrets in the repo; config via environment variables.
- Routing/state files updated when needed.
- No direct commits to `main`.

## Runtime / API / worker changes

Additional gates when a change touches the API contract, the frontend↔API boundary, the OCR/PII
worker execution model, `docker-compose.yml`, the `Makefile`, or `.env.example`:

- **Contract tests for every new response shape.** Any new or changed API response (e.g. a new
  status code, a `202` job envelope, a new field) needs an API-level test and, where a client
  consumes it, a matching frontend contract test.
- **Job-flow coverage.** Changes to async job handling must keep frontend tests for the
  pending, running, succeeded, and failed job flows (plus the synchronous fallback and
  missing/legacy-field guards) green.
- **Compose build/start smoke.** When `docker-compose.yml` or the `Makefile` changes, run
  `python scripts/check-runtime-surface.py` (via `make test`), `docker compose config`, and
  `docker compose config --services`; do a `make build` / `make up` smoke when feasible.
- **No duplicate build definitions for a shared image.** Services that share one image (api and
  ocr-worker) must have exactly one `build:` block; the reuser references the built image by tag.
- **Explicit acceptance gate before changing a runtime default.** Do not flip a default such as
  `OCR_EXECUTION_MODE` to a new mode until the frontend and tests fully support that mode.
- **No new user-facing container-internal path knobs.** Deployments configure a single `DATA_ROOT`;
  container-internal storage paths (`UPLOAD_STORAGE_DIR`, `DOCUMENT_DATA_DIR`, `DATA_JOB_STATE_DIR`,
  `PII_FEEDBACK_ARCHIVE_DIR`, `OCR_MODEL_DIR`, `JOB_STORE_DB_PATH`) stay as advanced overrides with
  stable defaults and must not appear as active settings in `.env.example` — changing them
  independently can split API/worker storage. `jobs.sqlite3` stays in its own `job-state` root.
- **Never commit runtime data.** No `*.sqlite3`/`-wal`/`-shm`, `.env`, `volumes/`, `.local/`, or
  private document text; only synthetic fixtures in tests.

## OCR/Text quality-evidence changes

Additional gates when a change touches `quality_evidence` (`ocr_quality.py`, `ocr_noise.py`, or any
future evidence source plugged into that list — dictionary/lexicon, multi-OCR, local-LLM hints):

- **False-positive guard tests.** Cover normal prose, structured identifiers (invoice/policy
  numbers, IBAN-like/phone-like strings), legal references, dates, prices, percentages, acronyms,
  filenames, bullet lists, and table rows/separators — a change that adds or tunes a suspicion
  signal must show it does not over-flag these categories.
- **No raw token text in evidence.** Every evidence item stays offset/count/flag/reason-code-only
  (`details: dict[str, int]`); a test must assert no synthetic sensitive sample text appears in the
  evidence JSON.
- **Private-corpus validation summary.** Run the change against the local private corpus
  (`test-corpus/`, never committed; local script and output under `.local/`, never committed) and
  report, per document, whether the new/changed evidence is useful, too noisy, missing a signal, or
  a false-positive risk — plus an explicit stable-document regression statement (existing
  `reading_text`/`structured_content`/lineage output compared against the prior baseline).
- **Evidence vs. correction, explicitly.** State in the PR/ADR that the change adds *evidence*
  (suspicion, explainable, reviewable) and does not automatically correct, remove, or rewrite OCR
  text, `reading_text`, or `structured_content` — any future correction/suggestion capability is a
  separate, explicitly re-scoped level.

The same discipline applies to any OCR/Text **output** change (`reading_text`,
`structured_content`, reconstruction heuristics): synthetic tests are required; a private-corpus
validation pass is required for behavior changes with an explicit stable-document no-regression
statement; no private-corpus files are ever committed; and no raw document/token text enters
metrics or evidence metadata.

## Contract changes

Additional gates when a change touches a versioned output/artifact contract — most notably the
proposed **OCR Output Contract v1 / Document Text Package**
([ADR-0027](../docs/adr/0027-ocr-output-contract-v1-strategy.md)), and equally any change to an
existing artifact schema (`text_result` fields, `quality_evidence`, `pii_result`) or the runtime
job contract:

- **Versioned schema + contract status.** A contract change bumps or introduces an explicit version
  (`contract_version` / per-field `*_version`) and, where the contract has one, keeps a meaningful
  `contract_status` (`valid`/`degraded`/`invalid`) with warnings/blockers rather than silently
  emitting partial output.
- **Legacy artifact compatibility considered.** Legacy artifacts written before the change must
  still validate/read (additive optional fields), or the migration is explicit and documented.
- **Consumer impact documented.** The PR/ADR states which consumers (PII, Review, benchmark,
  frontend) are affected and how; a consumer must not silently break when an optional layer is
  absent.
- **Breaking changes are explicit and tested.** A breaking contract change is called out as such,
  gated behind a version bump, and covered by tests for both the old and new shape where both are
  supported. Additive, backward-compatible changes are strongly preferred.
- **No raw text across the boundary beyond existing text layers.** A packaging/contract change adds
  no new raw document or entity text to metrics-only layers; the existing text-artifact privacy
  rules still apply.
