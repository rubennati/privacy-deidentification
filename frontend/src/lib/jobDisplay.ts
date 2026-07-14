// Maps a safe `JobStatus` (ids, timestamps, sanitized error code/message only — never raw document
// text or PII) to a user-facing German label. Kept separate from `jobActivity.ts` so the polling/
// storage logic and the presentation text can be tested and changed independently.

import type { JobStatus } from "../api/workstations";

export type JobDisplayTone = "info" | "success" | "error";

export interface JobDisplayView {
  tone: JobDisplayTone;
  message: string;
}

const KIND_LABEL: Record<JobStatus["kind"], string> = {
  ocr_text: "Die Texterkennung (OCR)",
  pii_detection: "Die Erkennung sensibler Daten (PII)",
};

/** Pure, total mapping — must never throw, even for a legacy/partial job record. */
export function describeJob(job: JobStatus): JobDisplayView {
  const label = KIND_LABEL[job.kind] ?? "Die Verarbeitung";
  switch (job.status) {
    case "pending":
      return { tone: "info", message: `${label} wurde angenommen und wartet auf Verarbeitung …` };
    case "running":
      return { tone: "info", message: `${label} läuft …` };
    case "succeeded":
      return { tone: "success", message: `${label} ist abgeschlossen. Das Ergebnis wird geladen.` };
    case "failed":
      return {
        tone: "error",
        message:
          job.error_message && job.error_message !== ""
            ? job.error_message
            : `${label} ist fehlgeschlagen.`,
      };
    case "canceled":
      return { tone: "error", message: `${label} wurde abgebrochen.` };
    default:
      return { tone: "info", message: `${label}: Status wird geprüft …` };
  }
}
