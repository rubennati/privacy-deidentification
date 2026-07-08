# ADR-0023: Runtime worker architecture for heavy OCR/PII/AI jobs

## Status

Proposed — 2026-07-08. Planning-only for the overall architecture; **Phase 1 (the internal job
model abstraction) is implemented** as a pure in-process refactor with no runtime-behavior change —
see [Implementation status](#implementation-status) below. Phases 2+ (SQLite, workers, queue) remain
proposed and unimplemented. Builds on
[ADR-0001](0001-stack-and-architecture.md) (Docker-first FastAPI + React behind nginx),
[ADR-0003](0003-audit-station.md)/[ADR-0004](0004-ocr-workstation.md)/[ADR-0005](0005-pii-workstation.md)
(synchronous stations behind adapters), [ADR-0007](0007-ocr-runtime-and-model-provisioning.md)
(optional heavy OCR runtime), and [ADR-0008](0008-separate-upload-and-document-data-storage.md)
(storage separation). It complements [`docs/engine/target-architecture.md`](../engine/target-architecture.md)
and slots the runtime/worker split into the roadmap's DB spike (Engine-7) and AI spike (Engine-8),
**not ahead of them**.

## Context

Heavy processing (OCR, PII, and future pseudonymization and local AI) runs **synchronously inside the
backend API process**. The OCR route calls `create_text_artifact(...)` directly in the request
handler (`backend/app/api/ocr.py`); PII is the same shape. These are `def` routes, so FastAPI runs
them in the threadpool — the async event loop is not blocked, but the work **shares the backend
container's process and memory**.

That shared fate is the problem. Today it is managed with per-profile container memory limits
(`make up-ocr`/`up-full` raise `BACKEND_MEMORY_LIMIT` to 2g) and a startup warning
(`runtime_capabilities.warn_if_ocr_memory_limit_is_low`) because PaddleOCR/PaddlePaddle under the
slim 512M default **OOM-kills the whole backend**, which nginx surfaces as a 502. The mitigation is
real but it treats a symptom: a single OCR page can still take the entire API — health probes,
in-flight PII requests, document listing — down with it.

The current runtime, precisely:

- **Containers:** `frontend` (nginx + React SPA, the only published port) and `backend` (private
  FastAPI). One image each. The heavy OCR/PII Python extras are baked into the *same* backend image
  via build args `INSTALL_OCR`/`INSTALL_PII`.
- **Runtime profiles:** `slim` / `pii` / `ocr` / `full`, selected by Make target (not `.env`), which
  toggle the build args and the backend memory limit.
- **Execution model:** fully synchronous, in-process, one request → one artifact, behind replaceable
  adapters. No queue, no worker, no background job.
- **Artifact persistence:** immutable, append-only, lineage-linked JSON files under
  `volumes/document-data/<id>/artifacts/`, originals under `volumes/uploads/`, review-decision and
  feedback JSONL side-channels under the document root and a separate feedback-archive root. See
  [`engine-artifacts.md`](../engine/engine-artifacts.md).
- **Config/capability model:** 12-factor env via `Settings`; read-only capability probes
  (`runtime_capabilities.py`) tell `/api/config` whether the OCR/PII runtimes are installed, so a
  missing runtime is a clean `503` rather than a crash.
- **State:** no database. All state is files.

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
3. **Track jobs durably in SQLite**, introduced *at the worker split* (not before), because a job
   store shared by two processes is exactly the mutable cross-process state that flat files handle
   poorly. **Artifacts stay on the filesystem**; the DB holds only job/index metadata and, later,
   review decisions and rules. This matches the existing SQLite-first stance in
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
        │ frontend  │        │  api / backend   │        │  jobs (SQLite, WAL)  │
        │ nginx+SPA │──/api─▶ │  slim, scheduler │◀──────▶│  status/lineage only │
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
                             volumes/uploads, volumes/document-data/<id>/artifacts/…
```

Components (each an independently rebuildable/restartable Compose service):

| Component | Role | Weight | When |
| --- | --- | --- | --- |
| `frontend` | nginx + SPA, only public port | light | today |
| `api` (backend) | thin scheduler + artifact/status reader; stays slim | light | today → slimmed |
| `jobs` DB (SQLite file) | durable job state + index; **no artifact bytes** | tiny | Phase 2/3 |
| `ocr-worker` | isolated OCR runtime, bounded concurrency, own memory limit | heavy | Phase 3 |
| `pii-worker` | PII runtime; may stay shared with API until it earns a split | medium | Phase 4 |
| `quality-worker` | optional evidence sources (dictionary/domain/2nd-OCR agreement) | medium | Phase 5 |
| `local-llm-worker` | optional local VLM/plausibility, strict resource profile | very heavy | Phase 6 |
| artifact storage | existing `volumes/` files (unchanged) | — | today |
| broker (Redis) | only if/when real queue semantics needed | small | Phase 4+ *if* justified |
| reverse proxy | already nginx; no new proxy needed near-term | — | — |

The **worker image is separated from the API image** so the API never rebuilds OCR/PII layers.
Simplest first cut: the same `backend/Dockerfile` built with `INSTALL_OCR`/`INSTALL_PII` args but run
as a *distinct service* with a different entrypoint (`worker` loop vs `uvicorn`). This buys process
isolation immediately with almost no new build machinery; a fully separate `worker/Dockerfile` is
only worth it once dependency trees actually diverge.

### Docker Compose profiles

Use Compose `profiles:` so the same file expresses every runtime shape and heavy layers are opt-in:

- `slim` — `frontend` + `api` only (no OCR/PII). Default `make up`.
- `pii` — adds PII (worker or in-API, per phase).
- `ocr` — adds `ocr-worker` + models mount + 2g limit on the worker (not the API).
- `full` — OCR + PII workers.
- `worker` — worker services without rebuilding the API.
- `dev` — developer conveniences.
- `benchmark` — the existing read-only private benchmark runner (already isolated in the Makefile).

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

| Event | Product behavior |
| --- | --- |
| OCR worker crashes / OOMs | API stays up. Job → `failed` (retryable). Frontend shows failed + retry. Compose restarts the worker independently. |
| PII worker crashes | Same, scoped to PII jobs; OCR and API unaffected. |
| Queue/DB unavailable | API returns `503` for *scheduling*; already-written immutable artifacts still read fine (they are files). Fail loud, never fake success. |
| Artifact file missing | Job that depends on it → `failed` with a clear error class; upstream artifacts are never regenerated silently. |
| Job times out | Killed, marked `timed_out`; no partial artifact is treated as final. |
| Worker restarts mid-job | Lease expires → job re-queued once. **No partial-final risk:** artifacts are immutable and only committed at the *end* of a job, so a killed job leaves *no* artifact, never a half one. |

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

- **Do next:** Phase 1 (job model abstraction) — smallest, zero-infra step that unlocks everything
  else — then Phase 3 (isolate the OCR worker), which is the **smallest change that yields the most
  stability**: it removes the API's fate-sharing with OCR. Phase 2 (SQLite job store) is the natural
  bridge and should land with, or immediately before, Phase 3.
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

- The API becomes a slim, always-responsive scheduler/reader; heavy work cannot crash it.
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
| 2 — SQLite job store + status API | Not started (proposed). |
| 3 — isolate `ocr-worker` | Not started (proposed). |
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
  station call inline, records lifecycle, and returns a `JobResult`. `get_job_runner` is the single
  FastAPI dependency a future worker-backed runner can replace.
- `backend/app/api/ocr.py` / `pii.py` — the `POST …/ocr` and `POST …/pii` handlers build a
  `JobContext` and call `runner.run(...)`, then `result.unwrap()`.

**Intentionally unchanged** (Phase 1 is not the worker split): OCR and PII still run **synchronously
in-process**; there is **no database, no queue, no worker container, no background task, and no new
API surface**. `JobRecord`s are per-request and in-memory — never persisted. The API request/response
shapes, artifact creation, error status codes/details, canonical-vs-technical-raw text separation,
PII input (technical raw text), review decisions, and benchmark payloads are all unchanged. Heavy OCR
still fate-shares with the backend process until Phase 3 isolates the worker.

**Privacy:** a `JobRecord` (the loggable/serializable half) carries only ids, timestamps, status, a
coarse `error_code`, and a sanitized `error_message`; raw document text, OCR text, and PII never
enter it. The original exception (which may hold sensitive detail) travels only in the transient,
in-process `JobResult.error` and is re-raised unchanged so API behavior is preserved — it is never
logged or copied into the record. A failed job never yields a `succeeded` status, preserving the
no-partial-result-as-final invariant.
