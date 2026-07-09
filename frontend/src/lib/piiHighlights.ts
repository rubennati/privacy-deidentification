import type {
  PiiAnchorBindingStatus,
  PiiAnchorSourceName,
  PiiEntityContractV1,
  PiiEntityIdentityBasis,
  PiiEntityMappingStatus,
  ReviewReadyAnchorBoundPiiEntity,
} from "../api/piiEntityContract";
import type { PiiEntity } from "../api/workstations";
import type { PiiReviewStatus } from "../api/piiReview";

export type HighlightSegment =
  | { kind: "text"; text: string }
  | { kind: "entity"; text: string; entity: PiiEntity; reviewStatus?: PiiReviewStatus };

export type PiiHighlightView = "technical_raw_text" | "canonical_reading_text" | "layout_text";

export interface AnchorBoundPiiHighlight {
  entity_id: string;
  entity_type: string;
  identity_basis: PiiEntityIdentityBasis;
  source_entity_ids: string[];
  primary_source_entity_id: string;
  anchor_ids: string[];
  source_name: PiiHighlightView;
  start: number;
  end: number;
  binding_status: PiiAnchorBindingStatus;
  mapping_status: PiiEntityMappingStatus;
  review_state: PiiReviewStatus;
  needs_review: boolean;
  reason_codes: string[];
  confidence: number;
}

export type AnchorBoundHighlightSegment =
  | { kind: "text"; text: string }
  | { kind: "entity"; text: string; highlight: AnchorBoundPiiHighlight };

export interface AnchorBoundPiiHighlightsByView {
  technical_raw_text: AnchorBoundPiiHighlight[];
  canonical_reading_text: AnchorBoundPiiHighlight[];
  layout_text: AnchorBoundPiiHighlight[];
}

export interface AnchorBoundPiiHighlightSummary {
  total_entities: number;
  evidence_only_count: number;
  partial_binding_count: number;
  ambiguous_binding_count: number;
  missing_canonical_count: number;
  ambiguous_canonical_count: number;
  partial_canonical_count: number;
  missing_layout_count: number;
}

export interface AnchorBoundPiiHighlightModel {
  byView: AnchorBoundPiiHighlightsByView;
  summary: AnchorBoundPiiHighlightSummary;
}

const EMPTY_ANCHOR_BOUND_HIGHLIGHTS: AnchorBoundPiiHighlightModel = {
  byView: { technical_raw_text: [], canonical_reading_text: [], layout_text: [] },
  summary: {
    total_entities: 0,
    evidence_only_count: 0,
    partial_binding_count: 0,
    ambiguous_binding_count: 0,
    missing_canonical_count: 0,
    ambiguous_canonical_count: 0,
    partial_canonical_count: 0,
    missing_layout_count: 0,
  },
};

export function buildAnchorBoundPiiHighlights(
  contract: PiiEntityContractV1 | null | undefined,
): AnchorBoundPiiHighlightModel {
  if (!contract) {
    return EMPTY_ANCHOR_BOUND_HIGHLIGHTS;
  }

  const byView: AnchorBoundPiiHighlightsByView = {
    technical_raw_text: [],
    canonical_reading_text: [],
    layout_text: [],
  };
  const summary: AnchorBoundPiiHighlightSummary = {
    total_entities: contract.entities.length,
    evidence_only_count: 0,
    partial_binding_count: 0,
    ambiguous_binding_count: 0,
    missing_canonical_count: 0,
    ambiguous_canonical_count: 0,
    partial_canonical_count: 0,
    missing_layout_count: 0,
  };

  for (const entity of contract.entities) {
    if (entity.review_state === "rejected") {
      continue;
    }
    if (entity.identity_basis === "evidence_only") {
      summary.evidence_only_count += 1;
    }
    if (entity.binding_status === "partial") {
      summary.partial_binding_count += 1;
    } else if (entity.binding_status === "ambiguous") {
      summary.ambiguous_binding_count += 1;
    }
    if (entity.mapping_status === "missing") {
      summary.missing_canonical_count += 1;
    } else if (entity.mapping_status === "ambiguous") {
      summary.ambiguous_canonical_count += 1;
    } else if (entity.mapping_status === "partial") {
      summary.partial_canonical_count += 1;
    }

    const raw = highlightForRange(entity, "technical_raw_text", entity.display.raw_highlight_range);
    if (raw) {
      byView.technical_raw_text.push(raw);
    }

    const canonicalRange = entity.display.canonical_highlight_range;
    const canonical =
      canonicalRange == null
        ? null
        : highlightForRange(entity, "canonical_reading_text", canonicalRange);
    if (canonical) {
      byView.canonical_reading_text.push(canonical);
    }

    const layoutRanges = rangesForSource(entity, "layout_text");
    if (layoutRanges.length === 0) {
      summary.missing_layout_count += 1;
    }
    for (const range of layoutRanges) {
      const layout = highlightForRange(entity, "layout_text", range);
      if (layout) {
        byView.layout_text.push(layout);
      }
    }
  }

  for (const view of Object.keys(byView) as PiiHighlightView[]) {
    byView[view].sort(compareAnchorHighlightPosition);
  }

  return { byView, summary };
}

