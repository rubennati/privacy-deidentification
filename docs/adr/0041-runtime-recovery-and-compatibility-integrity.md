# ADR-0041: Runtime recovery and compatibility integrity v1

## Status

Accepted — 2026-07-12. Builds on [ADR-0023](0023-runtime-worker-architecture.md) (job store,
worker isolation; this delivers the Phase-4 items "stale-running reclaim" and bounded retry),
[ADR-0030](0030-runtime-job-ux-notifications-v1.md) (frontend job activity), and
[ADR-0038](0038-artifact-and-document-lifecycle-integrity.md) (artifact authority; this closes the
remaining worker-side gap it documented). Branch `runtime-recovery-and-compatibility-v1`.

## Context — confirmed root causes

An audit of interruption and compatibility behavior confirmed these defects:

1. **A claimed job could stay `running` forever.** `claim_next_pending_job` transitioned
   pending → running with no lease, heartbeat, or reclaim path; a worker crash/OOM/restart left
   the row authoritative as `running` indefinitely (documented Phase-3 limitation of ADR-0023).
2. **Terminal transitions were unfenced.** `mark_succeeded`/`mark_failed` updated by `job_id`
   alone, so any late writer could overwrite whatever state the row had meanwhile reached.
3. **The job database's schema version was stamped unconditionally.** Initialization executed
   `CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version = 1` on every file — a newer or foreign
   database would be silently accepted and *downgraded* instead of refused.
4. **Readiness ignored processing.** `/health/ready` checked only storage directories; a broken or
   incompatible job database, or a dead worker in worker mode, still reported "ok".
5. **Frontend polling could hang or lie forever.** One rejected `fetchStatus` killed the owning
   poll loop; concurrent waiters (`waitForStoreTerminal`) then never settled; `resumeActiveJobs`
   produced unhandled rejections; a vanished job (404) was retried and re-persisted forever; and
   `localStorage` could resurrect years-old "running" entries.
6. **API payloads were trusted via unchecked casts.** `(await response.json()) as JobStatus`
   accepted any shape; an unknown `status` value could neither terminate nor be safely waited on.
   The versioned PII entity contract was consumed without checking `contract_version`.
