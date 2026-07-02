# Engine Roadmap

> **Level scale (0–19).** Per-engine capability levels now use the **0–19 maturity scale**
> ([engine README](README.md#maturity-scale)). The `Engine-N` PR ids below keep their numbers,
> but the `OCR Lx` / `PII Lx` / `Review Lx` level citations in their titles/scope still use the
> legacy **0–10** numbering — translate with the *Legacy scale mapping* table at the bottom of the
> relevant engine document. Full renumbering here is a tracked follow-up.

The order in which engine capability is built, reframed around the engine (not infrastructure). Each
item lists goal, scope, non-scope, affected files, whether it adds a dependency, tests, benchmark
verification, risk, and acceptance criteria.

Sequencing rationale: **measure first, then fix the biggest gaps the benchmark exposes** — structured
recall (AT/DE + domain), then NER precision (candidate validation), then human review, then the DB
and optional AI. Redaction is the final foundation, deliberately last.

## Status overview

| ID | Title | Status |
| --- | --- | --- |
| Engine-0 | Capability model / target architecture | ✅ **done** (PR #8) |
| Engine-1 | Benchmark runner / regression metrics | ✅ **done** (PR #7) |
| Engine-2 | OCR L4–L5 hardening (confidence + quality report + readable text) | planned |
| Engine-3 | OCR layout/table spike | planned (spike) |
| Engine-4 | PII L2–L3 `insurance-at-de` recognizer pack | ✅ **done** |
| Engine-5 | PII L5 candidate validation | ✅ **done** |
| Engine-6 | Review/feedback model (Review L2–L4) | planned (priority) |
| Engine-7 | DB architecture spike | planned (spike) |
| Engine-8 | Optional local AI / VLM spike | planned (spike) |
| Engine-9 | Redaction / de-identification foundation | planned (later) |

---

## Engine-0 — Capability model / target architecture  *(this PR)*

- **Goal:** define the engine target picture, levels, artifacts, metrics, tool strategy, and roadmap.
- **Scope:** `docs/engine/*`, ADR-0011, and pointer updates in `README.md`, `.ai/state.md`,
  `.ai/decisions.md`.
- **Non-scope:** any OCR/PII/review behaviour change; any dependency.
- **Affected files:** docs only.
- **New dependency:** no.
- **Tests:** `make lint` / `make typecheck` / `make test` unaffected (docs only).
- **Benchmark:** none (may run `make benchmark-private` to validate the snapshot; no report
  committed).
- **Risk:** low (documentation).
- **Acceptance:** the eight engine documents + ADR exist, cross-link, and the current-level snapshot
  matches the repo and the benchmark.

## Engine-1 — Benchmark runner / regression metrics  ✅ *done (PR #7)*

- **Delivered:** `scripts/benchmark/` (stdlib-only), `make benchmark-private[-json]`,
  `make benchmark-test`, `privacy_guard.py`, [ADR-0010](../adr/0010-private-benchmark-runner.md).
- **Covers:** corpus coverage/matching, OCR/text routing correctness + page-status distribution,
  PII P/R/F1 per doc/type/group/global, privacy-guarded reports.
- **Remaining for a later benchmark-maturity bump (L3):** OCR confidence/runtime/memory columns,
  per-profile PII metrics, run history/trend, and a CI regression gate — folded into Engine-2 (OCR
  metrics) and a later CI task.

## Engine-2 — OCR L4–L5 hardening

- **Goal:** make OCR quality *measurable* (confidence, `quality_report`) and produce a
  human-readable text rendering distinct from the canonical text.
- **Scope:** capture per-page PaddleOCR confidence; add a `quality_report` artifact (counts/coverage/
  confidence, no text); add a deterministic readable rendering seed (`layout_text_result`) that never
  mutates `best_text_result`; extend the benchmark with confidence/coverage columns.
- **Non-scope:** layout geometry/columns (Engine-3), tables (Engine-3), any AI.
- **Affected files:** `backend/app/services/ocr_adapters.py` (confidence), `ocr_service.py`,
  `audit_service.py`/`text_quality.py` (report), `schemas.py` (new artifact), `scripts/benchmark/*`,
  `docs/engine/*`.
- **New dependency:** no (confidence is already in the PaddleOCR payload).
- **Tests:** confidence extraction + `quality_report` unit tests; canonical-text-unchanged test.
- **Benchmark:** confidence/coverage appear in `make benchmark-private`; routing unchanged.
- **Risk:** medium (touches the OCR path; must not change routing behaviour).
- **Acceptance:** every OCR page carries confidence; a `quality_report` exists; a readable rendering
  exists alongside an unchanged canonical text.

## Engine-3 — OCR layout/table spike

- **Goal:** evaluate layout/table reconstruction (OCR L6–L7) before committing a tool.
- **Scope:** isolated spike comparing PyMuPDF (geometry) and Docling/PP-Structure (structure/tables)
  on representative pages; produce findings, not a pipeline change.
- **Non-scope:** wiring a new engine into the pipeline; changing canonical text.
- **Affected files:** a spike dir + `docs/engine/*` findings (adapter only if adopted).
- **New dependency:** spike-local only; a pipeline dependency needs its own follow-up PR.
- **Tests:** spike harness; no production tests until adoption.
- **Benchmark:** layout readability / table-quality metrics prototyped.
- **Risk:** low (isolated); medium if adopted (heavy deps).
- **Acceptance:** a written recommendation on layout/table tooling with measured evidence.

## Engine-4 — PII L2–L3 `insurance-at-de` recognizer pack  ✅ *done*

- **Goal:** close the biggest detection gaps the benchmark shows — AT/DE structured recall and the
  zero-coverage domain-sensitive group.
- **Delivered:** dependency-free Presidio pattern specifications materialized lazily by the adapter;
  AT/DE structured + insurance/legal/business identifiers; four named coverage profiles recorded in
  `pii_result`; benchmark canonical mappings for the new types.
- **Remaining:** address/contact-line recognizers and L4 per-profile benchmark reporting.
- **Non-scope:** candidate validation (Engine-5), NER retuning, any new heavy model.
- **Affected files:** `backend/app/services/pii_adapters.py` (custom recognizers), `config.py`
  (supported types/profiles), `schemas.py` (entity types), `scripts/benchmark/pii_matching.py`
  (canonical map already lists these), tests, `docs/engine/*`.
- **New dependency:** no (Presidio recognizers, deterministic patterns/context).
- **Tests:** recognizer unit tests with **synthetic** AT/DE + domain values only.
- **Benchmark:** `domain_sensitive_types` group moves off zero; `PHONE_NUMBER`/`IBAN_CODE` recall
  rises without collapsing precision.
- **Risk:** medium (precision/recall trade-offs on real formats).
- **Acceptance:** synthetic AT/DE + domain identifiers detected; measurable recall lift on the
  benchmark with acceptable precision.

## Engine-5 — PII L5 candidate validation  ✅ *done*

- **Goal:** raise NER precision by pruning/scoring-down obvious false positives — a subtractive,
  auditable post-processing step (see
  [PII engine: candidate validation](pii-engine-levels.md#candidate-validation-is-a-post-processing-exclusion-step)).
- **Delivered:** dependency-free lexical/shape validation rules (`pii_validation_rules.py`,
  `pii_candidate_validation.py`) producing KEEP/SCORE_DOWN/DROP with a fixed reason-code set;
  wired into `pii_service.py` before persistence. `pii_result` gains additive per-entity
  `original_score`/`validation_status`/`validation_reasons` and a content-level `validation`
  summary — no new artifact type. `PII_CANDIDATE_VALIDATION_ENABLED` (default on) is an escape
  hatch. Benchmark runner aggregates validation counts corpus-wide.
- **Non-scope:** new detection, AI plausibility (Engine-8), review actions (Engine-6).
- **Affected files:** `backend/app/services/pii_service.py`, `pii_candidate_validation.py`,
  `pii_validation_rules.py` (new), `config.py`, `schemas.py`, `scripts/benchmark/*`, tests,
  `docs/engine/*`, `docs/adr/0013-pii-candidate-validation.md`.
- **New dependency:** no (lexical/shape rules only; no spaCy POS/model dependency introduced).
- **Tests:** validation-rule unit tests, pii_service integration tests (drop excluded, summary
  counts, profile stability), privacy tests (no raw values in reasons/logs/summary), benchmark
  unit + end-to-end tests.
- **Benchmark:** see the before/after numbers in
  [`quality-metrics.md`](quality-metrics.md#benchmark-snapshot-aggregate-private-beforeafter-run).
- **Risk:** medium-high (must not suppress true positives) — mitigated by preferring SCORE_DOWN
  over DROP whenever a rule is ambiguous.
- **Acceptance:** NER precision materially improves on the benchmark, every suppression carries a
  reason, and true positives are preserved.

## Engine-6 — Review/feedback model (Review L2–L4)

- **Goal:** persist human confirm/reject/add/comment over immutable PII labels, lineage-safe.
- **Scope:** `review_result` artifact + API + UI actions bound to `pii_result`/`text_result`; stale
  handling on re-extraction; reasons/comments.
- **Non-scope:** rules engine (Review L5 / PII L8), DB (Engine-7), policy workflow.
- **Affected files:** `backend/app/schemas.py`, a `review_service.py`, `backend/app/api/*`,
  `frontend/src/components/pii/*` + detail page, tests, `docs/engine/*`.
- **New dependency:** no (file-based `review_result` first).
- **Tests:** decision persistence + lineage/stale tests (backend + frontend).
- **Benchmark:** review corrections become an available signal (Review L7 later feeds ground truth).
- **Risk:** medium (first mutable-ish state; keep `pii_result` immutable).
- **Acceptance:** confirm/reject/add/comment persist against exact lineage and re-render; re-runs mark
  decisions stale rather than reapplying them.

## Engine-7 — DB architecture spike

- **Goal:** decide the database approach when review/rules state makes files awkward (see
  [DB chapter](target-architecture.md#database-considerations)).
- **Scope:** design doc + spike: SQLite-first schema for index/state, run history, review decisions,
  rules; migration strategy from file artifacts. **No production migration in the spike.**
- **Non-scope:** moving raw text/PII into a DB; PostgreSQL; ORM rollout.
- **Affected files:** a design doc/ADR + spike; no production schema.
- **New dependency:** spike-local (e.g. stdlib `sqlite3`); production deps in a follow-up.
- **Tests:** spike only.
- **Benchmark:** could enable run-history/trend once adopted.
- **Risk:** low (spike).
- **Acceptance:** an ADR recommending SQLite-first scope (what moves to DB, what stays files) with a
  migration sketch.

## Engine-8 — Optional local AI / VLM spike

- **Goal:** evaluate a **local** model for hard-page OCR assist and/or PII plausibility, under the
  [hard AI rules](target-architecture.md#hard-rules-for-any-ai-at-every-level).
- **Scope:** isolated, local-only spike on a hard-page subset; assistive output only; measure assist
  acceptance vs baseline.
- **Non-scope:** pipeline integration; any external inference; auto-committing AI output as canonical.
- **Affected files:** a spike dir + findings; no production path.
- **New dependency:** spike-local only (large model), never in the default image.
- **Tests:** spike harness + human adjudication.
- **Benchmark:** assist-acceptance / false-improvement metrics prototyped.
- **Risk:** medium (weight/latency); low to the product (isolated).
- **Acceptance:** a written recommendation, with evidence, on whether/where local AI earns its place
  — respecting local-only, assistive, auditable constraints.

## Engine-9 — Redaction / de-identification foundation

- **Goal:** begin the actual de-identification — masking/redaction built on reviewed PII, as a
  separate station after review approval.
- **Scope:** redaction primitives behind an adapter (e.g. PyMuPDF), a redaction station design,
  export of a de-identified document; gated on approved `review_result`.
- **Non-scope:** everything before it must be solid first; this is the last roadmap item for a reason.
- **Affected files:** a `redaction_service.py` + adapter, export path, schemas, UI, tests, docs.
- **New dependency:** likely PyMuPDF (redaction) — reviewed for licensing.
- **Tests:** redaction correctness (masked spans truly removed), no-leak tests.
- **Benchmark:** redaction completeness vs reviewed spans.
- **Risk:** high (correctness is safety-critical — a missed span leaks PII).
- **Acceptance:** approved PII spans are verifiably removed from an exported document, driven by
  reviewed decisions, with an audit trail.

---

## Current level standing (project-wide)

| Area | Current level | Justification | Next level | Next PR |
| --- | --- | --- | --- | --- |
| OCR / Text engine | **L3 done, L4 partial** | per-page routing + quality verdicts shipped; no OCR confidence, no `quality_report`, no readable rendering | L4 → L5 | Engine-2 |
| PII engine | **L5 done** | AT/DE + domain pack, named coverage profiles, and candidate validation shipped; address/contact-line recognition and per-profile benchmark reporting remain open | L6 | Engine-6 (entity resolution overlaps into Review) |
| Review / feedback | **L1 done** | detail page lists candidates + lineage-safe highlights; no persisted decisions | L2 | Engine-6 |
| Benchmark / regression | **L2** | reproducible routing + PII P/R/F1 from existing artifacts; single snapshot, no trend/CI gate | L3 (trend + CI) | Engine-2 + later CI |
| Storage / core | **sufficient for MVP** | separated roots, immutable artifacts, validated deletes | — | — |
| Database | **not implemented; architecture open** | everything file-based | decide SQLite-first index/state | Engine-7 (spike) |
| Optional local AI/VLM | **not started** | deliberately deferred; guardrails defined | isolated spike | Engine-8 (spike) |
| Redaction / de-identification | **not started** | detection-only by design; needs review first | foundation | Engine-9 |
