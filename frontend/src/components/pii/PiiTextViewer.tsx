import type { PiiEntity } from "../../api/workstations";
import { reviewStatusLabel, type PiiReviewStatus } from "../../api/piiReview";
import { buildHighlightSegments } from "../../lib/piiHighlights";

interface PiiTextViewerProps {
  text: string;
  entities: readonly PiiEntity[];
  /**
   * When false, the per-entity hover tooltip (entity type + score) is suppressed. Highlights and
   * offsets are unchanged; this only hides the technical metadata exposed on hover in user view.
   */
  showEntityMeta?: boolean;
  /** Resolved review status per occurrence id. A rejected (false-positive) entity is never
   *  highlighted; a kept (opted out of pseudonymization) entity renders with a distinguishable
   *  style; the default/accepted (pseudonymize) case looks like a normal highlight. Omitted
   *  entirely when no review data has loaded, in which case every entity renders with its default
   *  look. */
  reviewStatusByOccurrenceId?: Record<string, PiiReviewStatus>;
  /** Called when a highlighted span is clicked, so the caller can reveal its entity group. */
  onSelectEntity?: (entityId: string) => void;
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

export function PiiTextViewer({
  text,
  entities,
  showEntityMeta = true,
  reviewStatusByOccurrenceId,
  onSelectEntity,
}: PiiTextViewerProps) {
  const segments = buildHighlightSegments(text, entities, reviewStatusByOccurrenceId);

  return (
    <div className="whitespace-pre-wrap break-words text-[15px] leading-8 text-ink">
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <span key={`text-${index}`}>{segment.text}</span>
        ) : (
          <mark
            key={`entity-${segment.entity.id}`}
            id={`pii-mark-${segment.entity.id}`}
            onClick={onSelectEntity ? () => onSelectEntity(segment.entity.id) : undefined}
            className={`scroll-mt-16 rounded px-0.5 ${onSelectEntity ? "cursor-pointer" : ""} ${
              ENTITY_STYLES[segment.entity.entity_type] ?? "bg-gray-200 text-gray-950"
            } ${segment.reviewStatus ? (REVIEW_STATUS_MODIFIERS[segment.reviewStatus] ?? "") : ""}`}
            title={
              showEntityMeta
                ? `${segment.entity.entity_type} · ${(segment.entity.score * 100).toFixed(0)} %` +
                  (segment.reviewStatus ? ` · ${reviewStatusLabel(segment.reviewStatus)}` : "")
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
