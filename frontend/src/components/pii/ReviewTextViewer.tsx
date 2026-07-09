import type { AnchorBoundPiiHighlightModel } from "../../lib/piiHighlights";
import { PiiTextViewer } from "./PiiTextViewer";

export type ReviewTextMode = "reading" | "raw" | "layout";

interface ReviewTextViewerProps {
  rawText: string;
  readingText?: string | null;
  layoutText?: string | null;
  highlightModel: AnchorBoundPiiHighlightModel;
  mode: ReviewTextMode;
  onModeChange: (mode: ReviewTextMode) => void;
  devMode?: boolean;
  /** Forwarded to the highlighted text view: when false, hover metadata is suppressed. */
  showEntityMeta?: boolean;
  /** Called when a highlighted span is clicked, so the caller can reveal its entity group. */
  onSelectEntity?: (entityId: string) => void;
}

const MODE_BUTTON_BASE = "rounded-md px-3 py-1.5 text-xs font-medium transition-colors";

export function ReviewTextViewer({
  rawText,
  readingText,
  layoutText,
  highlightModel,
  mode,
  onModeChange,
  devMode = false,
  showEntityMeta = true,
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
  const rawHighlights = highlightModel.byView.technical_raw_text;
  const readingHighlights = highlightModel.byView.canonical_reading_text;
  const layoutHighlights = highlightModel.byView.layout_text;
  const hasMissingCanonicalMapping =
    highlightModel.summary.missing_canonical_count > 0 ||
    highlightModel.summary.partial_canonical_count > 0 ||
    highlightModel.summary.ambiguous_canonical_count > 0;
  const hasMissingAnchorBinding = highlightModel.summary.missing_binding_count > 0;
  const hasPartialOrAmbiguousBinding =
    highlightModel.summary.partial_binding_count > 0 ||
    highlightModel.summary.ambiguous_binding_count > 0;
  const hasEvidenceOnlyFallback = highlightModel.summary.evidence_only_count > 0;
  const hasMissingLayoutRanges = highlightModel.summary.missing_layout_count > 0;

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
              ? "Der Lesetext ist die lesefreundliche Hauptansicht. Markierungen kommen aus dem anchor-gebundenen Entity-Vertrag."
              : "Der Lesetext ist die lesefreundliche Hauptansicht."
            : layoutHighlights.length > 0
              ? "Der Layout-Text dient der Orientierung. Markierungen erscheinen nur, wenn der Entity-Vertrag Layout-Ranges liefert."
              : "Der Layout-Text dient der Orientierung. Für diese Entities liefert der Vertrag keine Layout-Ranges."}
        </p>
      )}
      {activeMode === "reading" && hasMissingCanonicalMapping && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Kanonische Ranges fehlen, sind teilweise oder mehrdeutig. Fehlende Lesetext-Markierungen
          werden hier nicht geraten.
        </p>
      )}
      {activeMode === "layout" && hasMissingLayoutRanges && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Layout-Ranges fehlen oder sind nicht verfügbar. Der Vertrag liefert nur markierbare
          Layout-Ranges, wenn die Anchor-Zuordnung sicher ist.
        </p>
      )}
      {hasMissingAnchorBinding && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Anchor-Bindung fehlt fuer einige PII-Entities. Diese Entities bleiben als Raw-Range
          sichtbar und werden nicht in andere Views geraten.
        </p>
      )}
      {hasPartialOrAmbiguousBinding && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Anchor-Bindung ist teilweise oder mehrdeutig. Der Backend-Vertrag markiert diese
          Zuordnung explizit.
        </p>
      )}
      {hasEvidenceOnlyFallback && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Evidence-only Fallback ist aktiv, wenn keine verlaessliche Anchor-Identitaet vorliegt.
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
              layoutHighlights.length > 0 ? (
                <PiiTextViewer
                  text={layoutText}
                  highlights={layoutHighlights}
                  showEntityMeta={showEntityMeta}
                  onSelectEntity={onSelectEntity}
                />
              ) : (
                <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-7 text-ink">
                  {layoutText}
                </pre>
              )
            ) : (
              <p className="text-sm text-muted">Der Layout-Text ist leer.</p>
            )
          ) : activeMode === "reading" ? (
            readingText ? (
              <PiiTextViewer
                text={readingText}
                highlights={readingHighlights}
                showEntityMeta={showEntityMeta}
                onSelectEntity={onSelectEntity}
              />
            ) : (
              <p className="text-sm text-muted">Der kanonische Lesetext ist leer.</p>
            )
          ) : rawText ? (
            <PiiTextViewer
              text={rawText}
              highlights={rawHighlights}
              showEntityMeta={showEntityMeta}
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
