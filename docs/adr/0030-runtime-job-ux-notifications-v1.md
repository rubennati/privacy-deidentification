# ADR-0030: Runtime Job UX / In-App Notifications v1

## Status

Accepted / implemented additively — 2026-07-09. Builds on
[ADR-0023](0023-runtime-worker-architecture.md) (job model, SQLite job store, `ocr-worker`,
`202`/job-status contract). This ADR does not change the job model, the job store schema, the OCR
worker, or any engine/artifact contract — it is the **product-facing presentation layer** on top of
the runtime already delivered by ADR-0023 Phases 1–3.6.

## Context

ADR-0023 gives the backend a durable job lifecycle (`pending → running → succeeded/failed`) and a
safe status API (`GET /api/jobs/{job_id}`, `GET /api/documents/{document_id}/jobs`), and Phase 3.6
made the frontend consume the worker-mode `202` contract: `runOcr()` polls the job and then fetches
the finished artifact. But that polling was entirely internal to one in-flight `runOcr()` call and
invisible to the rest of the page:

- A page reload during OCR lost all knowledge that a job was in flight. The document page came back
  looking idle, with no way to tell "still running" from "never started," even though the worker was
  still processing the job server-side.
- There was no shared, reactive place other UI (a status banner, a future notifications panel) could
  read job progress from — only the one `Promise` chain inside `runOcr()`.
- Nothing prevented two independent polling loops (a live call and a hypothetical recovery path)
  from hitting `GET /api/jobs/{job_id}` for the same job at once.

This is a UX/runtime-visibility gap, not a missing backend capability: the job contract already
carries everything needed to answer "is it still running, and did it work?" The job is to expose
that safely and reactively, without adding infrastructure ADR-0023 explicitly deferred (Redis/RQ/
Celery, WebSocket/SSE, browser push, email).

## Decision

**Polling + `localStorage` is v1.** No new transport, no new backend service:

1. **Backend: one additive field.** `JobStatusResponse` gains `is_terminal: bool`
   (`backend/app/schemas.py`, computed in `backend/app/api/jobs.py`) so a client does not have to
   hardcode which statuses are terminal. No other backend change — `JobRecord`/`JobStatus`,
   `JobStore`, the OCR worker, and the existing `GET /api/jobs/{job_id}` /
   `GET /api/documents/{document_id}/jobs` endpoints (already newest-first, already document-scoped,
   already bounded) already carried enough safe metadata (kind, status, timestamps, sanitized
   `error_code`/`error_message`, produced artifact id/type) for the UX this ADR adds. Per the
   guidance that shaped this change, the backend is deliberately **not** extended with
   `display_status`/`display_message`/`progress_stage` fields — that presentation logic lives in the
   frontend (`frontend/src/lib/jobDisplay.ts`), consistent with how `stationErrors.ts` and
   `runtimeNotice.ts` already own user-facing text for this app.

2. **Frontend: a small, framework-agnostic job activity store**
   (`frontend/src/lib/jobActivity.ts`). It is a plain class (`JobActivityStore`) over a `Map`, not a
   React hook, so it is directly unit-testable and has no opinion about *when* React re-renders:
   - `record(job)` upserts a job's latest known status and persists it to `localStorage` (best
     effort — a missing/throwing `localStorage`, e.g. private browsing, degrades to in-memory-only
     tracking rather than crashing).
   - `beginPolling(jobId)` / `endPolling(jobId)` is a try-lock: at most one poll loop ever runs per
     job id. `pollJobUntilTerminal(store, jobId, fetchStatus, options)` uses it, so a live `runOcr()`
     call and a reload-recovery resume racing for the same job id never double-poll — the second
     caller just waits on the store's own update stream instead of starting a second fetch loop.
   - `resumeActiveJobs(store, documentId, fetchStatus, fetchDocumentJobs?)` rehydrates persisted jobs
     for one document from `localStorage` and resumes polling any non-terminal one; it also calls the
     existing `GET /api/documents/{id}/jobs` as a best-effort fallback, so recovery still works if
     `localStorage` was cleared or this is a different browser/tab — the backend was already the
     source of truth here, `localStorage` is only a fast/cheap local index into it.

3. **`runOcr()` is refactored to *use* the shared store, not duplicate it.** It still returns the
   same artifact-or-throw contract external callers already depend on (unchanged fetch call
   count/order — existing tests assert this). Internally, the 202 job is `record()`-ed immediately
   (so a subscriber sees "accepted" before the first poll tick), and the polling loop moves into
   `pollJobUntilTerminal` so it participates in the same single-owner lock reload recovery uses.

4. **A small presentational surface**, not a redesign: `JobStatusBanner`
   (`frontend/src/components/JobStatusBanner.tsx`) renders one of accepted/running/succeeded/failed/
   canceled from a `JobStatus`, using `jobDisplay.ts`'s pure `describeJob()` mapping. It is wired into
   the existing document detail page's Review section, shown only while nothing on the page is
   already displaying its own live progress UI (a click-triggered run keeps its existing
   `DocumentAnalysisPanel`/`StationPanel` progress display) — so the banner's job is specifically to
   fill the reload/recovery gap, not to duplicate the live-run UI.

5. **Result refresh on recovery.** When a recovered/background-tracked OCR job reaches `succeeded`
   and nothing local is already handling it, the document page fetches the OCR artifact and applies
   it exactly like a live run would (guarded by a handled-job-id set, so this never double-fires for
   the same job or races a live call's own `setText`). If that fetch itself fails, the page shows a
   controlled "job completed but the result could not be loaded" message rather than looking stuck.
   A recovered `failed`/`canceled` job shows the backend's sanitized `error_message` (falling back to
   a generic message) — never a raw exception or stack trace, matching ADR-0023's existing job
   privacy rules.

## What this explicitly does not add

- No Redis, RQ, Celery, or any message broker.
- No WebSocket, Server-Sent Events, or browser/OS/email push notifications.
- No change to the job model, `JobStore` schema, the OCR worker, or `OCR_EXECUTION_MODE` semantics.
- No change to OCR/PII detection behavior, `DocumentTextPackageV1`, or any artifact contract.
- No PII job/worker (PII stays synchronous, unchanged).
- No cancellation, retry, or stale-lease reclaim UI — those remain ADR-0023 Phase 4 backend work.
- No global "recent jobs across all documents" panel; the recovery surface is scoped to the document
  page a job belongs to, matching the app's existing per-document structure.

## Consequences

- The frontend now has one shared, reactive place (`jobActivityStore`) that both a live call and a
  reload can read/write job status through, instead of state trapped inside one `Promise` chain.
- **Job status is a stable contract the frontend consumes, not worker internals** (already true per
  [`target-architecture.md`](../engine/target-architecture.md#runtime-job-contract)): a future
  transport swap (SSE/WebSocket/event bus) can replace *how* `jobActivityStore` learns about updates
  without changing `JobStatus`, `JobActivityStore`'s public API, or any component that reads from it.
- `localStorage` is a convenience index, not a new source of truth — SQLite (via the existing job
  API) remains authoritative, and the document-jobs fallback means a cleared/unavailable
  `localStorage` degrades to "recovery takes one extra request" rather than "recovery silently
  fails."
- No new privacy surface: everything the store/banner touches was already safe, sanitized job
  metadata under ADR-0023's existing privacy rules (ids, timestamps, sanitized error code/message,
  produced artifact id/type — never raw document text, OCR text, or PII).
