// Runtime Job UX v1: a small, framework-agnostic activity layer over the safe job-status API.
//
// This module never talks to the network itself — callers inject a `fetchStatus` function — so it
// stays trivially unit-testable and has no opinion about which station/job kind it tracks. It only
// ever stores what the backend's `JobStatus` already exposes (ids, timestamps, sanitized error
// code/message, produced artifact reference): no raw document text, OCR text, or PII ever passes
// through here.
//
// Reload recovery: active (non-terminal) jobs are persisted to `localStorage` so a page reload can
// rehydrate and resume polling. Persistence is best-effort — a missing/unavailable `localStorage`
// (private browsing, quota, SSR) degrades to in-memory-only tracking rather than throwing.
//
// Duplicate-polling guard: `beginPolling`/`endPolling` implement a simple try-lock so at most one
// poll loop ever runs per job id, whether it was started by a live submit (e.g. `runOcr`) or by a
// reload-recovery resume — see `pollJobUntilTerminal`.

import type { JobStatus } from "../api/workstations";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const STORAGE_KEY = "runtime.job-activity.v1";
const MAX_TRACKED_JOBS = 20;
const DEFAULT_POLL_INTERVAL_MS = 2000;
/** Give up a poll loop after this many back-to-back fetch failures; the failure is recorded on the
 * store (visible to the UI and to concurrent waiters) instead of spinning forever. */
const MAX_CONSECUTIVE_POLL_FAILURES = 5;
/** A persisted non-terminal job older than this cannot still be running (the backend recovers
 * abandoned claims long before): drop it at load instead of resurrecting stale activity forever. */
const MAX_PERSISTED_ACTIVE_AGE_MS = 24 * 60 * 60 * 1000;

const TERMINAL_STATUSES = new Set<JobStatus["status"]>(["succeeded", "failed", "canceled"]);
const KNOWN_STATUSES = new Set<string>([
  "pending",
  "running",
  "succeeded",
  "failed",
  "canceled",
]);

const POLL_FAILURE_MESSAGE =
  "Der Status der Hintergrundverarbeitung konnte nicht abgerufen werden.";
const JOB_GONE_MESSAGE = "Der Verarbeitungsauftrag ist nicht mehr vorhanden.";

export function isTerminalStatus(status: JobStatus["status"]): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** Real browser localStorage when available; `null` in any other environment (tests, SSR). */
function getBrowserLocalStorage(): StorageLike | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    // Some browsers throw synchronously accessing localStorage under strict privacy settings.
    return null;
  }
}

type Listener = () => void;

export class JobActivityStore {
  private readonly jobs = new Map<string, JobStatus>();
  private readonly polling = new Set<string>();
  private readonly pollFailures = new Map<string, string>();
  private readonly listeners = new Set<Listener>();
  private hydrated = false;

  constructor(private readonly storage: StorageLike | null) {}

  /** Load persisted jobs from storage. Safe to call more than once; only hydrates once. */
  loadPersisted(): void {
    if (this.hydrated) {
      return;
    }
    this.hydrated = true;
    if (!this.storage) {
      return;
    }
    try {
      const raw = this.storage.getItem(STORAGE_KEY);
      if (!raw) {
        return;
      }
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return;
      }
      for (const entry of parsed) {
        if (isJobStatusLike(entry) && !isStalePersistedActiveJob(entry)) {
          this.jobs.set(entry.job_id, entry);
        }
      }
    } catch {
      // Corrupt/unavailable storage must never crash the page; start with an empty store.
    }
  }

  /** Upsert a job's latest known status and persist/notify. Never throws. */
  record(job: JobStatus): void {
    this.jobs.set(job.job_id, job);
    this.prune();
    this.persist();
    this.notify();
  }

  /** Remove one job from tracking (e.g. explicit user dismissal, or a job the backend no longer
   * knows). Clears any recorded poll failure with it. */
  remove(jobId: string): void {
    this.pollFailures.delete(jobId);
    if (this.jobs.delete(jobId)) {
      this.persist();
      this.notify();
    }
  }

  /** Snapshot of tracked jobs, newest-updated first, optionally scoped to one document. */
  list(documentId?: string): JobStatus[] {
    const all = [...this.jobs.values()];
    const scoped = documentId ? all.filter((job) => job.document_id === documentId) : all;
    return scoped.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }

  getJob(jobId: string): JobStatus | undefined {
    return this.jobs.get(jobId);
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Try-lock: returns `true` only if the caller is now the sole owner of polling this job. A new
   * owner clears any failure a previous poll loop recorded — it is being retried right now. */
  beginPolling(jobId: string): boolean {
    if (this.polling.has(jobId)) {
      return false;
    }
    this.polling.add(jobId);
    this.pollFailures.delete(jobId);
    return true;
  }

  /** Release the poll lock and notify, so concurrent waiters re-check the outcome (terminal
   * status, recorded failure, or the last known state at a deadline) instead of waiting forever. */
  endPolling(jobId: string): void {
    this.polling.delete(jobId);
    this.notify();
  }

  isPolling(jobId: string): boolean {
    return this.polling.has(jobId);
  }

  /** Record why polling this job gave up, keeping the failure visible to the UI and to waiters. */
  failPolling(jobId: string, message: string): void {
    this.pollFailures.set(jobId, message);
  }

  getPollFailure(jobId: string): string | undefined {
    return this.pollFailures.get(jobId);
  }

  private prune(): void {
    if (this.jobs.size <= MAX_TRACKED_JOBS) {
      return;
    }
    const overflow = this.list().slice(MAX_TRACKED_JOBS);
    for (const job of overflow) {
      // Never drop a job that is still actively being polled, even under storage pressure.
      if (!this.polling.has(job.job_id)) {
        this.jobs.delete(job.job_id);
      }
    }
  }

  private persist(): void {
    if (!this.storage) {
      return;
    }
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(this.list()));
    } catch {
      // Quota/availability issues degrade to in-memory-only tracking for this session.
    }
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }
}

