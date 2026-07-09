import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JobStatus } from "../api/workstations";
import {
  createJobActivityStore,
  pollJobUntilTerminal,
  resumeActiveJobs,
  type StorageLike,
} from "./jobActivity";

function job(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    job_id: "job-1",
    document_id: "doc-1",
    kind: "ocr_text",
    status: "pending",
    execution_mode: "future_worker",
    created_at: "2026-07-09T10:00:00.000000Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-07-09T10:00:00.000000Z",
    attempt_count: 0,
    error_code: null,
    error_message: null,
    result_artifact_id: null,
    result_artifact_type: null,
    metadata: {},
    is_terminal: false,
    ...overrides,
  };
}

/** Minimal in-memory Storage double so persistence is testable without a real browser. */
function createFakeStorage(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
    removeItem: (key) => {
      data.delete(key);
    },
  };
}

describe("JobActivityStore", () => {
  it("records and lists jobs, newest-updated first", () => {
    const store = createJobActivityStore(null);
    store.record(job({ job_id: "a", updated_at: "2026-07-09T10:00:01.000000Z" }));
    store.record(job({ job_id: "b", updated_at: "2026-07-09T10:00:02.000000Z" }));

    expect(store.list().map((j) => j.job_id)).toEqual(["b", "a"]);
  });

  it("scopes list() to one document", () => {
    const store = createJobActivityStore(null);
    store.record(job({ job_id: "a", document_id: "doc-1" }));
    store.record(job({ job_id: "b", document_id: "doc-2" }));

    expect(store.list("doc-1").map((j) => j.job_id)).toEqual(["a"]);
  });

  it("removes a job and notifies subscribers", () => {
    const store = createJobActivityStore(null);
    store.record(job());
    const listener = vi.fn();
    store.subscribe(listener);

    store.remove("job-1");

    expect(store.getJob("job-1")).toBeUndefined();
    expect(listener).toHaveBeenCalled();
  });

  it("persists jobs to injected storage and reloads them in a fresh store instance", () => {
    const storage = createFakeStorage();
    const first = createJobActivityStore(storage);
    first.record(job({ status: "running" }));

    const second = createJobActivityStore(storage);
    second.loadPersisted();

    expect(second.getJob("job-1")).toMatchObject({ job_id: "job-1", status: "running" });
  });

  it("tolerates corrupt persisted JSON instead of crashing", () => {
    const storage = createFakeStorage();
    storage.setItem("runtime.job-activity.v1", "{not json");
    const store = createJobActivityStore(storage);

    expect(() => store.loadPersisted()).not.toThrow();
    expect(store.list()).toEqual([]);
  });

  it("only hydrates from storage once per store instance", () => {
    const storage = createFakeStorage();
    const store = createJobActivityStore(storage);
    store.loadPersisted();
    storage.setItem("runtime.job-activity.v1", JSON.stringify([job({ job_id: "late" })]));

    store.loadPersisted();

    expect(store.getJob("late")).toBeUndefined();
  });

  it("prunes old terminal jobs beyond the tracked limit but never an actively polling job", () => {
    const store = createJobActivityStore(null);
    store.record(job({ job_id: "actively-polled", updated_at: "2026-07-09T09:00:00.000000Z" }));
    expect(store.beginPolling("actively-polled")).toBe(true);

    for (let i = 0; i < 25; i += 1) {
      store.record(
        job({ job_id: `overflow-${i}`, updated_at: `2026-07-09T10:00:${String(i).padStart(2, "0")}.000000Z` }),
      );
    }

    expect(store.getJob("actively-polled")).toBeDefined();
    expect(store.list().length).toBeLessThanOrEqual(21); // 20 tracked + the pinned polling job
  });

  it("begin/endPolling implement a single-owner try-lock", () => {
    const store = createJobActivityStore(null);

    expect(store.beginPolling("job-1")).toBe(true);
    expect(store.beginPolling("job-1")).toBe(false);
    store.endPolling("job-1");
    expect(store.beginPolling("job-1")).toBe(true);
  });
});

