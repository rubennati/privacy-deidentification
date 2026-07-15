import type {
  PiiAnchorBindingStatus,
  PiiAnchorSourceName,
  PiiEntityContractV1,
  PiiEntityIdentityBasis,
  PiiEntityMappingStatus,
  ReviewReadyAnchorBoundPiiEntity,
} from "../api/piiEntityContract";
import type { PiiEntity } from "../api/workstations";
import type { PiiManualAddition, PiiReviewStatus } from "../api/piiReview";

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
  /** Set only for a manually added entity (PII L14 / Review L10, ADR-0035); absent for every
   *  detector-derived highlight, so `origin === "human"` is the render-time distinguishing check. */
  origin?: "human";
}

// Every segment carries its own code-point range in the source buffer. Segments always partition
// the text exactly (each code point appears in exactly one segment), so `start` is unique per
// segment and safe as a stable render key — a highlight split by an overlapping one must never
// reuse the highlight's own start as a key for both fragments (that duplicate-key reconciliation
// is what used to corrupt the rendered text).
export type AnchorBoundHighlightSegment =
  | { kind: "text"; text: string; start: number; end: number }
  | {
      kind: "entity";
      text: string;
      start: number;
      end: number;
      highlight: AnchorBoundPiiHighlight;
      highlights: AnchorBoundPiiHighlight[];
    };

export interface AnchorBoundPiiHighlightsByView {
  technical_raw_text: AnchorBoundPiiHighlight[];
  canonical_reading_text: AnchorBoundPiiHighlight[];
  layout_text: AnchorBoundPiiHighlight[];
}