function isJobStatusLike(value: unknown): value is JobStatus {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<JobStatus>;
  return (
    typeof candidate.job_id === "string" &&
    typeof candidate.document_id === "string" &&
    typeof candidate.status === "string" &&
    // A status this build does not know (written by a different version) must not be restored:
    // polling code could neither classify it as terminal nor safely wait on it.
    KNOWN_STATUSES.has(candidate.status) &&
    typeof candidate.updated_at === "string"
  );
}

/** A persisted *non-terminal* job too old to still be running anywhere (or with an unreadable
 * timestamp) is stale activity, not recoverable work. Terminal entries stay regardless of age. */
function isStalePersistedActiveJob(job: JobStatus): boolean {
  if (isTerminalStatus(job.status)) {
    return false;
  }
  const updatedAt = Date.parse(job.updated_at);
  if (Number.isNaN(updatedAt)) {
    return true;
  }
  return Date.now() - updatedAt > MAX_PERSISTED_ACTIVE_AGE_MS;
}

export function createJobActivityStore(storage?: StorageLike | null): JobActivityStore {
  return new JobActivityStore(storage === undefined ? getBrowserLocalStorage() : storage);
}

/** App-wide singleton. Tests should prefer `createJobActivityStore()` for an isolated instance. */
export const jobActivityStore = createJobActivityStore();

export interface PollOptions {
  intervalMs?: number;
  /** Absolute deadline in epoch ms. When reached with a non-terminal job, polling stops and the
   * caller receives the last known (non-terminal) status rather than an error — callers decide
   * what a timeout means for their station. */
  deadlineAt?: number;
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

/** `true` when a status fetch failed because the job no longer exists on the backend. */
function isJobGoneError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { status?: unknown }).status === 404
  );
}

/** `true` for a payload this build cannot understand — retrying would see the same bytes again,
 * so the poll loop gives up immediately instead of burning its retry budget. */
function isIncompatiblePayloadError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { incompatiblePayload?: unknown }).incompatiblePayload === true
  );
}

function pollFailureMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return POLL_FAILURE_MESSAGE;
}

/**
 * Poll one job until it reaches a terminal status, recording every observed update in `store`.
 *
 * At most one poll loop ever runs per job id (see `beginPolling`): a second concurrent call for the
 * same job id waits on the store instead of starting a redundant fetch loop, so a live submit and a
 * reload-recovery resume can never double-poll the same job. The waiting side always settles: when
 * the owning loop ends — terminal status, give-up after repeated fetch failures, a vanished job, or
 * its deadline — waiters resolve or reject from the store's recorded outcome rather than hanging
 * forever.
 *
 * Transient fetch failures are retried up to `MAX_CONSECUTIVE_POLL_FAILURES` times; a `404` means
 * the job no longer exists (e.g. its document was deleted), so tracking is removed instead of
 * being retried or persisted as stale activity. Both give-up paths record an explicit failure on
 * the store (see `getPollFailure`) and reject, so a request/recovery failure is never silent.
 */