describe("pollJobUntilTerminal", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls until a terminal status, recording every update", async () => {
    vi.useFakeTimers();
    const store = createJobActivityStore(null);
    const fetchStatus = vi
      .fn<(jobId: string) => Promise<JobStatus>>()
      .mockResolvedValueOnce(job({ status: "pending" }))
      .mockResolvedValueOnce(job({ status: "running" }))
      .mockResolvedValueOnce(job({ status: "succeeded", result_artifact_id: "a".repeat(32) }));

    const resultPromise = pollJobUntilTerminal(store, "job-1", fetchStatus, { intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(1000);
    const result = await resultPromise;

    expect(fetchStatus).toHaveBeenCalledTimes(3);
    expect(result.status).toBe("succeeded");
    expect(store.getJob("job-1")?.status).toBe("succeeded");
  });

  it("returns the last known status once the deadline passes without a terminal state", async () => {
    vi.useFakeTimers();
    const store = createJobActivityStore(null);
    const fetchStatus = vi.fn<(jobId: string) => Promise<JobStatus>>().mockResolvedValue(
      job({ status: "running" }),
    );

    const resultPromise = pollJobUntilTerminal(store, "job-1", fetchStatus, {
      intervalMs: 1000,
      deadlineAt: Date.now(),
    });
    const result = await resultPromise;

    expect(result.status).toBe("running");
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("never starts a second poll loop for a job already being polled", async () => {
    vi.useFakeTimers();
    const store = createJobActivityStore(null);
    let resolveSecondFetch: (value: JobStatus) => void = () => {};
    const fetchStatus = vi
      .fn<(jobId: string) => Promise<JobStatus>>()
      .mockResolvedValueOnce(job({ status: "running" }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondFetch = resolve;
          }),
      );

    const first = pollJobUntilTerminal(store, "job-1", fetchStatus, { intervalMs: 1000 });
    // A second caller (e.g. a reload-recovery resume racing a live submit) must not add a fetch.
    const second = pollJobUntilTerminal(store, "job-1", fetchStatus, { intervalMs: 1000 });

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    resolveSecondFetch(job({ status: "succeeded" }));

    const [firstResult, secondResult] = await Promise.all([first, second]);
    expect(firstResult.status).toBe("succeeded");
    expect(secondResult.status).toBe("succeeded");
    // Exactly one loop ever called fetchStatus (2 calls total: initial + one poll tick).
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("tolerates a job status missing optional fields without crashing", async () => {
    const store = createJobActivityStore(null);
    const legacyJob = {
      job_id: "job-1",
      document_id: "doc-1",
      kind: "ocr_text",
      status: "succeeded",
      execution_mode: "future_worker",
      created_at: "2026-07-09T10:00:00.000000Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-07-09T10:00:00.000000Z",
      attempt_count: 1,
      error_code: null,
      error_message: null,
      result_artifact_id: null,
      result_artifact_type: null,
      metadata: {},
      // `is_terminal` intentionally omitted, as a legacy/mocked response might.
    } as JobStatus;
    const fetchStatus = vi.fn().mockResolvedValue(legacyJob);

    const result = await pollJobUntilTerminal(store, "job-1", fetchStatus);

    expect(result.status).toBe("succeeded");
  });
});

describe("resumeActiveJobs", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resumes polling a persisted non-terminal job for the given document", async () => {
    const storage = createFakeStorage();
    const bootstrap = createJobActivityStore(storage);
    bootstrap.record(job({ job_id: "persisted", status: "running" }));

    const store = createJobActivityStore(storage);
    const fetchStatus = vi.fn().mockResolvedValue(job({ job_id: "persisted", status: "succeeded" }));

    resumeActiveJobs(store, "doc-1", fetchStatus);
    await vi.runOnlyPendingTimersAsync();

    expect(fetchStatus).toHaveBeenCalledWith("persisted");
    expect(store.getJob("persisted")?.status).toBe("succeeded");
  });

  it("discovers and resumes a job the client did not already know about via the document-jobs fallback", async () => {
    const store = createJobActivityStore(null);
    const remoteJob = job({ job_id: "server-known", status: "running" });
    const fetchDocumentJobs = vi.fn().mockResolvedValue([remoteJob]);
    const fetchStatus = vi
      .fn()
      .mockResolvedValue(job({ job_id: "server-known", status: "succeeded" }));

    resumeActiveJobs(store, "doc-1", fetchStatus, fetchDocumentJobs);
    await vi.waitFor(() => expect(store.getJob("server-known")).toBeDefined());
    await vi.runOnlyPendingTimersAsync();

    expect(fetchDocumentJobs).toHaveBeenCalledWith("doc-1");
    expect(store.getJob("server-known")?.status).toBe("succeeded");
  });

  it("swallows a document-jobs fallback failure without throwing", async () => {
    const store = createJobActivityStore(null);
    const fetchDocumentJobs = vi.fn().mockRejectedValue(new Error("network down"));
    const fetchStatus = vi.fn();

    expect(() => resumeActiveJobs(store, "doc-1", fetchStatus, fetchDocumentJobs)).not.toThrow();
    await vi.waitFor(() => expect(fetchDocumentJobs).toHaveBeenCalled());
  });
});
