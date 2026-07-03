import { StatusNotice } from "./StatusNotice";
import { isAnalysisRunning, type AnalysisStep } from "../lib/documentAnalysis";

interface AnalysisError {
  message: string;
  correlationId: string | null;
}

interface DocumentAnalysisPanelProps {
  step: AnalysisStep;
  /** When true the button offers a re-run; otherwise it offers the first analysis. */
  hasCurrentAnalysis: boolean;
  /** Safe, already-mapped error message (never raw document text or raw PII). */
  error: AnalysisError | null;
  /** Proactive hint when a station's runtime is not installed on this server (see buildRuntimeNotice). */
  runtimeNotice?: string | null;
  onRun: () => void;
}

// User-facing progress labels; deliberately non-technical (no station/endpoint names).
const STEP_LABEL: Record<"audit" | "ocr" | "pii", string> = {
  audit: "Dokument wird vorbereitet …",
  ocr: "Text wird extrahiert …",
  pii: "Sensible Daten werden erkannt …",
};

/**
 * The single product-facing analysis action for the user view. It runs the existing Audit/OCR/PII
 * stations in order (see runDocumentAnalysis) so non-dev users are not left at a dead end. The dev
 * view keeps its separate per-station controls and does not render this panel.
 */
export function DocumentAnalysisPanel({
  step,
  hasCurrentAnalysis,
  error,
  runtimeNotice,
  onRun,
}: DocumentAnalysisPanelProps) {
  const running = isAnalysisRunning(step);
  const buttonLabel = hasCurrentAnalysis ? "Analyse erneut ausführen" : "Dokument analysieren";

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          aria-busy={running}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "Analyse läuft …" : buttonLabel}
        </button>
      </div>
      {running && (
        <StatusNotice status="uploading" message={STEP_LABEL[step as "audit" | "ocr" | "pii"]} />
      )}
      {!running && error && (
        <StatusNotice status="error" message={error.message} correlationId={error.correlationId} />
      )}
      {!running && !error && runtimeNotice && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {runtimeNotice}
        </p>
      )}
    </div>
  );
}