export interface AnchorBoundPiiHighlightSummary {
  total_entities: number;
  evidence_only_count: number;
  missing_binding_count: number;
  partial_binding_count: number;
  ambiguous_binding_count: number;
  missing_canonical_count: number;
  ambiguous_canonical_count: number;
  partial_canonical_count: number;
  missing_layout_count: number;
  binding_reason_counts: Record<string, number>;
  warning_codes: string[];
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
    missing_binding_count: 0,
    partial_binding_count: 0,
    ambiguous_binding_count: 0,
    missing_canonical_count: 0,
    ambiguous_canonical_count: 0,
    partial_canonical_count: 0,
    missing_layout_count: 0,
    binding_reason_counts: {},
    warning_codes: [],
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
    missing_binding_count: 0,
    partial_binding_count: 0,
    ambiguous_binding_count: 0,
    missing_canonical_count: 0,
    ambiguous_canonical_count: 0,
    partial_canonical_count: 0,
    missing_layout_count: 0,
    binding_reason_counts: {},
    warning_codes: [],
  };
  const warningCodes = new Set<string>();

  for (const entity of contract.entities) {
    // A rejected (false-positive) entity stays renderable as an explicitly dismissed ghost so a
    // reviewer can see and revise the decision in place — but it no longer contributes to the
    // warning/coverage summary, which describes only active (pseudonymize/keep) entities.
    const rejected = entity.review_state === "rejected";
    if (!rejected) {
      collectEntitySummary(entity, summary, warningCodes);
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
    if (layoutRanges.length === 0 && !rejected) {
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
  summary.warning_codes = [...warningCodes].sort();

  return { byView, summary };
}

function collectEntitySummary(
  entity: ReviewReadyAnchorBoundPiiEntity,
  summary: AnchorBoundPiiHighlightSummary,
  warningCodes: Set<string>,
): void {
  for (const reason of entity.binding_reasons) {
    summary.binding_reason_counts[reason] = (summary.binding_reason_counts[reason] ?? 0) + 1;
    if (reason !== "anchor_exact_match") {
      warningCodes.add(reason);
    }
  }
  for (const warning of entity.warnings) {
    warningCodes.add(warning);
  }
  if (entity.identity_basis === "evidence_only") {
    summary.evidence_only_count += 1;
  }
  if (entity.binding_status === "missing") {
    summary.missing_binding_count += 1;
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
}

export const buildHighlightsFromAnchorBoundEntities = buildAnchorBoundPiiHighlights;
export const buildViewHighlightsFromEntityContract = buildAnchorBoundPiiHighlights;

export interface ManualAdditionHighlights {
  canonical: AnchorBoundPiiHighlight[];
  raw: AnchorBoundPiiHighlight[];
}

/**
 * Display-only adapter from manual additions (PII L14 / Review L10, ADR-0035) to the same highlight
 * shape the anchor-bound entity contract produces — a frontend-side merge only, never touching the
 * backend contract/`pii_result`. Canonical offsets are always available (that's what was captured);
 * the raw view is populated only when the reverse projection was `"exact"`, mirroring how detector
 * entities already only highlight raw when their own mapping is exact, never guessed. A `rejected`
 * addition stays included and renders as a dismissed ghost (like a rejected detector entity), so
 * the decision remains visible and revisable in place.
 * A `stale` addition (its `text_artifact_id` was superseded by a newer text result) is excluded:
 * its offsets refer to a previous text buffer, so rendering it into the current one would
 * decorate unrelated characters.
 */
export function buildManualAdditionHighlights(
  manualAdditions: readonly PiiManualAddition[],
): ManualAdditionHighlights {
  const canonical: AnchorBoundPiiHighlight[] = [];
  const raw: AnchorBoundPiiHighlight[] = [];

  for (const addition of manualAdditions) {
    if (addition.artifact_currency === "stale") {
      continue;
    }
    canonical.push(
      manualAdditionHighlight(
        addition,
        "canonical_reading_text",
        addition.canonical_start,
        addition.canonical_end,
        "exact",
      ),
    );
    if (
      addition.raw_projection_status === "exact" &&
      addition.raw_start != null &&
      addition.raw_end != null
    ) {
      raw.push(
        manualAdditionHighlight(addition, "technical_raw_text", addition.raw_start, addition.raw_end, "exact"),
      );
    }
  }

  canonical.sort(compareAnchorHighlightPosition);
  raw.sort(compareAnchorHighlightPosition);
  return { canonical, raw };
}

function manualAdditionHighlight(
  addition: PiiManualAddition,
  sourceName: PiiHighlightView,
  start: number,
  end: number,
  mappingStatus: PiiEntityMappingStatus,
): AnchorBoundPiiHighlight {
  return {
    entity_id: addition.addition_id,
    entity_type: addition.entity_type,
    identity_basis: "evidence_only",
    source_entity_ids: [addition.addition_id],
    primary_source_entity_id: addition.addition_id,
    anchor_ids: [],
    source_name: sourceName,
    start,
    end,
    binding_status: "not_applicable",
    mapping_status: mappingStatus,
    review_state: addition.review_status,
    needs_review: false,
    reason_codes: ["manual_addition"],
    confidence: 1,
    origin: "human",
  };
}

export function buildAnchorBoundHighlightSegments(
  text: string,
  highlights: readonly AnchorBoundPiiHighlight[],
): AnchorBoundHighlightSegment[] {
  const codePoints = Array.from(text);
  const valid = highlights
    .filter((highlight) => isValidHighlight(codePoints, highlight))
    .sort(compareAnchorHighlightPosition);
  const boundaries = [
    ...new Set([0, codePoints.length, ...valid.flatMap((item) => [item.start, item.end])]),
  ].sort((left, right) => left - right);
  const segments: AnchorBoundHighlightSegment[] = [];
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index];
    const end = boundaries[index + 1];
    if (end <= start) {
      continue;
    }
    const memberships = valid
      .filter((highlight) => highlight.start < end && highlight.end > start)
      .sort(compareAnchorHighlightPriority);
    const segmentText = codePoints.slice(start, end).join("");
    const primary = memberships[0];
    if (!primary) {
      segments.push({ kind: "text", text: segmentText, start, end });
    } else {
      segments.push({
        kind: "entity",
        text: segmentText,
        start,
        end,
        highlight: primary,
        highlights: memberships,
      });
    }
  }
  return segments;
}

/**
 * The ordered jump-navigation targets for a text view: the `primary_source_entity_id` of every
 * highlight that actually leads a rendered mark, in document order, deduplicated.
 *
 * This must mirror exactly how `PiiTextViewer` assigns a DOM id — a mark id is placed on the first
 * segment a highlight leads, and a highlight leads a segment only when it is valid for the text
 * buffer and is the top-priority member of that segment. An entity fully shadowed by an overlapping
 * higher-priority one (e.g. a PERSON inside a CONTACT_LINE) never becomes primary and so renders no
 * id; a highlight out of range for the text is dropped entirely. Navigation must use this list, not
 * the raw highlight set, or ↑/↓ would step onto ids that were never rendered ("jumps into nothing").
 */
export function orderedNavigableHighlightIds(
  text: string,
  highlights: readonly AnchorBoundPiiHighlight[],
): string[] {
  const segments = buildAnchorBoundHighlightSegments(text, highlights);
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const segment of segments) {
    if (segment.kind !== "entity") {
      continue;
    }
    const id = segment.highlight.primary_source_entity_id;
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

/** Highlights whose range does not fit the given text buffer. They are never rendered (the text
 *  must stay uncorrupted), but callers can surface the drop explicitly instead of silently. */
export function invalidAnchorBoundHighlights(
  text: string,
  highlights: readonly AnchorBoundPiiHighlight[],
): AnchorBoundPiiHighlight[] {
  const codePoints = Array.from(text);
  return highlights.filter((highlight) => !isValidHighlight(codePoints, highlight));
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