export async function pollJobUntilTerminal(
  store: JobActivityStore,
  jobId: string,
  fetchStatus: (jobId: string) => Promise<JobStatus>,
  options: PollOptions = {},
): Promise<JobStatus> {
  if (!store.beginPolling(jobId)) {
    return waitForPollingOutcome(store, jobId);
  }
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  let consecutiveFailures = 0;
  try {
    while (true) {
      let job: JobStatus;
      try {
        job = await fetchStatus(jobId);
        consecutiveFailures = 0;
      } catch (error) {
        if (isJobGoneError(error)) {
          store.failPolling(jobId, JOB_GONE_MESSAGE);
          store.remove(jobId);
          throw error;
        }
        if (isIncompatiblePayloadError(error)) {
          store.failPolling(jobId, pollFailureMessage(error));
          throw error;
        }
        consecutiveFailures += 1;
        if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          store.failPolling(jobId, pollFailureMessage(error));
          throw error;
        }
        await sleep(intervalMs);
        continue;
      }
      store.record(job);
      if (isTerminalStatus(job.status)) {
        return job;
      }
      if (options.deadlineAt !== undefined && Date.now() >= options.deadlineAt) {
        return job;
      }
      await sleep(intervalMs);
    }
  } finally {
    store.endPolling(jobId);
  }
}

/** Settle once the owning poll loop produces an outcome for `jobId`.
 *
 * Resolves with the job's terminal status; resolves with the last known (non-terminal) status when
 * the owner stopped at its deadline — mirroring the owner's own return contract; rejects when the
 * owner recorded a poll failure or the job is gone. Never waits forever: every owner exit notifies
 * the store, and the state is re-checked immediately after subscribing to close the startup race.
 */
function waitForPollingOutcome(store: JobActivityStore, jobId: string): Promise<JobStatus> {
  const outcome = (): { job?: JobStatus; error?: Error } | null => {
    const job = store.getJob(jobId);
    if (job && isTerminalStatus(job.status)) {
      return { job };
    }
    if (store.isPolling(jobId)) {
      return null;
    }
    const failure = store.getPollFailure(jobId);
    if (failure !== undefined) {
      return { error: new Error(failure) };
    }
    if (job) {
      return { job };
    }
    return { error: new Error(JOB_GONE_MESSAGE) };
  };
  return new Promise((resolve, reject) => {
    const settle = (result: { job?: JobStatus; error?: Error }) => {
      if (result.job) {
        resolve(result.job);
      } else {
        reject(result.error);
      }
    };
    const unsubscribe = store.subscribe(() => {
      const result = outcome();
      if (result !== null) {
        unsubscribe();
        settle(result);
      }
    });
    // The owner may have finished between the failed try-lock and subscribing.
    const immediate = outcome();
    if (immediate !== null) {
      unsubscribe();
      settle(immediate);
    }
  });
}

/**
 * Resume tracking for one document's active jobs after a fresh page load.
 *
 * Reads any locally persisted (non-terminal) jobs for `documentId` first, then — best-effort —
 * asks the backend's document-jobs listing for anything the client did not already know about
 * (e.g. `localStorage` was cleared, or this is a different browser/tab). Any non-terminal job found
 * either way resumes polling through the same de-duplicated `pollJobUntilTerminal` path. A resume
 * poll that ultimately fails records its failure on the store (rendered as an explicit recovery
 * notice) instead of surfacing an unhandled rejection or leaving stale activity behind.
 */
export function resumeActiveJobs(
  store: JobActivityStore,
  documentId: string,
  fetchStatus: (jobId: string) => Promise<JobStatus>,
  fetchDocumentJobs?: (documentId: string) => Promise<JobStatus[]>,
): void {
  store.loadPersisted();
  const resumePoll = (jobId: string) => {
    pollJobUntilTerminal(store, jobId, fetchStatus).catch(() => {
      // The failure is already recorded on the store (getPollFailure) and shown by the UI;
      // swallowing here only prevents an unhandled rejection from a fire-and-forget resume.
    });
  };
  for (const job of store.list(documentId)) {
    if (!isTerminalStatus(job.status)) {
      resumePoll(job.job_id);
    }
  }
  if (!fetchDocumentJobs) {
    return;
  }
  void fetchDocumentJobs(documentId)
    .then((jobs) => {
      for (const job of jobs) {
        store.record(job);
        if (!isTerminalStatus(job.status)) {
          resumePoll(job.job_id);
        }
      }
    })
    .catch(() => {
      // Best-effort recovery only; localStorage-tracked jobs (if any) still resumed above.
    });
}
