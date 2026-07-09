# ADR-0023: Runtime worker architecture for heavy OCR/PII/AI jobs

## Status

Proposed — 2026-07-08. Planning-only for the overall worker architecture; **Phase 1 (the internal
job model abstraction), Phase 2 (SQLite-backed job state + status API), Phase 3 (isolated
`ocr-worker` container), and Phase 3.6 (default worker stack and runtime simplification) are
implemented** — see [Implementation status](#implementation-status) below. Synchronous in-process
OCR remains an explicit development/test fallback (`OCR_EXECUTION_MODE=sync`), while the normal
runtime defaults to worker isolation. Phases 4+ (PII worker, concurrency/timeout/retry controls,
optional Redis/RQ, quality/LLM workers) remain proposed and unimplemented. Builds on
[ADR-0001](0001-stack-and-architecture.md) (Docker-first FastAPI + React behind nginx),
[ADR-0003](0003-audit-station.md)/[ADR-0004](0004-ocr-workstation.md)/[ADR-0005](0005-pii-workstation.md)
(synchronous stations behind adapters), [ADR-0007](0007-ocr-runtime-and-model-provisioning.md)
(optional heavy OCR runtime), and [ADR-0008](0008-separate-upload-and-document-data-storage.md)
(storage separation). It complements [`docs/engine/target-architecture.md`](../engine/target-architecture.md)
and slots the runtime/worker split into the roadmap's DB spike (Engine-7) and AI spike (Engine-8),
**not ahead of them**.

## Context

Before this ADR's worker phases, heavy processing (OCR, PII, and future pseudonymization and local
AI) ran **synchronously inside the backend API process**. The OCR route called
`create_text_artifact(...)` directly in the request handler (`backend/app/api/ocr.py`); PII was the
same shape. These are `def` routes, so FastAPI runs them in the threadpool — the async event loop is
not blocked, but the work shared the backend container's process and memory.

That shared fate was the problem. It was previously managed with per-profile container memory
limits and a startup warning because PaddleOCR/PaddlePaddle under a small API memory limit could
OOM-kill the whole backend, which nginx surfaced as a 502. That mitigation treated a symptom: a
single OCR page could still take the entire API — health probes, in-flight PII requests, document
listing — down with it. Phase 3/3.6 moves OCR to the isolated worker by default.

The current runtime, precisely:

- **Containers:** `frontend` (nginx + React SPA, the only published port), `api` (private FastAPI),
  and `ocr-worker` (private polling worker). The API and worker deliberately share one backend image
  in Phase 3.6; that image includes the required OCR and PII dependencies.
- **Runtime profiles:** removed in Phase 3.6. `make up` and plain `docker compose up -d --build`
  start the default functional stack (`frontend`, `api`, `ocr-worker`). The old
  `slim`/`pii`/`ocr`/`full` variants and `INSTALL_OCR`/`INSTALL_PII` build toggles were retired.
- **Execution model:** OCR is queued by default: `POST …/ocr` returns `202` job status and the
  worker produces the immutable `text_result`; `OCR_EXECUTION_MODE=sync` remains an explicit
  fallback that returns `201` with the artifact body. PII remains synchronous in the API.
- **Artifact persistence:** immutable, append-only, lineage-linked JSON files under
  `volumes/document-store/<id>/artifacts/`, originals under `volumes/uploads/`, review-decision and
  feedback JSONL side-channels under the document root and a separate feedback-archive root. See
  [`engine-artifacts.md`](../engine/engine-artifacts.md).
- **Config/capability model:** 12-factor env via `Settings`; read-only capability probes
  (`runtime_capabilities.py`) tell `/api/config` whether the OCR/PII runtimes are installed, so a
  missing runtime is a clean `503` rather than a crash.
- **State:** immutable artifacts remain files; Phase 2 adds one SQLite DB for durable job metadata
  only (`jobs.sqlite3`, by default in its own `DATA_JOB_STATE_DIR` root, separate from per-document
  artifacts). It stores ids, status, timestamps,
  sanitized errors, and artifact references — never artifact payloads, raw OCR/reading text, or PII
  values.

