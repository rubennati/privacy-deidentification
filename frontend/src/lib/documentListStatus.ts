import type { JobStatus } from "../api/workstations";

/**
 * Coarse per-document analysis state for the documents list, derived from the metadata-only jobs
 * endpoint (never from artifact contents). Deliberately three states a reader can act on:
 * - "running": something is in flight right now
 * - "analyzed": a PII detection has succeeded at least once (list-level info; the detail page
 *   remains the authority on staleness/lineage)
 * - "none": no successful analysis yet
 */
export type DocumentAnalysisState = "analyzed" | "running" | "none";

/** A pending/running job without progress for this long is treated as abandoned for display.
 *  Runtime Phase 3 has no stale-lease reclaim yet (a worker killed mid-job leaves the row
 *  "running" forever — Phase 4 work); a badge must not claim activity that stopped long ago. */
const RUNNING_STALE_AFTER_MS = 15 * 60 * 1000;

export function deriveAnalysisState(
  jobs: readonly JobStatus[],
  now: Date = new Date(),
): DocumentAnalysisState {
  const isFresh = (job: JobStatus): boolean => {
    const lastActivity = Date.parse(job.updated_at ?? job.created_at);
    return Number.isFinite(lastActivity) && now.getTime() - lastActivity < RUNNING_STALE_AFTER_MS;
  };
  if (jobs.some((job) => (job.status === "pending" || job.status === "running") && isFresh(job))) {
    return "running";
  }
  if (jobs.some((job) => job.kind === "pii_detection" && job.status === "succeeded")) {
    return "analyzed";
  }
  return "none";
}