export const buildHighlightsFromAnchorBoundEntities = buildAnchorBoundPiiHighlights;
export const buildViewHighlightsFromEntityContract = buildAnchorBoundPiiHighlights;

export function buildAnchorBoundHighlightSegments(
  text: string,
  highlights: readonly AnchorBoundPiiHighlight[],
): AnchorBoundHighlightSegment[] {
  const codePoints = Array.from(text);
  const valid = highlights.filter((highlight) => isValidHighlight(codePoints, highlight));
  const ranked = [...valid].sort(compareAnchorHighlightPriority);
  const accepted: AnchorBoundPiiHighlight[] = [];

  for (const candidate of ranked) {
    const overlaps = accepted.some(
      (highlight) => candidate.start < highlight.end && candidate.end > highlight.start,
    );
    if (!overlaps) {
      accepted.push(candidate);
    }
  }

  accepted.sort(compareAnchorHighlightPosition);
  const segments: AnchorBoundHighlightSegment[] = [];
  let cursor = 0;
  for (const highlight of accepted) {
    if (highlight.start > cursor) {
      segments.push({ kind: "text", text: codePoints.slice(cursor, highlight.start).join("") });
    }
    segments.push({
      kind: "entity",
      text: codePoints.slice(highlight.start, highlight.end).join(""),
      highlight,
    });
    cursor = highlight.end;
  }
  if (cursor < codePoints.length) {
    segments.push({ kind: "text", text: codePoints.slice(cursor).join("") });
  }
  return segments;
}

function highlightForRange(
  entity: ReviewReadyAnchorBoundPiiEntity,
  sourceName: PiiHighlightView,
  range: { start: number; end: number },
): AnchorBoundPiiHighlight | null {
  if (!Number.isInteger(range.start) || !Number.isInteger(range.end) || range.end <= range.start) {
    return null;
  }
  const primarySourceEntityId = entity.source_entity_ids[0];
  if (!primarySourceEntityId) {
    return null;
  }
  return {
    entity_id: entity.entity_id,
    entity_type: entity.entity_type,
    identity_basis: entity.identity_basis,
    source_entity_ids: entity.source_entity_ids,
    primary_source_entity_id: primarySourceEntityId,
    anchor_ids: entity.anchor_set.anchor_ids,
    source_name: sourceName,
    start: range.start,
    end: range.end,
    binding_status: entity.binding_status,
    mapping_status: entity.mapping_status,
    review_state: entity.review_state,
    needs_review: entity.display.needs_review,
    reason_codes: entity.warnings.length > 0 ? entity.warnings : entity.display.review_reason_codes,
    confidence: entity.confidence,
  };
}

function rangesForSource(
  entity: ReviewReadyAnchorBoundPiiEntity,
  sourceName: PiiAnchorSourceName,
): Array<{ start: number; end: number }> {
  const seen = new Set<string>();
  const ranges: Array<{ start: number; end: number }> = [];
  for (const ref of entity.anchor_refs) {
    if (ref.source_name !== sourceName || ref.source_range == null) {
      continue;
    }
    const key = `${ref.source_range.start}:${ref.source_range.end}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    ranges.push({ start: ref.source_range.start, end: ref.source_range.end });
  }
  return ranges;
}

function isValidHighlight(
  codePoints: string[],
  highlight: AnchorBoundPiiHighlight,
): boolean {
  return (
    Number.isInteger(highlight.start) &&
    Number.isInteger(highlight.end) &&
    highlight.start >= 0 &&
    highlight.end <= codePoints.length &&
    highlight.end > highlight.start
  );
}

function compareAnchorHighlightPriority(
  left: AnchorBoundPiiHighlight,
  right: AnchorBoundPiiHighlight,
): number {
  return (
    right.confidence - left.confidence ||
    right.end - right.start - (left.end - left.start) ||
    left.start - right.start ||
    compareText(left.entity_type, right.entity_type) ||
    compareText(left.entity_id, right.entity_id)
  );
}

function compareAnchorHighlightPosition(
  left: AnchorBoundPiiHighlight,
  right: AnchorBoundPiiHighlight,
): number {
  return (
    left.start - right.start ||
    left.end - right.end ||
    compareText(left.entity_type, right.entity_type) ||
    compareText(left.entity_id, right.entity_id)
  );
}

/**
 * Build safe React-renderable segments from Python Unicode-codepoint offsets.
 *
 * When `reviewStatusByOccurrenceId` is given, an entity resolved to `"rejected"` (false positive)
 * is excluded entirely — it is no longer an active highlight once a reviewer rejects it. Every
 * other resolved status is attached to its segment so the caller can style it distinctly (e.g.
 * "kept" vs. the default "accepted"/pseudonymize look); entities with no resolved status (no
 * review data loaded, or a legacy/malformed response) render exactly as before.
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
