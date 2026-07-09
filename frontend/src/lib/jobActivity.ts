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

const TERMINAL_STATUSES = new Set<JobStatus["status"]>(["succeeded", "failed", "canceled"]);

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
        if (isJobStatusLike(entry)) {
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

  /** Remove one job from tracking (e.g. explicit user dismissal). */
  remove(jobId: string): void {
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

  /** Try-lock: returns `true` only if the caller is now the sole owner of polling this job. */
  beginPolling(jobId: string): boolean {
    if (this.polling.has(jobId)) {
      return false;
    }
    this.polling.add(jobId);
    return true;
  }

  endPolling(jobId: string): void {
    this.polling.delete(jobId);
  }

  isPolling(jobId: string): boolean {
    return this.polling.has(jobId);
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
    typeof candidate.updated_at === "string"
  );
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

/**
 * Poll one job until it reaches a terminal status, recording every observed update in `store`.
 *
 * At most one poll loop ever runs per job id (see `beginPolling`): a second concurrent call for the
 * same job id simply waits on the store's own updates instead of starting a redundant fetch loop,
 * so a live submit and a reload-recovery resume can never double-poll the same job.
 */
export async function pollJobUntilTerminal(
  store: JobActivityStore,
  jobId: string,
  fetchStatus: (jobId: string) => Promise<JobStatus>,
  options: PollOptions = {},
): Promise<JobStatus> {
  if (!store.beginPolling(jobId)) {
    return waitForStoreTerminal(store, jobId);
  }
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  try {
    while (true) {
      const job = await fetchStatus(jobId);
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

/** Resolve once the store observes a terminal status for `jobId` (from whichever loop owns it). */
function waitForStoreTerminal(store: JobActivityStore, jobId: string): Promise<JobStatus> {
  const existing = store.getJob(jobId);
  if (existing && isTerminalStatus(existing.status)) {
    return Promise.resolve(existing);
  }
  return new Promise((resolve) => {
    const unsubscribe = store.subscribe(() => {
      const job = store.getJob(jobId);
      if (job && isTerminalStatus(job.status)) {
        unsubscribe();
        resolve(job);
      }
    });
  });
}

/**
 * Resume tracking for one document's active jobs after a fresh page load.
 *
 * Reads any locally persisted (non-terminal) jobs for `documentId` first, then — best-effort —
 * asks the backend's document-jobs listing for anything the client did not already know about
 * (e.g. `localStorage` was cleared, or this is a different browser/tab). Any non-terminal job found
 * either way resumes polling through the same de-duplicated `pollJobUntilTerminal` path.
 */
export function resumeActiveJobs(
  store: JobActivityStore,
  documentId: string,
  fetchStatus: (jobId: string) => Promise<JobStatus>,
  fetchDocumentJobs?: (documentId: string) => Promise<JobStatus[]>,
): void {
  store.loadPersisted();
  for (const job of store.list(documentId)) {
    if (!isTerminalStatus(job.status)) {
      void pollJobUntilTerminal(store, job.job_id, fetchStatus);
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
          void pollJobUntilTerminal(store, job.job_id, fetchStatus);
        }
      }
    })
    .catch(() => {
      // Best-effort recovery only; localStorage-tracked jobs (if any) still resumed above.
    });
}
