import type { PiiEntity } from "../../api/workstations";
import { PiiTextViewer } from "./PiiTextViewer";

export type ReviewTextMode = "canonical" | "layout";

interface ReviewTextViewerProps {
  canonicalText: string;
  layoutText?: string | null;
  entities: readonly PiiEntity[];
  mode: ReviewTextMode;
  onModeChange: (mode: ReviewTextMode) => void;
  /** Forwarded to the highlighted text view: when false, hover metadata is suppressed. */
  showEntityMeta?: boolean;
}

const MODE_BUTTON_BASE = "rounded-md px-3 py-1.5 text-xs font-medium transition-colors";

export function ReviewTextViewer({
  canonicalText,
  layoutText,
  entities,
  mode,
  onModeChange,
  showEntityMeta = true,
}: ReviewTextViewerProps) {
  const hasLayoutText = layoutText != null;
  const activeMode = hasLayoutText && mode === "layout" ? "layout" : "canonical";

  return (
    <section className="min-w-0" aria-labelledby="text-viewer-heading">
      {/* Toolbar: title + display-mode toggle, kept compact directly above the paper page. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="text-viewer-heading" className="font-semibold text-ink">
          Extrahierter Text
        </h2>
        {hasLayoutText && (
          <div
            className="flex rounded-lg border border-card-border bg-dropzone p-1"
            role="group"
            aria-label="Textanzeige"
          >
            <button
              type="button"
              onClick={() => onModeChange("canonical")}
              aria-pressed={activeMode === "canonical"}
              className={`${MODE_BUTTON_BASE} ${
                activeMode === "canonical"
                  ? "bg-card text-ink shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              Canonical text
            </button>
            <button
              type="button"
              onClick={() => onModeChange("layout")}
              aria-pressed={activeMode === "layout"}
              className={`${MODE_BUTTON_BASE} ${
                activeMode === "layout"
                  ? "bg-card text-ink shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              Layout text
            </button>
          </div>
        )}
      </div>

      {activeMode === "layout" && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-accent-dark">
          Layout text is for reading/review only. PII highlights use canonical text.
        </p>
      )}

      {/* Workspace: a subtle desk-like surface. The scroll lives here (unchanged from before) so
          jump-to-entity keeps scrolling the highlighted mark into view. */}
      <div className="mt-3 max-h-[70vh] overflow-auto rounded-xl bg-dropzone p-4 sm:p-6">
        {/* Paper: a centered A4-width sheet so the review reads like a document page, not a raw
            debug panel. It never spans the full workspace width. */}
        <div className="mx-auto max-w-[210mm] rounded-sm border border-card-border bg-card px-6 py-8 shadow-[0_1px_2px_rgba(17,24,39,0.06),0_12px_32px_rgba(17,24,39,0.08)] sm:px-10 sm:py-12">
          {activeMode === "layout" ? (
            layoutText ? (
              <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-7 text-ink">
                {layoutText}
              </pre>
            ) : (
              <p className="text-sm text-muted">Der Layout-Text ist leer.</p>
            )
          ) : canonicalText ? (
            <PiiTextViewer text={canonicalText} entities={entities} showEntityMeta={showEntityMeta} />
          ) : (
            <p className="text-sm text-muted">Der extrahierte Text ist leer.</p>
          )}
        </div>
      </div>
    </section>
  );
}