### Risks in the current design

1. **API fate-shares with heavy jobs.** OCR OOM/crash/segfault takes down `uvicorn` and every
   concurrent request; `restart: unless-stopped` then bounces the container. This is the headline
   risk.
2. **No durable job state.** A long OCR/PII run has no id, no status, no cancellation, no retry. A
   client either holds a long HTTP request open or loses the result.
3. **Coarse rebuilds.** OCR system libraries and Python wheels live in the API image, so an
   OCR-runtime change rebuilds the layers the slim API also depends on. The API cannot stay slim and
   independently deployable from OCR.
4. **No worker isolation, no independent restart** of heavy work.
5. **Limited parallelism control.** Concurrency is whatever the threadpool allows; there is no
   explicit, memory-aware bound for a runtime this heavy.
6. **Limited observability of jobs.** There are good structured request logs, but no per-job
   lifecycle (queued/running/failed/retried/timed-out).
7. **Future multi-OCR/LLM would overload this shape.** Adding a second OCR engine, dictionaries,
   domain vocabularies, or a local VLM to the single API process multiplies both the memory blast
   radius and the rebuild surface.

The core engine invariants must survive any change: **canonical vs technical-raw text stay
separate; detection-only until redaction is designed; fail loud, never silently degrade; everything
auditable and lineage-linked; no bytes/text/PII leave the machine** (see
[`target-architecture.md`](../engine/target-architecture.md#design-invariants-the-engine-must-keep)).

## Decision

Adopt a **staged move to an isolated worker boundary**, smallest-stability-step first, without
jumping to microservices, a message broker, or Kubernetes. Concretely:

1. **Introduce an explicit internal job model** (id, type, status, input/output artifact ids,
   timestamps, attempt count, error class) as the seam between "schedule work" and "do work". This
   is a code refactor with **no new container and no DB** — existing synchronous calls become
   `run_job(...)` behind the abstraction and still run in-process at first.
2. **Split heavy processing into a separate worker container** so an OCR/PII OOM or crash cannot take
   the API down. The API becomes a thin scheduler/reader: it enqueues jobs and serves job status +
   immutable artifacts. This is the highest stability-per-effort move and the real point of the ADR.
3. **Track jobs durably in SQLite**, introduced before the worker split as the Phase 2
   scheduler/status foundation and reused by the later API↔worker boundary. **Artifacts stay on the
   filesystem**; the DB holds only job/index metadata and, later, review decisions and rules. This
   matches the existing SQLite-first stance in
   [`target-architecture.md`](../engine/target-architecture.md#sqlite-first-postgresql-later).
4. **Use a DB-backed job table with a polling worker** as the first queue — **not** Redis/Celery.
   Add Redis + a lightweight task runner only when real queue semantics (multiple workers, visibility
   timeouts, priorities) are demanded.
5. **Keep everything additive and reversible.** No artifact contract changes; jobs *reference*
   existing immutable artifacts. Every phase is independently shippable and rollback-able.

### Why these choices

- **Worker split before multi-engine/LLM.** Isolation is the prerequisite; adding evidence sources to
  the current in-process design multiplies the blast radius. Do isolation first.
- **SQLite, not Postgres, not file-only job state.** File-only job state is racy across the
  API↔worker boundary (two writers, no transactions). Postgres is a real ops dependency unneeded at
  single-user, ~1-concurrent-OCR-job scale. SQLite in WAL mode gives transactional job status with
  zero ops and fits the Docker-first local model; artifacts never enter it.
- **DB-backed polling queue, not Redis+Celery.** At "one OCR job at a time", a `jobs` table the
  worker polls (with a claimed/leased row) delivers durable status, retry, and isolation with no new
  broker. **Celery is too heavy** (broker + result backend + config surface) for a local-first
  single-user pilot. **Redis + RQ** (or Dramatiq) is the right *next* step when concurrency and retry
  semantics grow — RQ over Celery for weight, over Arq because the OCR/PII work is CPU-bound and
  synchronous. Adopt it in Phase 4+, not now.
- **Reject FastAPI `BackgroundTasks` for heavy work.** It runs in the API process, so it does **not**
  solve OOM fate-sharing — the exact problem this ADR exists to fix. It is fine only for trivial
  fire-and-forget side effects, not OCR/PII.

## Target architecture (staged, not big-bang)

```text
        ┌───────────┐        ┌──────────────────┐        ┌──────────────────────┐
        │ frontend  │        │       api        │        │  jobs (SQLite, WAL)  │
        │ nginx+SPA │──/api─▶ │ scheduler/reader│◀──────▶│  status/lineage only │
        └───────────┘        │  reads artifacts │        └──────────────────────┘
                             └──────┬───────────┘                    ▲
                                    │ enqueue / poll status          │ claim/lease, write status
                                    ▼                                │
                             ┌──────────────┐   ┌──────────────┐   ┌─┴────────────┐
                             │ ocr-worker   │   │ pii-worker   │   │ quality- /   │
                             │ heavy, bound │   │ medium       │   │ llm-worker   │  (later, optional)
                             │ concurrency 1│   │              │   │ strict limits│
                             └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
                                    │ read/write immutable artifacts (files)     │
                                    ▼                                            ▼
                             volumes/uploads, volumes/document-store/<id>/artifacts/… ; volumes/job-state/jobs.sqlite3
```

Components (each an independently rebuildable/restartable Compose service):

| Component | Role | Weight | When |
| --- | --- | --- | --- |
| `frontend` | nginx + SPA, only public port | light | today |
| `api` | scheduler + artifact/status reader; isolated from OCR execution | light/medium | today → slimmer image later |
| `jobs` DB (SQLite file) | durable job state + index; **no artifact bytes** | tiny | Phase 2/3 |
| `ocr-worker` | isolated OCR runtime, bounded concurrency, own memory limit | heavy | Phase 3 |
| `pii-worker` | PII runtime; may stay shared with API until it earns a split | medium | Phase 4 |
| `quality-worker` | optional evidence sources (dictionary/domain/2nd-OCR agreement) | medium | Phase 5 |
| `local-llm-worker` | optional local VLM/plausibility, strict resource profile | very heavy | Phase 6 |
| artifact storage | existing `volumes/` files (unchanged) | — | today |
| broker (Redis) | only if/when real queue semantics needed | small | Phase 4+ *if* justified |
| reverse proxy | already nginx; no new proxy needed near-term | — | — |

Phase 3 separates the **worker service/process boundary** first, while deliberately reusing the same
backend image for the API and worker. Phase 3.6 keeps that same-image choice and makes it the normal
runtime: one build path, one default Compose stack, and one `make up` path. A fully separate API
image or worker Dockerfile is only worth it once dependency trees actually diverge.

### Docker Compose default stack

Compose now starts the functional tool without profiles:

- `frontend` — nginx + SPA; the only published host port.
- `api` — FastAPI scheduler/status/artifact reader; private network only.
- `ocr-worker` — isolated OCR execution; private network only.

The service name is `api` rather than `backend` because its runtime responsibility is now narrower
than "the whole backend": it schedules OCR, serves status/artifacts, and still owns synchronous PII.
No `container_name` is set; Compose-native project scoping handles unique container names. The
default project name is `privacy-deidentification`, and the explicit network name derives from it.

The old slim/pii/ocr/full variants were removed because the product now requires the OCR/PII
runtime surface by default and the OCR worker boundary handles the main stability risk. The default
image includes OCR and PII dependencies; OCR model files remain separately provisioned and mounted
read-only. Sync OCR is retained only as `OCR_EXECUTION_MODE=sync`, not as a separate service/profile.

Each worker gets its own `deploy.resources.limits` and `restart: unless-stopped`, so it restarts
independently and its memory ceiling never touches the API's.

### Parallelism strategy

- **One OCR job at a time initially** (`ocr-worker` concurrency = 1), because OCR is memory-heavy.
- **Configurable concurrency** via env (e.g. `OCR_WORKER_CONCURRENCY`, `PII_WORKER_CONCURRENCY`) with
  conservative defaults; **never unbounded**.
- **PII in parallel** at a higher (still bounded) concurrency than OCR once split — it is lighter.
- **Multi-engine OCR** = additional bounded worker replicas / a second job type feeding a comparison
  step; still explicitly capped.
- **Per-job timeout, cancellation, and retry policy** live on the job record: a lease/heartbeat marks
  a job `running`; lease expiry (worker died) re-queues once (at-least-once) up to a small max; a
  timeout kills and marks `timed_out`; a cancel flag is honored at the next safe checkpoint.
- **Failure isolation + resource limits** are per worker container.

### Failure model

Phase 3 implements the isolation boundary and terminal status for normal station failures. Lease
expiry, heartbeat, retry, timeout, and cancellation remain target behavior for Phase 4+ and are
called out explicitly so the current worker does not overpromise recovery semantics it does not yet
have.

| Event | Product behavior |
| --- | --- |
| OCR worker crashes / OOMs | API stays up. Phase 3 station errors mark the job `failed`; a hard crash mid-job can leave it `running` until Phase 4 stale-lease reclaim. Compose restarts the worker independently. |
| PII worker crashes | Same, scoped to PII jobs; OCR and API unaffected. |
| Queue/DB unavailable | API returns `503` for *scheduling*; already-written immutable artifacts still read fine (they are files). Fail loud, never fake success. |
| Artifact file missing | Job that depends on it → `failed` with a clear error class; upstream artifacts are never regenerated silently. |
| Job times out | Target Phase 4+ behavior: killed, marked `timed_out`; no partial artifact is treated as final. |
| Worker restarts mid-job | Phase 3: job may remain `running` until manual intervention or a later reclaim feature. Target Phase 4+ behavior: lease expires → job re-queued once. **No partial-final risk:** artifacts are immutable and only committed at the *end* of a job, so a killed job leaves *no* artifact, never a half one. |

This preserves the existing invariants: fail loud, immutable/append-only artifacts, no silent
degrade, and **no sensitive text in logs** (job errors carry an error *class*, not document text).

### OCR/PII quality architecture fit

Future quality signals — PDF-text-layer vs OCR agreement, second OCR engine, OCR/layout confidence,
dictionary/lexicon, domain vocabulary, document-type detection, review feedback, benchmark gates, and
an optional local LLM/VLM — are **evidence sources, not hard truth** (already the position of
[ADR-0022](0022-ocr-l12-multi-column-layout-reconstruction.md) and the AI hard-rules in
[`target-architecture.md`](../engine/target-architecture.md#hard-rules-for-any-ai-at-every-level)).
The worker boundary supports each as a **new job type and/or worker container** emitting additive,
labelled `assistive` artifacts that feed confidence gates — no pipeline redesign, no change to
technical-raw/canonical text, no PII-input switch. The local-LLM worker in particular must stay
local, labelled low-confidence, auditable, additive, and behind a strict resource profile; its first
step remains an **isolated spike (Engine-8)**, not integration.

### Artifact & provenance strategy

Unchanged in substance — the current immutable, versioned, lineage-linked file artifacts already
model raw upload → technical raw text → canonical reading text → layout/structured content → PII
result → review-decision overlay, with future pseudonymized preview / reconstruction map / quality
reports as additive artifacts. The only addition is a **job record** that *references* the artifact
ids it consumed and produced (a lightweight `job_result`/lineage row in the DB). Deletion,
archival, versioning, and privacy boundaries follow the existing rules
([`engine-artifacts.md`](../engine/engine-artifacts.md)); job records are deleted with their document
(the feedback archive keeps its separate survival boundary). The DB **indexes** artifacts; it never
stores their raw text or PII.

## Staged migration plan

| Phase | Change | Benefit | Risk | Size | Migration complexity | Tests | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **0** | Document current architecture (this ADR). No runtime change. | Shared understanding; sequencing agreed. | None. | XS | None. | Doc/`git diff --check`. | Revert doc. |
| **1** | Internal **job model abstraction**; stations run *through* it, still synchronous, in-process. No DB, no container. | Establishes the schedule/execute seam with zero infra risk. | Low — pure refactor behind existing endpoints. | S | None (no data/schema). | Unit tests for job lifecycle; existing station tests unchanged. | Revert; endpoints still call stations directly. |
| **2** | Add **SQLite** for job/index metadata + a **job-status API**; artifacts stay files; work still in-process. | Durable job state, status/history, cancellable in principle. | Low–med — first stateful component; needs WAL + migration discipline. | M | Low (additive DB; files untouched). | DB job CRUD, status API, concurrent-write (WAL) tests. | Feature-flag reads; drop DB file, keep files. |
| **3** | Split **`ocr-worker`** into its own container; API enqueues + reads status; DB-backed polling queue. | **The stability win:** OCR OOM/crash can no longer take the API down. | Med — process boundary, lease/heartbeat, at-least-once semantics. | M–L | Med (compose + entrypoint; no artifact change). | Worker claim/lease/retry, OOM-kill simulation, API-stays-up integration test. | Env switch back to in-process execution; keep DB. |
| **4** | Split **`pii-worker`** if useful; add explicit concurrency, retry, timeout, cancellation controls. Consider Redis + RQ **only if** queue semantics demand it. | Parallel PII; bounded, tunable throughput. | Med — more moving parts; broker iff added. | M | Med. | Concurrency-limit, timeout, cancel, retry-policy tests. | Fold PII back into API/worker; drop broker if added. |
| **5** | Add **quality evidence layer** (optional 2nd-OCR / dictionary / domain vocabulary) as new job types/workers emitting additive `assistive` artifacts. | Multi-signal OCR/PII quality without redesign. | Med — evidence must stay additive, never authoritative. | M–L | Med (additive artifacts only). | Additive-artifact + benchmark-gate tests; must-not-regress canonical text. | Disable the evidence job type. |
| **6** | Optional **local LLM/VLM worker** under a strict resource profile; isolated spike first. | Assistive plausibility for hard scans/candidates. | High — resource + auditability + privacy. | L | Med–High. | Labelling/auditability, resource-limit, local-only egress tests. | Remove the worker/profile; nothing else depends on it. |

## Recommendation

- **Do next:** Phase 3 (isolate the OCR worker), which is the **smallest remaining change that yields
  the most stability**: it removes the API's fate-sharing with OCR. Phase 1 established the internal
  job seam and Phase 2 added durable SQLite status metadata without changing synchronous execution.
- **Do not do yet:** Redis, Celery/Dramatiq/Arq, PostgreSQL, a message broker, multi-engine OCR,
  dictionaries/domain vocabularies as workers, or the local LLM worker. Each waits for its phase and
  a concrete need.
- **Too much for now:** Kubernetes, microservices, an external broker/result backend, and any
  multi-node orchestration. This is a local-first, single-user pilot; that infrastructure is
  unjustified and would slow the engine work that is the actual product.
- **Sequencing guard:** keep this infra roughly aligned with the roadmap's DB spike (Engine-7) and AI
  spike (Engine-8). Do not let runtime plumbing outrun OCR/Text and PII engine prerequisites; run the
  checkpoint loop after each phase.

## Consequences

- The API becomes an always-responsive scheduler/reader at the process boundary; heavy OCR work
  cannot crash it. Image slimming is a later optimization.
- One new stateful component (SQLite) and one new long-running service class (workers) enter the
  system — accepted deliberately, and only from Phase 2/3 onward.
- Build/deploy granularity improves: the API image stops rebuilding OCR/PII layers.
- No artifact contract, PII-input, canonical/technical-raw text, review-decision, benchmark-payload,
  pseudonymization, redaction, or export behavior changes as a result of this ADR.
- Future OCR/AI quality signals are added as bounded, additive, labelled workers/steps behind
  confidence gates, consistent with ADR-0022 and the AI hard-rules.

## Implementation status

| Phase | State |
| --- | --- |
| 0 — document current architecture (this ADR) | Done. |
| **1 — internal job model abstraction** | **Done.** In-process only; no runtime behavior change. |
| **2 — SQLite job store + status API** | **Done.** Durable metadata/status only; OCR/PII still execute synchronously in-process. |
| **3 — isolate `ocr-worker`** | **Done.** `OCR_EXECUTION_MODE=worker` moves OCR into an isolated polling worker container; `sync` keeps in-process execution as fallback. PII stays synchronous. |
| **3.6 — simplify default runtime** | **Done.** Default Compose stack is `frontend` + `api` + `ocr-worker`, OCR worker mode is the default, the frontend polls `202` jobs, and slim/pii/ocr/full build/runtime variants are removed. |
| 4+ — PII worker, concurrency controls, optional Redis/RQ, quality/LLM workers | Not started (proposed). |

### Phase 1 — internal job model abstraction (implemented)

Phase 1 introduces the "schedule work" ↔ "do work" seam and nothing else. It is a pure refactor
behind the existing endpoints:

- `backend/app/services/job_models.py` — `JobKind` (`ocr_text`, `pii_detection`), `JobStatus`
  (`pending`/`running`/`succeeded`/`failed`/`canceled`), `JobExecutionMode`
  (`synchronous_inline`/`future_worker`), an immutable `JobContext`, a mutable `JobRecord` with
  lifecycle transitions, and a generic `JobResult`. `sanitize_job_error` reduces any exception to a
  safe `(error_code, error_message)` pair.
- `backend/app/services/job_runner.py` — `SyncJobRunner.run(context, operation)` executes the
  station call inline, records lifecycle, and returns a `JobResult`. `provide_job_runner` is the
  FastAPI dependency a future worker-backed runner can replace.
- `backend/app/api/ocr.py` / `pii.py` — the `POST …/ocr` and `POST …/pii` handlers build a
  `JobContext` and call `runner.run(...)`, then `result.unwrap()`.

**Intentionally unchanged in Phase 1**: OCR and PII still run **synchronously in-process**; there is
no queue, no worker container, and no background task. At the time of Phase 1, `JobRecord`s were
per-request and in-memory — never persisted. The API request/response shapes, artifact creation,
error status codes/details, canonical-vs-technical-raw text separation, PII input (technical raw
text), review decisions, and benchmark payloads all stayed unchanged. Heavy OCR still fate-shares
with the backend process until Phase 3 isolates the worker.

**Privacy:** a `JobRecord` (the loggable/serializable half) carries only ids, timestamps, status, a
coarse `error_code`, and a sanitized `error_message`; raw document text, OCR text, and PII never
enter it. The original exception (which may hold sensitive detail) travels only in the transient,
in-process `JobResult.error` and is re-raised unchanged so API behavior is preserved — it is never
logged or copied into the record. A failed job never yields a `succeeded` status, preserving the
no-partial-result-as-final invariant.

### Phase 2 — SQLite job store + status API (implemented)

Phase 2 persists the same safe job lifecycle metadata in SQLite while preserving the existing
synchronous station behavior:

- `backend/app/services/job_store.py` — a stdlib `sqlite3` repository with idempotent schema
  creation, WAL mode, short transactions, one connection per operation, and methods for
  create/running/succeeded/failed/get/list/delete. The DB path is configurable with
  `JOB_STORE_DB_PATH`; the default is `DATA_JOB_STATE_DIR/jobs.sqlite3` (a dedicated persistent
  job-state volume, kept separate from per-document artifact folders). Phase 3.6 moved the default
  out of `DOCUMENT_DATA_DIR` into this dedicated root.
- `backend/app/services/job_runner.py` — the FastAPI runner provider now attaches the configured
  store, so OCR/PII job rows are created before inline execution and updated on success/failure.
  Direct unit-test runners can still be created without persistence.
- `backend/app/api/jobs.py` — additive safe status endpoints:
  `GET /api/jobs/{job_id}` and `GET /api/documents/{document_id}/jobs`.
- `POST /api/documents/{document_id}/ocr` and `POST /api/documents/{document_id}/pii` keep their
  existing response bodies and add an `X-Job-Id` header on successful synchronous runs. Document job
  listing is the fallback lookup path by document id.

**Intentionally unchanged** (Phase 2 is not the worker split): OCR and PII still run synchronously in
the backend request thread; there is no worker container, queue, Redis, Celery/RQ, background task,
new Docker profile, OCR algorithm change, PII model change, pseudonymization, redaction, export, or
frontend workflow change. Heavy OCR still fate-shares with the backend until Phase 3.

**Privacy:** the SQLite DB stores metadata only: job/document ids, kind, status, execution mode,
created/started/finished/updated timestamps, attempt count, sanitized `error_code`/`error_message`,
optional produced artifact id/type, and a small string metadata map. It never stores uploaded bytes,
raw OCR text, canonical reading text, layout text, structured content payloads, PII values, artifact
JSON payloads, stack traces, or raw exception messages. Job rows are deleted with their document's
document-store boundary; artifacts remain file-based and immutable.

### Phase 3 — isolate the OCR worker (implemented)

Phase 3 moves OCR execution out of the FastAPI process into an isolated `ocr-worker` container that
claims jobs from the Phase 2 SQLite store. It is **the stability win**: an OCR OOM/crash can no
longer take the API down. It is a DB-backed polling worker — **not** Redis/Celery/RQ — and PII stays
synchronous in the API.

- **Execution mode (`OCR_EXECUTION_MODE`, default `worker` as of Phase 3.6).** `worker` makes
  `POST /api/documents/{id}/ocr` enqueue a `pending` OCR job and return `202` with the job's safe
  status; the endpoint touches no OCR runtime. `sync` preserves Phase 2 exactly as an explicit
  fallback: the OCR endpoint runs `create_text_artifact` inline through the `SyncJobRunner` and
  returns the `text_result` artifact with `201`. Both modes set `X-Job-Id`.
- **The worker** (`backend/app/services/ocr_worker.py` + entrypoint `backend/app/ocr_worker.py`,
  run as `python -m app.ocr_worker`): initializes the shared store, then polls. Each cycle it
  atomically claims the oldest pending `ocr_text` job, runs the unchanged `create_text_artifact`
  station in its own process, and records a terminal `succeeded` (with produced artifact id/type)
  or sanitized `failed`. It drains back-to-back jobs and sleeps `OCR_WORKER_POLL_INTERVAL_SECONDS`
  when idle. `SIGTERM`/`SIGINT` requests a graceful stop after the in-flight job.
- **Safe claiming.** `JobStore.claim_next_pending_job` is one `UPDATE … RETURNING` statement whose
  `WHERE` re-selects the target row. Under SQLite's single-writer WAL lock (with `busy_timeout`),
  two workers can never claim the same job: the second runs after the first commits and no longer
  sees the row as `pending`. OCR runs **outside** that short transaction, so there is no long DB
  transaction during extraction. `OCR_WORKER_MAX_ATTEMPTS` bounds re-claims (default 1; Phase 3 does
  not auto-retry — a failed job is terminal).
- **Concurrency.** `OCR_WORKER_CONCURRENCY` is validated to be exactly `1` (one memory-heavy OCR job
  at a time); higher concurrency is deferred to Phase 4 and rejected loudly rather than ignored.
- **Docker/Compose.** The default Compose stack includes `ocr-worker` with command override
  `python -m app.ocr_worker`. It shares the same backend image and the document-store / uploads /
  ocr-models / job-state volumes with the API (all mapped from a single host `DATA_ROOT`). It has its own memory ceiling
  (`OCR_WORKER_MEMORY_LIMIT`, default `2g`) and `restart: unless-stopped`, so it restarts
  independently and its ceiling never touches the API's. Splitting a slimmer API image from the
  worker image is a deliberate future optimization — Phase 3.6 uses one image for
  correctness/stability first.
- **Failure model (as tested):** an OCR error marks the job `failed` with a sanitized code/message
  and writes no artifact (never a partial `succeeded`); the API keeps listing documents/jobs while
  the worker is down; with no worker running, jobs simply stay `pending`; a worker crash mid-job
  leaves the row `running` (stale-lease reclaim/heartbeat is **deferred to Phase 4** and documented
  as a known limitation); job metadata and logs never carry raw text or stack traces.

**Intentionally unchanged in Phase 3:** the OCR algorithm, technical raw/canonical text,
`quality_evidence`, PII model and its technical-raw-text input, PII projection, review decisions,
benchmark payloads, and artifact contracts. There is still no Redis/Celery/RQ, no PII worker split,
no pseudonymization/redaction/export, and no local LLM. The synchronous runner remains available as
the fallback for tests/dev.

### Phase 3.6 — default worker stack and runtime simplification (implemented)

Phase 3.6 turns the Phase 3 opt-in worker shape into the normal runtime:

- `make up` / `docker compose up -d --build` starts `frontend`, `api`, and `ocr-worker`; no Compose
  profile is required for core behavior.
- `OCR_EXECUTION_MODE` defaults to `worker`; `sync` remains available for development and targeted
  tests.
- The frontend handles the worker response contract: `runOcr()` accepts `202` job metadata, polls
  `GET /api/jobs/{job_id}`, and fetches `GET /api/documents/{id}/ocr` after success. Existing page
  code still receives a `TextArtifact`.
- The old slim/pii/ocr/full Make targets and `INSTALL_OCR`/`INSTALL_PII` build args are removed.
  The shared API/worker image includes OCR and PII dependencies by default. OCR model files remain
  separate local data under `./volumes/ocr-models` and are still never downloaded during a request.
- `.env.example` now lists only meaningful deployment knobs: project name, port, a single
  `DATA_ROOT`, worker mode/resources, OCR model names, PII profile/settings, dev gate, and advanced
  overrides. Container-internal storage paths (`UPLOAD_STORAGE_DIR`, `DOCUMENT_DATA_DIR`,
  `DATA_JOB_STATE_DIR`, `PII_FEEDBACK_ARCHIVE_DIR`, `OCR_MODEL_DIR`, `JOB_STORE_DB_PATH`) are no
  longer presented as normal deployment settings — they have stable internal defaults and remain
  advanced overrides only, so a deployment cannot silently split API/worker storage by editing one.
- Storage consolidates under a single host `DATA_ROOT` (default `./volumes`). Compose maps
  `${DATA_ROOT}/{uploads,document-store,job-state,pii-feedback-archive,ocr-models}` onto the stable
  internal paths. The former `document-data` root was renamed to `document-store`, and `jobs.sqlite3`
  moved out of it into a dedicated `job-state` root so durable job state never sits beside
  per-document artifact folders. There is no automatic migration (see the README migration note).
- Service naming is `frontend`, `api`, `ocr-worker`. No `container_name` is set; Compose project
  scoping provides unique names, with default `COMPOSE_PROJECT_NAME=privacy-deidentification`.

**Intentionally unchanged in Phase 3.6:** OCR algorithms, PII algorithms, `reading_text`,
`quality_evidence`, artifact contracts, SQLite-as-file job state, PII synchronous execution, and
the no-Redis/Celery/RQ/no-Kubernetes boundary.
