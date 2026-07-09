// Client + types for the review-ready PII entity contract (ADR-0029).
// A derived, additive view over the latest pii_result: every detected entity carries a stable id,
// its authoritative raw span, an optional canonical reading span, an explicit mapping status, and a
// text-free display model. This does not replace text or mutate offsets; the UI highlights already
// loaded raw/canonical text using these ranges. Types are intentionally additive — consuming this
// contract is optional and no existing review flow depends on it yet.

import type {
  PiiReviewDecisionScope,
  PiiReviewDecisionValue,
  PiiReviewStatus,
} from "./piiReview";

export type PiiEntityMappingStatus =
  | "exact"
  | "projected"
  | "partial"
  | "missing"
  | "ambiguous"
  | "not_applicable";

export type PiiEntityPreferredTextSource = "technical_raw_text" | "canonical_reading_text";

export interface PiiEntitySpan {
  start: number;
  end: number;
}

export interface PiiEntitySourceSpan extends PiiEntitySpan {
  page_number: number | null;
  page_start: number | null;
  page_end: number | null;
}

export interface PiiEntityDisplaySpan extends PiiEntitySpan {
  projection_method: "offset_map" | "text_match" | null;
}

export interface PiiEntityDisplay {
  preferred_text_source: PiiEntityPreferredTextSource;
  raw_highlight_range: PiiEntitySpan;
  canonical_highlight_range: PiiEntitySpan | null;
  display_label: string;
  display_context_available: boolean;
  needs_review: boolean;
  review_reason_codes: string[];
}

export interface PiiEntityProvenance {
  detection_source: string;
  source_role: string;
  recognizers: string[];
  candidate_count: number;
  merge_reason: string | null;
  overlap_decision: string | null;
  review_required: boolean;
  superseded_candidate_ids: string[];
}

export interface ReviewReadyPiiEntity {
  entity_id: string;
  source_entity_id: string;
  entity_group_id: string;
  document_id: string;
  package_id: string;
  text_artifact_id: string;
  entity_type: string;
  value: string;
  confidence: number;
  detection_source: string;
  source_role: string;
  page_number: number | null;
  raw_text_range: PiiEntitySourceSpan;
  canonical_reading_text_range: PiiEntityDisplaySpan | null;
  mapping_status: PiiEntityMappingStatus;
  overlap_decision: string | null;
  provenance: PiiEntityProvenance | null;
  review_state: PiiReviewStatus;
  review_decision: PiiReviewDecisionValue | null;
  decision_scope: PiiReviewDecisionScope | null;
  display: PiiEntityDisplay;
  warnings: string[];
}

export interface PiiEntityMappingSummary {
  exact: number;
  projected: number;
  partial: number;
  missing: number;
  ambiguous: number;
  not_applicable: number;
}

export interface PiiEntityContractV1 {
  contract_version: "1.0";
  document_id: string;
  pii_artifact_id: string;
  package_id: string;
  text_artifact_id: string;
  reading_text_available: boolean;
  input_contract: unknown | null;
  overlap_resolution: unknown | null;
  entities: ReviewReadyPiiEntity[];
  mapping_summary: PiiEntityMappingSummary;
  needs_review_count: number;
}

/** Which text layer to highlight an entity in, and the range within it.
 *
 * Prefers the canonical reading text when a mapping exists, and always falls back to the raw range
 * so an entity with a missing/partial/ambiguous/not-applicable mapping still renders without
 * throwing. */
export function resolveHighlightRange(entity: ReviewReadyPiiEntity): {
  source: PiiEntityPreferredTextSource;
  range: PiiEntitySpan;
} {
  const canonical = entity.display.canonical_highlight_range;
  if (entity.display.preferred_text_source === "canonical_reading_text" && canonical) {
    return { source: "canonical_reading_text", range: canonical };
  }
  return { source: "technical_raw_text", range: entity.display.raw_highlight_range };
}

/** Fetch the review-ready entity contract for a document. Returns null on any failure (missing PII
 *  result, network error, legacy/unreachable server) so the UI degrades to "no contract data"
 *  instead of breaking. */
export async function fetchPiiEntityContract(
  documentId: string,
): Promise<PiiEntityContractV1 | null> {
  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/pii/entity-contract`,
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as PiiEntityContractV1;
  } catch {
    return null;
  }
}
