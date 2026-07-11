import { useRef } from "react";

import { reviewStatusLabel } from "../../api/piiReview";
import { entityTypeLabel } from "../../lib/entityTypeLabels";
import {
  buildAnchorBoundHighlightSegments,
  invalidAnchorBoundHighlights,
  type AnchorBoundPiiHighlight,
} from "../../lib/piiHighlights";
import { getCharacterOffsetsFromSelection } from "../../lib/textSelection";

interface PiiTextViewerProps {
  text: string;
  highlights: readonly AnchorBoundPiiHighlight[];
  /**
   * When false, the technical per-entity hover tooltip (type enum, score, reason codes) is
   * replaced by a plain-language one (German label + review status). Highlights and offsets are
   * unchanged; this only switches the metadata exposed on hover in user view.
   */
  showEntityMeta?: boolean;
  /** Called when a highlighted span is clicked, with the clicked mark element so the caller can
   *  anchor a popover to it. */
  onSelectEntity?: (entityId: string, element: HTMLElement) => void;
  /** Called with character offsets when the reader selects a non-empty span of this text (PII L14 /
   *  Review L10, ADR-0035). Only meaningful in the canonical reading-text view — the caller decides
   *  whether to wire this in for a given mode. */
  onTextSelected?: (offsets: { start: number; end: number }) => void;
}

const ENTITY_STYLES: Record<string, string> = {
  PERSON: "bg-amber-200 text-amber-950",
  EMAIL_ADDRESS: "bg-sky-200 text-sky-950",
  PHONE_NUMBER: "bg-violet-200 text-violet-950",
  LOCATION: "bg-emerald-200 text-emerald-950",
  ORGANIZATION: "bg-orange-200 text-orange-950",
  DATE_TIME: "bg-pink-200 text-pink-950",
  ADDRESS: "bg-teal-200 text-teal-950",
  IBAN_CODE: "bg-indigo-200 text-indigo-950",
  BIC: "bg-indigo-200 text-indigo-950",
  URL: "bg-cyan-200 text-cyan-950",
};

// A manually added span (PII L14 / Review L10, ADR-0035) stays visually distinct from a machine
// detection while it is still pseudonymize-bound; once kept/rejected it uses the same state look
// as every other entity so one visual language describes the decision, not the origin.
const MANUAL_ADDITION_MODIFIER = "ring-2 ring-inset ring-sky-500";

/**
 * The three review states share one visual language across all views:
 * - accepted (default, will be pseudonymized): colored highlight per entity type
 * - kept (explicitly not pseudonymized): no fill, solid frame — still visibly "something",
 *   still clickable to revise
 * - rejected (not PII / false positive): no fill, dashed muted frame — visibly dismissed,
 *   still clickable to revise
 */
function highlightStateClasses(highlight: AnchorBoundPiiHighlight): string {
  if (highlight.review_state === "rejected") {
    // A ring (box-shadow) cannot be dashed, so the dismissed state draws its frame via outline.
    return "bg-transparent text-muted [outline:1.5px_dashed_#a8b0a4] [outline-offset:-1.5px]";
  }
  if (highlight.review_state === "kept") {
    return "bg-transparent text-ink ring-1 ring-inset ring-slate-400";
  }
  const colored = ENTITY_STYLES[highlight.entity_type] ?? "bg-gray-200 text-gray-950";
  const needsReview = highlight.needs_review ? " ring-1 ring-inset ring-red-400" : "";
  const manual = highlight.origin === "human" ? ` ${MANUAL_ADDITION_MODIFIER}` : "";
  return `${colored}${needsReview}${manual}`;
}

function technicalTooltip(segment: {
  highlight: AnchorBoundPiiHighlight;
  highlights: AnchorBoundPiiHighlight[];
}): string {
  return (
    `${segment.highlight.entity_type} · ${(segment.highlight.confidence * 100).toFixed(0)} %` +
    ` · ${reviewStatusLabel(segment.highlight.review_state)}` +
    (segment.highlights.length > 1 ? ` · ${segment.highlights.length} überlappende Entities` : "") +
    (segment.highlight.origin === "human" ? " · Manuell hinzugefügt" : "") +
    (segment.highlight.reason_codes.length > 0
      ? ` · ${segment.highlight.reason_codes.join(", ")}`
      : "")
  );
}

