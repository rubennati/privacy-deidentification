import type { JobStatus } from "../api/workstations";
import { describeJob } from "../lib/jobDisplay";
import { StatusNotice, type UploadStatus } from "./StatusNotice";

interface JobStatusBannerProps {
  /** The tracked job to reflect, or `null`/`undefined` to render nothing. */
  job: JobStatus | null | undefined;
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
export function JobStatusBanner({ job }: JobStatusBannerProps) {
  if (!job) {
    return null;
  }
  const { tone, message } = describeJob(job);
  return <StatusNotice status={TONE_TO_STATUS[tone]} message={message} />;
}
