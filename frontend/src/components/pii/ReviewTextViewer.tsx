import type { PiiEntity } from "../../api/workstations";
import type { PiiReviewStatus } from "../../api/piiReview";
import { PiiTextViewer } from "./PiiTextViewer";

export type ReviewTextMode = "reading" | "raw" | "layout";

interface ReviewTextViewerProps {
  rawText: string;
  readingText?: string | null;
  layoutText?: string | null;
  entities: readonly PiiEntity[];
  mode: ReviewTextMode;
  onModeChange: (mode: ReviewTextMode) => void;
  devMode?: boolean;
  /** Forwarded to the highlighted text view: when false, hover metadata is suppressed. */
  showEntityMeta?: boolean;
  /** Resolved review status per occurrence id, respected in both raw and reading mode. */
  reviewStatusByOccurrenceId?: Record<string, PiiReviewStatus>;
  /** Called when a highlighted span is clicked, so the caller can reveal its entity group. */
  onSelectEntity?: (entityId: string) => void;
}

const MODE_BUTTON_BASE = "rounded-md px-3 py-1.5 text-xs font-medium transition-colors";

export function ReviewTextViewer({
  rawText,
  readingText,
  layoutText,
  entities,
  mode,
  onModeChange,
  devMode = false,
  showEntityMeta = true,
  reviewStatusByOccurrenceId,
  onSelectEntity,
}: ReviewTextViewerProps) {
  const hasReadingText = readingText != null;
  const hasLayoutText = layoutText != null;
  const activeMode: ReviewTextMode =
    mode === "layout" && hasLayoutText
      ? "layout"
      : mode === "reading" && hasReadingText
        ? "reading"
        : "raw";
  const projectedEntities =
    readingText == null
      ? []
      : entities.flatMap((entity) => {
          const start = entity.reading_start_offset;
          const end = entity.reading_end_offset;
          if (
            entity.projection_status !== "exact" ||
            start == null ||
            end == null ||
            start < 0 ||
            end <= start ||
            end > Array.from(readingText).length
          ) {
            return [];
          }
          return [
            {
              ...entity,
              text: Array.from(readingText).slice(start, end).join(""),
              start_offset: start,
              end_offset: end,
            },
          ];
        });
  const hasRawOnlyEntities = entities.some((entity) => entity.projection_status !== "exact");

  return (
    <section className="min-w-0" aria-labelledby="text-viewer-heading">
      {/* Toolbar: title + display-mode toggle, kept compact directly above the paper page. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="text-viewer-heading" className="font-semibold text-ink">
          Extrahierter Text
        </h2>
        {(devMode || hasReadingText) && (
          <div
            className="flex rounded-lg border border-card-border bg-dropzone p-1"
            role="group"
            aria-label="Textanzeige"
          >
            <button
              type="button"
              onClick={() => onModeChange("reading")}
              aria-pressed={activeMode === "reading"}
              disabled={!hasReadingText}
              className={`${MODE_BUTTON_BASE} ${
                activeMode === "reading"
                  ? "bg-card text-ink shadow-sm"
                  : "text-muted hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              }`}
            >
              Kanonischer Lesetext
            </button>
            <button
              type="button"
              onClick={() => onModeChange("raw")}
              aria-pressed={activeMode === "raw"}
              className={`${MODE_BUTTON_BASE} ${
                activeMode === "raw"
                  ? "bg-card text-ink shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
            >
              Technischer Rohtext
            </button>
            {devMode && (
              <button
                type="button"
                onClick={() => onModeChange("layout")}
                aria-pressed={activeMode === "layout"}
                disabled={!hasLayoutText}
                className={`${MODE_BUTTON_BASE} ${
                  activeMode === "layout"
                    ? "bg-card text-ink shadow-sm"
                    : "text-muted hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
                }`}
              >
                Layout-Text
              </button>
            )}
          </div>
        )}
      </div>

      {activeMode !== "raw" && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-accent-dark">
          {activeMode === "reading"
            ? devMode
              ? "Der Lesetext ist die lesefreundliche Hauptansicht. Markierungen verwenden sicher projizierte Lesetext-Offsets."
              : "Der Lesetext ist die lesefreundliche Hauptansicht."
            : "Der Layout-Text dient der Orientierung. PII-Markierungen verwenden derzeit den technischen Rohtext."}
        </p>
      )}
      {activeMode === "reading" && hasRawOnlyEntities && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Einige PII-Markierungen sind nur im technischen Rohtext sichtbar.
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
          ) : activeMode === "reading" ? (
            readingText ? (
              <PiiTextViewer
                text={readingText}
                entities={projectedEntities}
                showEntityMeta={showEntityMeta}
                reviewStatusByOccurrenceId={reviewStatusByOccurrenceId}
                onSelectEntity={onSelectEntity}
              />
            ) : (
              <p className="text-sm text-muted">Der kanonische Lesetext ist leer.</p>
            )
          ) : rawText ? (
            <PiiTextViewer
              text={rawText}
              entities={entities}
              showEntityMeta={showEntityMeta}
              reviewStatusByOccurrenceId={reviewStatusByOccurrenceId}
              onSelectEntity={onSelectEntity}
            />
          ) : (
            <p className="text-sm text-muted">Der technische Rohtext ist leer.</p>
          )}
        </div>
      </div>
    </section>
  );
}
