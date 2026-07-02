import type { PiiEntity } from "../../api/workstations";
import { buildHighlightSegments } from "../../lib/piiHighlights";

interface PiiTextViewerProps {
  text: string;
  entities: readonly PiiEntity[];
  /**
   * When false, the per-entity hover tooltip (entity type + score) is suppressed. Highlights and
   * offsets are unchanged; this only hides the technical metadata exposed on hover in user view.
   */
  showEntityMeta?: boolean;
}

const ENTITY_STYLES: Record<string, string> = {
  PERSON: "bg-amber-200 text-amber-950",
  EMAIL_ADDRESS: "bg-sky-200 text-sky-950",
  PHONE_NUMBER: "bg-violet-200 text-violet-950",
  LOCATION: "bg-emerald-200 text-emerald-950",
  ORGANIZATION: "bg-orange-200 text-orange-950",
  DATE_TIME: "bg-pink-200 text-pink-950",
};

export function PiiTextViewer({ text, entities, showEntityMeta = true }: PiiTextViewerProps) {
  const segments = buildHighlightSegments(text, entities);

  return (
    <div className="whitespace-pre-wrap break-words font-mono text-sm leading-7 text-ink">
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <span key={`text-${index}`}>{segment.text}</span>
        ) : (
          <mark
            key={`entity-${segment.entity.id}`}
            id={`pii-mark-${segment.entity.id}`}
            className={`scroll-mt-16 rounded px-0.5 ${ENTITY_STYLES[segment.entity.entity_type] ?? "bg-gray-200 text-gray-950"}`}
            title={
              showEntityMeta
                ? `${segment.entity.entity_type} · ${(segment.entity.score * 100).toFixed(0)} %`
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
