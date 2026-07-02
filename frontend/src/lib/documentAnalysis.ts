// User-facing analysis flow: runs the three synchronous stations (Audit → OCR/Text → PII) in
// lineage order using the existing endpoints. This is a thin frontend orchestration — there is no
// backend pipeline endpoint and no artifact IDs are constructed here; each station is awaited so
// the backend sees the freshly created input artifact for the next step and stays authoritative
// over lineage validation.

import {
  runAudit,
  runOcr,
  runPii,
  type AuditArtifact,
  type PiiArtifact,
  type TextArtifact,
} from "../api/workstations";

export type AnalysisStep = "idle" | "audit" | "ocr" | "pii" | "done";

/** The steps during which the flow is actively running (button disabled, progress shown). */
export const ANALYSIS_RUNNING_STEPS = ["audit", "ocr", "pii"] as const;

export function isAnalysisRunning(step: AnalysisStep): boolean {
  return step === "audit" || step === "ocr" || step === "pii";
}

export interface AnalysisHandlers {
  /** Called before each station starts, and with "done" once all three succeed. */
  onStep: (step: AnalysisStep) => void;
  onAudit: (audit: AuditArtifact) => void;
  onText: (text: TextArtifact) => void;
  onPii: (pii: PiiArtifact) => void;
}

/**
 * Runs Audit, then OCR/Text, then PII, applying each returned artifact via the handlers as soon as
 * it arrives. Because results are applied incrementally, a later failure preserves the earlier
 * successful results. The first station failure is rethrown so the caller can surface a safe
 * message and stop; nothing is retried automatically.
 */
export async function runDocumentAnalysis(
  documentId: string,
  handlers: AnalysisHandlers,
): Promise<void> {
  handlers.onStep("audit");
  handlers.onAudit(await runAudit(documentId));

  handlers.onStep("ocr");
  handlers.onText(await runOcr(documentId));

  handlers.onStep("pii");
  handlers.onPii(await runPii(documentId));

  handlers.onStep("done");
}
