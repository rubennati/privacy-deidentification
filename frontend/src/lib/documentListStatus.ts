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

export function deriveAnalysisState(jobs: readonly JobStatus[]): DocumentAnalysisState {
  if (jobs.some((job) => job.status === "pending" || job.status === "running")) {
    return "running";
  }
  if (jobs.some((job) => job.kind === "pii_detection" && job.status === "succeeded")) {
    return "analyzed";
  }
  return "none";
}
