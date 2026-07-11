import { useRef } from "react";

import { reviewStatusLabel, type PiiReviewStatus } from "../../api/piiReview";
import {
  buildAnchorBoundHighlightSegments,
  type AnchorBoundPiiHighlight,
} from "../../lib/piiHighlights";
import { getCharacterOffsetsFromSelection } from "../../lib/textSelection";

interface PiiTextViewerProps {
  text: string;
  highlights: readonly AnchorBoundPiiHighlight[];
  /**
   * When false, the per-entity hover tooltip (entity type + score) is suppressed. Highlights and
   * offsets are unchanged; this only hides the technical metadata exposed on hover in user view.
   */
  showEntityMeta?: boolean;
  /** Called when a highlighted span is clicked, so the caller can reveal its entity group. */
  onSelectEntity?: (entityId: string) => void;
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
};

// "accepted" (pseudonymize, the default) looks like a normal highlight — it is the expected case
// for nearly every entity, so it gets no extra modifier. "kept" (explicitly opted out of
// pseudonymization) stays visually distinguishable. Rejected entities never reach this component
// (filtered out upstream).
const REVIEW_STATUS_MODIFIERS: Partial<Record<PiiReviewStatus, string>> = {
  kept: "opacity-60 [text-decoration:underline] decoration-dashed",
};

// A manually added span (PII L14 / Review L10, ADR-0035) stays visually distinct from a machine
// detection, composable with the review-status modifiers above.
const MANUAL_ADDITION_MODIFIER = "ring-2 ring-inset ring-sky-500";

export function PiiTextViewer({
  text,
  highlights,
  showEntityMeta = true,
  onSelectEntity,
  onTextSelected,
}: PiiTextViewerProps) {
  const segments = buildAnchorBoundHighlightSegments(text, highlights);
  const containerRef = useRef<HTMLDivElement>(null);

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
    <div
      ref={containerRef}
      onMouseUp={onTextSelected ? handleMouseUp : undefined}
      className="whitespace-pre-wrap break-words text-[15px] leading-8 text-ink"
    >
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <span key={`text-${index}`}>{segment.text}</span>
        ) : (
          <mark
            key={`entity-${segment.highlight.entity_id}-${segment.highlight.source_name}-${segment.highlight.start}`}
            id={`pii-mark-${segment.highlight.primary_source_entity_id}`}
            data-entity-id={segment.highlight.entity_id}
            data-source-name={segment.highlight.source_name}
            onClick={
              onSelectEntity
                ? () => onSelectEntity(segment.highlight.primary_source_entity_id)
                : undefined
            }
            className={`scroll-mt-16 rounded px-0.5 ${onSelectEntity ? "cursor-pointer" : ""} ${
              ENTITY_STYLES[segment.highlight.entity_type] ?? "bg-gray-200 text-gray-950"
            } ${
              segment.highlight.needs_review ? "ring-1 ring-inset ring-red-400" : ""
            } ${
              REVIEW_STATUS_MODIFIERS[segment.highlight.review_state] ?? ""
            } ${
              segment.highlight.origin === "human" ? MANUAL_ADDITION_MODIFIER : ""
            }`}
            title={
              showEntityMeta
                ? `${segment.highlight.entity_type} · ${(segment.highlight.confidence * 100).toFixed(0)} %` +
                  ` · ${reviewStatusLabel(segment.highlight.review_state)}` +
                  (segment.highlight.origin === "human" ? " · Manuell hinzugefügt" : "") +
                  (segment.highlight.reason_codes.length > 0
                    ? ` · ${segment.highlight.reason_codes.join(", ")}`
                    : "")
                : undefined
            }
          >
            {segment.text}
          </mark>
        ),
      )}
    </div>
  );
}
