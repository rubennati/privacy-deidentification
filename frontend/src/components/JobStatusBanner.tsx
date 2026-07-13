import type { JobStatus } from "../api/workstations";
import { describeJob } from "../lib/jobDisplay";
import { StatusNotice, type UploadStatus } from "./StatusNotice";

interface JobStatusBannerProps {
  /** The tracked job to reflect, or `null`/`undefined` to render nothing. */
  job: JobStatus | null | undefined;
  /** Why polling this job's status gave up, if it did — rendered as an explicit error so a
   * recovery/polling failure is never silently indistinguishable from "still running". */
  pollFailureMessage?: string | null;
}

const TONE_TO_STATUS: Record<ReturnType<typeof describeJob>["tone"], UploadStatus> = {
  info: "uploading",
  success: "success",
  error: "error",
};

/**
 * Reload-recovery status surface: shows a background-tracked job's current state (queued, running,
 * succeeded, failed) even when no local in-flight call is driving the page's own progress UI — e.g.
 * right after a page reload, before the user clicks anything. Renders nothing without a job.
 */
export function JobStatusBanner({ job, pollFailureMessage }: JobStatusBannerProps) {
  if (!job) {
    return null;
  }
  if (pollFailureMessage && job.status !== "succeeded" && job.status !== "failed") {
    return (
      <StatusNotice
        status="error"
        message={`Die Hintergrundverarbeitung konnte nicht weiter verfolgt werden: ${pollFailureMessage}`}
      />
    );
  }
  const { tone, message } = describeJob(job);
  return <StatusNotice status={TONE_TO_STATUS[tone]} message={message} />;
}
