import type { PiiManualAddition } from "../../api/piiReview";
import { buildManualAdditionHighlights, type AnchorBoundPiiHighlightModel } from "../../lib/piiHighlights";
import { PiiTextViewer } from "./PiiTextViewer";

// Layout-Text is deactivated from the review UI (see roadmap): the raw and canonical reading views
// cover the first-draft need, and dropping it removes a whole class of projection edge cases. The
// backend still produces layout data; it is simply no longer surfaced here.
export type ReviewTextMode = "reading" | "raw";

interface ReviewTextViewerProps {
  rawText: string;
  readingText?: string | null;
  highlightModel: AnchorBoundPiiHighlightModel;
  mode: ReviewTextMode;
  onModeChange: (mode: ReviewTextMode) => void;
  devMode?: boolean;
  /** Forwarded to the highlighted text view: when false, hover metadata is suppressed. */
  showEntityMeta?: boolean;
  /** Called when a highlighted span is clicked (with the mark element, e.g. to anchor a popover),
   *  so the caller can reveal its entity group or open an in-place decision. */
  onSelectEntity?: (entityId: string, element: HTMLElement) => void;
  /** Reviewer-added spans (PII L14 / Review L10, ADR-0035), merged into the highlight display only
   *  — never touching the backend anchor-bound entity contract. */
  manualAdditions?: readonly PiiManualAddition[];
  /** Called with character offsets on a text selection; only wired into the canonical reading-text
   *  view (ADR-0035: canonical-text offsets only). */
  onTextSelected?: (offsets: { start: number; end: number }) => void;
}

const MODE_BUTTON_BASE = "rounded-md px-3 py-1.5 text-xs font-medium transition-colors";

export function ReviewTextViewer({
  rawText,
  readingText,
  highlightModel,
  mode,
  onModeChange,
  devMode = false,
  showEntityMeta = true,
  onSelectEntity,
  manualAdditions = [],
  onTextSelected,
}: ReviewTextViewerProps) {
  const hasReadingText = readingText != null;
  const activeMode: ReviewTextMode =
    mode === "reading" && hasReadingText ? "reading" : "raw";
  const manualAdditionHighlights = buildManualAdditionHighlights(manualAdditions);
  const rawHighlights = [...highlightModel.byView.technical_raw_text, ...manualAdditionHighlights.raw];
  const readingHighlights = [
    ...highlightModel.byView.canonical_reading_text,
    ...manualAdditionHighlights.canonical,
  ];
  const hasMissingCanonicalMapping =
    highlightModel.summary.missing_canonical_count > 0 ||
    highlightModel.summary.partial_canonical_count > 0 ||
    highlightModel.summary.ambiguous_canonical_count > 0;
  const hasMissingAnchorBinding = highlightModel.summary.missing_binding_count > 0;
  const hasPartialOrAmbiguousBinding =
    highlightModel.summary.partial_binding_count > 0 ||
    highlightModel.summary.ambiguous_binding_count > 0;
  const hasEvidenceOnlyFallback = highlightModel.summary.evidence_only_count > 0;

  return (
    <section className="min-w-0" aria-labelledby="text-viewer-heading">
      {/* Toolbar: title + display-mode toggle. Sticky so the mode switch stays reachable while the
          full-height paper below scrolls with the page (no nested scroll container). */}
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 bg-card py-2">
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
              {devMode ? "Kanonischer Lesetext" : "Lesetext"}
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
              {devMode ? "Technischer Rohtext" : "Technische Ansicht"}
            </button>
          </div>
        )}
      </div>

      {/* Diagnostic hints about anchor binding, contract ranges, and view semantics are developer
          material: in user view a single plain-language sentence covers the one case that changes
          what the reader sees (a highlight only visible in the technical view). */}
      {devMode && activeMode === "reading" && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-accent-dark">
          Der Lesetext ist die lesefreundliche Hauptansicht. Markierungen kommen aus dem
          anchor-gebundenen Entity-Vertrag.
        </p>
      )}
      {!devMode && activeMode === "reading" && hasMissingCanonicalMapping && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Einige erkannte Stellen können in dieser Ansicht nicht markiert werden und sind nur in
          der technischen Ansicht sichtbar.
        </p>
      )}
      {devMode && activeMode === "reading" && hasMissingCanonicalMapping && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Kanonische Ranges fehlen, sind teilweise oder mehrdeutig. Fehlende Lesetext-Markierungen
          werden hier nicht geraten.
        </p>
      )}
      {devMode && hasMissingAnchorBinding && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Anchor-Bindung fehlt für einige PII-Entities. Diese Entities bleiben als Raw-Range
          sichtbar und werden nicht in andere Views geraten.
        </p>
      )}
      {devMode && hasPartialOrAmbiguousBinding && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Anchor-Bindung ist teilweise oder mehrdeutig. Der Backend-Vertrag markiert diese
          Zuordnung explizit.
        </p>
      )}
      {devMode && hasEvidenceOnlyFallback && (
        <p className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink">
          Evidence-only Fallback ist aktiv, wenn keine verlässliche Anchor-Identität vorliegt.
        </p>
      )}

      {/* Paper: a centered A4-width sheet that grows with its content and scrolls with the page —
          deliberately no fixed-height inner scroll container (that read like an embedded iframe:
          its own scrollbar, a cut-off sheet). Jump-to-entity scrolls the page itself. */}
      <div className="mt-3">
        <div className="mx-auto max-w-[210mm] rounded-md border border-card-border bg-card px-6 py-8 shadow-[0_1px_3px_rgba(17,24,39,0.08),0_16px_40px_rgba(17,24,39,0.10)] sm:px-10 sm:py-12">
          {activeMode === "reading" ? (
            readingText ? (
              <PiiTextViewer
                text={readingText}
                highlights={readingHighlights}
                showEntityMeta={showEntityMeta}
                onSelectEntity={onSelectEntity}
                onTextSelected={onTextSelected}
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