function plainTooltip(highlight: AnchorBoundPiiHighlight, clickable: boolean): string {
  return (
    `${entityTypeLabel(highlight.entity_type)} · ${reviewStatusLabel(highlight.review_state)}` +
    (clickable ? " · Klicken zum Ändern" : "")
  );
}

export function PiiTextViewer({
  text,
  highlights,
  showEntityMeta = true,
  onSelectEntity,
  onTextSelected,
}: PiiTextViewerProps) {
  const segments = buildAnchorBoundHighlightSegments(text, highlights);
  const invalidHighlightCount = invalidAnchorBoundHighlights(text, highlights).length;
  const containerRef = useRef<HTMLDivElement>(null);
  // One highlight can span several segments when other highlights overlap it; the jump-target DOM
  // id must still exist exactly once, on the first segment it leads.
  const markIdBySegmentStart = new Map<number, string>();
  const markIdsAssigned = new Set<string>();
  for (const segment of segments) {
    if (segment.kind === "entity" && !markIdsAssigned.has(segment.highlight.primary_source_entity_id)) {
      markIdsAssigned.add(segment.highlight.primary_source_entity_id);
      markIdBySegmentStart.set(segment.start, `pii-mark-${segment.highlight.primary_source_entity_id}`);
    }
  }

  function handleMouseUp() {
    if (!onTextSelected || !containerRef.current) {
      return;
    }
    const selection = window.getSelection();
    if (!selection) {
      return;
    }
    const offsets = getCharacterOffsetsFromSelection(containerRef.current, selection);
    if (offsets) {
      onTextSelected(offsets);
    }
  }

  return (
    <>
      {invalidHighlightCount > 0 && (
        // Out-of-range highlights are never rendered (the text buffer must stay uncorrupted), but
        // dropping them silently would hide a real contract/state defect — say so explicitly.
        <p
          data-testid="pii-invalid-highlight-notice"
          className="mb-3 rounded-lg bg-accent-soft px-3 py-2 text-xs text-ink"
        >
          {invalidHighlightCount} Markierung(en) passen nicht zum angezeigten Text und werden
          nicht dargestellt.
        </p>
      )}
      <div
        ref={containerRef}
        data-testid="pii-text-content"
        onMouseUp={onTextSelected ? handleMouseUp : undefined}
        className="whitespace-pre-wrap break-words text-[15px] leading-8 text-ink"
      >
        {/* Segments partition the source text exactly, so `segment.start` is unique among siblings
            and stable as a key. Never key on the highlight's own range: a highlight split by an
            overlapping one repeats its range across segments, and duplicate keys corrupt the
            rendered text during reconciliation. */}
        {segments.map((segment) =>
          segment.kind === "text" ? (
            <span key={`seg-${segment.start}`}>{segment.text}</span>
          ) : (
            <mark
              key={`seg-${segment.start}`}
              id={markIdBySegmentStart.get(segment.start)}
              data-entity-id={segment.highlight.entity_id}
              data-entity-ids={segment.highlights.map((highlight) => highlight.entity_id).join(" ")}
              data-source-name={segment.highlight.source_name}
              data-review-state={segment.highlight.review_state}
              onClick={
                onSelectEntity
                  ? (event) =>
                      onSelectEntity(segment.highlight.primary_source_entity_id, event.currentTarget)
                  : undefined
              }
              className={`scroll-mt-16 rounded px-0.5 ${onSelectEntity ? "cursor-pointer" : ""} ${highlightStateClasses(segment.highlight)}`}
              title={
                showEntityMeta
                  ? technicalTooltip(segment)
                  : plainTooltip(segment.highlight, onSelectEntity != null)
              }
            >
              {segment.text}
            </mark>
          ),
        )}
      </div>
    </>
  );
}
