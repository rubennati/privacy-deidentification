import type { PiiEntity } from "../api/workstations";
import type { PiiReviewStatus } from "../api/piiReview";

export type HighlightSegment =
  | { kind: "text"; text: string }
  | { kind: "entity"; text: string; entity: PiiEntity; reviewStatus?: PiiReviewStatus };

/**
 * Build safe React-renderable segments from Python Unicode-codepoint offsets.
 *
 * When `reviewStatusByOccurrenceId` is given, an entity resolved to `"rejected"` (false positive)
 * is excluded entirely — it is no longer an active highlight once a reviewer rejects it. Every
 * other resolved status is attached to its segment so the caller can style it distinctly
 * (e.g. "ignored"/"accepted" vs. the default "pending" look); entities with no resolved status
 * (no review data loaded, or a legacy/malformed response) render exactly as before.
 */
export function buildHighlightSegments(
  text: string,
  entities: readonly PiiEntity[],
  reviewStatusByOccurrenceId?: Record<string, PiiReviewStatus>,
): HighlightSegment[] {
  const codePoints = Array.from(text);
  const valid = entities
    .filter((entity) => isValidEntity(codePoints, entity))
    .filter((entity) => reviewStatusByOccurrenceId?.[entity.id] !== "rejected");
  const ranked = [...valid].sort(comparePriority);
  const accepted: PiiEntity[] = [];

  for (const candidate of ranked) {
    const overlaps = accepted.some(
      (entity) =>
        candidate.start_offset < entity.end_offset && candidate.end_offset > entity.start_offset,
    );
    if (!overlaps) {
      accepted.push(candidate);
    }
  }

  accepted.sort(comparePosition);
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const entity of accepted) {
    if (entity.start_offset > cursor) {
      segments.push({ kind: "text", text: codePoints.slice(cursor, entity.start_offset).join("") });
    }
    segments.push({
      kind: "entity",
      text: codePoints.slice(entity.start_offset, entity.end_offset).join(""),
      entity,
      reviewStatus: reviewStatusByOccurrenceId?.[entity.id],
    });
    cursor = entity.end_offset;
  }
  if (cursor < codePoints.length) {
    segments.push({ kind: "text", text: codePoints.slice(cursor).join("") });
  }
  return segments;
}

function isValidEntity(codePoints: string[], entity: PiiEntity): boolean {
  if (
    !Number.isInteger(entity.start_offset) ||
    !Number.isInteger(entity.end_offset) ||
    entity.start_offset < 0 ||
    entity.end_offset <= entity.start_offset ||
    entity.end_offset > codePoints.length
  ) {
    return false;
  }
  return codePoints.slice(entity.start_offset, entity.end_offset).join("") === entity.text;
}

function comparePriority(left: PiiEntity, right: PiiEntity): number {
  return (
    right.score - left.score ||
    right.end_offset - right.start_offset - (left.end_offset - left.start_offset) ||
    left.start_offset - right.start_offset ||
    compareText(left.entity_type, right.entity_type) ||
    compareText(left.id, right.id)
  );
}

function comparePosition(left: PiiEntity, right: PiiEntity): number {
  return (
    left.start_offset - right.start_offset ||
    left.end_offset - right.end_offset ||
    compareText(left.entity_type, right.entity_type) ||
    compareText(left.id, right.id)
  );
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