7. **A damaged newest review-log line silently reactivated the older decision.** The JSONL
   decision log is collapsed to the latest record per target and `_parse_line` skipped unreadable
   lines silently — corruption of the newest decision quietly changed which decision was
   authoritative. Unknown `record_type` values (a newer app's records) were skipped the same way.

## Decision

### 1. Processing leases + deterministic recovery (job store schema v2)

Every `running` row carries `lease_expires_at`, set at claim (worker) or start (sync inline;
`JOB_LEASE_SECONDS`, default 1 h). `JobStore.recover_abandoned_jobs` resolves *abandoned* rows —
lease expired, or no lease at all (pre-v2 rows; nothing alive can have written them):

- worker-mode rows with attempts remaining → requeued (`pending`, attempt count kept, so the retry
  budget stays honest);
- everything else (budget exhausted, or synchronous inline rows whose request died — nothing can
  ever re-run those) → explicit terminal `failed` with the static `interrupted` error code.

Recovery runs at every meaningful boundary, so the guarantee holds without any single resident
sweeper: **worker startup** (which additionally reclaims *all* worker-mode `running` rows of its
kind regardless of lease age — the deployment enforces exactly one OCR worker, so any such row is
an orphan of the worker's own previous life), **every worker poll cycle**, **job enqueue**, and
**every job-status read** (observation recovers first: a poller can never watch a job stay
`running` forever merely because its worker disappeared). Recovery is set-based and idempotent —
the same store state resolves to the same outcome regardless of which process runs it.
`OCR_WORKER_MAX_ATTEMPTS` now defaults to 2: one automatic retry after an interruption, then
explicit failure.

### 2. Claim fencing — retries never conflict or duplicate

Terminal transitions are fenced to the claiming attempt (`WHERE status='running' AND
attempt_count = ?`). A writer whose claim was lost gets `StaleJobClaimError` and the recovered
state wins. Artifact publication is fenced the same way: a worker passes its claim attempt through
`create_text_artifact` → `publish_artifact_files`, which re-checks the claim under the document
lifecycle lock and refuses publication for a lost claim — a stale worker can no longer overwrite
the authority pointer with a result whose job success can never be recorded. Synchronous inline
runs stay unfenced at publication (no late publisher can exist for a dead request) and tolerate
`StaleJobClaimError` on their terminal marks the same way they tolerate deletion.

Residual race, accepted and documented: with a *misconfigured* multi-worker deployment, a worker
that outlives its lease can still publish files microseconds before its claim check; ADR-0038's
activation rule (authority requires the exact succeeded job) then fails those reads closed (409)
until the next coherent run — visible, never silent.

### 3. Versioned job database with an explicit refusal path

`PRAGMA user_version` is now read, not stamped: the current version (2) passes; a fresh file is
created at v2; the known v1 schema is migrated in one serialized `BEGIN IMMEDIATE` transaction
(adds `lease_expires_at` and the `worker_status` heartbeat table, preserving rows); anything else
— newer, unknown, or an unversioned file that already contains data — raises
`JobStoreIncompatibleError` naming the found/supported versions and **never** creates, stamps,
alters, or overwrites anything. The worker entrypoint fails fast (visible restart loop) on an
incompatible store instead of polling it.

### 4. Readiness reflects whether processing can proceed

`/health/ready` reports per-component states and gates on all applicable ones: `storage`
(writable), `job_store` (`ok`/`unavailable`/`incompatible`), and — in worker mode — `ocr_worker`
liveness from a heartbeat the worker writes from a dedicated thread (independent of in-flight OCR
work) every poll interval into the store's `worker_status` table
(`OCR_WORKER_HEARTBEAT_STALE_SECONDS`, default 60 s; `unknown` until a worker ever beats,
`not_applicable` in sync mode). "Ready" now genuinely means requests, persistence, *and*
processing work right now. `/health/live` (the Compose healthcheck) is unchanged.

### 5. Frontend polling that always settles, explicitly

`pollJobUntilTerminal` retries transient fetch failures (bounded consecutive-failure budget),
gives up immediately on a vanished job (404 → tracking removed — no stale activity) and on an
incompatible payload (never retryable), and records every give-up as an explicit poll failure on
the activity store. Waiters no longer wait only for a terminal status: every owner exit notifies
the store, and waiters settle from the recorded outcome — terminal status, the owner's
deadline-time last-known status, or a rejection carrying the recorded failure. `resumeActiveJobs`
catches resume failures (no unhandled rejections); the failure surfaces as an explicit
recovery-failure notice (`JobStatusBanner`), never as an eternal "läuft". Persisted non-terminal
jobs older than 24 h (or with unreadable timestamps/unknown statuses) are dropped at load — the
backend recovers abandoned claims long before that bound.

### 6. Frontend contract validation — fail closed

Job-status payloads are validated before they drive behavior (`parseJobStatus`: required identity
fields, `status` within the known set; additive unknown fields stay tolerated); an incompatible
payload raises the marker `IncompatibleApiPayloadError` instead of being accepted through a cast.
The PII entity contract validates `contract_version == "1.0"` plus its load-bearing shape: a
different version maps to the existing `incompatible` UI state, a malformed body to `error` —
never `ok`.

### 7. Append-only review log: damage is explicit, never a silent fallback

`_read_review_records` replaces silent line-skipping: an unreadable line — invalid JSON, a
non-object payload, an unknown `record_type` (a newer application's records), or a
schema-invalid record — raises `PiiReviewLogDamagedError` (500 with an explicit detail) for
**reads and writes**, because collapsing the log without that line would resurrect an older
decision as the apparent newest state. One deliberate exception: an unparseable **final fragment
without a trailing newline** is a torn append whose write (append + fsync) never completed and was
therefore never acknowledged to any client — ignoring it serves exactly the state callers were
told had been stored. Immutable artifact snapshots were already fail-closed via ADR-0038's
authority model (a damaged pointed artifact raises, never falls back to older files).

## Consequences

- Interrupted work now always converges: requeue-and-retry or explicit `interrupted` failure — at
  worker restart, during polling, on enqueue, and on observation.
- Job-status reads (GET) perform the idempotent recovery sweep — a deliberate, documented
  observation-repairs-state choice for this local single-node product.
- Two schema-version policies now exist in writing: the job DB refuses unknown versions; review
  JSONL records refuse unknown record types; both changed only via explicit, versioned migration.
- Client polling ends in bounded time with an explicit outcome in every failure mode.
- Normal processing, review, restart, and retry flows are unchanged in the success path (proven by
  the untouched remainder of both test suites).

## Limitations

- Worker liveness is heartbeat-based; a wedged-but-beating worker looks alive. Concurrency stays
  1; there is still no queue broker, cancel API, or PII worker split (ADR-0023 Phase 4 remainder).
- The multi-worker misconfiguration race above degrades to explicit 409s, not to silence.
- Review-log damage requires manual operator intervention (inspect/repair the JSONL); there is no
  automated quarantine/rebuild yet.
- The v1→v2 job-DB migration is forward-only; downgrading the application against a v2 database
  fails explicitly (by design).
