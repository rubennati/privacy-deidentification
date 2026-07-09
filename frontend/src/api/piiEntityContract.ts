// Client + types for the anchor-bound review-ready PII entity contract (ADR-0031 Phase C, on top of
// ADR-0029). A derived, additive view over the latest pii_result: every detected entity is
// normalized against the OCR/Text Text Anchor Graph into a stable anchor-bound entity. Entity
// identity derives from anchor identity where an exact binding exists; raw offsets, canonical
// ranges, and the value are evidence/display, not identity. This does not mutate offsets; the UI
// highlights already loaded raw/canonical text using the display ranges. Types are additive —
// consuming this contract is optional and no existing review flow depends on it yet.

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

export type PiiAnchorBindingStatus = "exact" | "partial" | "missing" | "ambiguous" | "not_applicable";

export type PiiAnchorBindingRole =
  | "entity_span"
  | "supporting_span"
  | "display_span"
  | "inferred_span";

export type PiiEntityIdentityBasis = "anchor_exact" | "anchor_partial" | "evidence_only";

export type PiiAnchorSourceName =
  | "technical_raw_text"
  | "canonical_reading_text"
  | "layout_text";

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

export interface PiiEntityAnchorRef {
  anchor_id: string;
  source_name: PiiAnchorSourceName;
  source_range: PiiEntitySpan | null;
  binding_status: PiiAnchorBindingStatus;
  binding_role: PiiAnchorBindingRole;
  confidence: number | null;
  reason_codes: string[];
}

export interface PiiEntityAnchorSet {
  anchor_ids: string[];
  binding_status: PiiAnchorBindingStatus;
  count: number;
}

export interface PiiSourceObservation {
  detection_id: string;
  recognizer: string;
  entity_type: string;
  source_name: PiiAnchorSourceName;
  detection_source: string;
  detection_role: "primary" | "supporting";
  source_range: PiiEntitySourceSpan;
  confidence: number;
  binding_status: PiiAnchorBindingStatus;
  binding_reasons: string[];
  provenance: PiiEntityProvenance | null;
}

export interface ReviewReadyAnchorBoundPiiEntity {
  entity_id: string;
  entity_type: string;
  identity_basis: PiiEntityIdentityBasis;
  binding_status: PiiAnchorBindingStatus;
  binding_reasons: string[];
  anchor_set: PiiEntityAnchorSet;
  anchor_refs: PiiEntityAnchorRef[];
  source_observations: PiiSourceObservation[];
  provenance: PiiEntityProvenance | null;
  confidence: number;
  value: string;
  raw_text_range: PiiEntitySourceSpan;
  entity_group_id: string;
  source_entity_ids: string[];
  mapping_status: PiiEntityMappingStatus;
  canonical_reading_text_range: PiiEntityDisplaySpan | null;
  review_state: PiiReviewStatus;
  review_decision: PiiReviewDecisionValue | null;
  decision_scope: PiiReviewDecisionScope | null;
  display: PiiEntityDisplay;
  warnings: string[];
}

export interface PiiAnchorBindingSummary {
  total: number;
  anchor_bound: number;
  evidence_only: number;
  exact: number;
  partial: number;
  missing: number;
  ambiguous: number;
  not_applicable: number;
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
  anchor_graph_available: boolean;
  anchor_graph_status: "valid" | "degraded" | "invalid" | null;
  input_contract: unknown | null;
  overlap_resolution: unknown | null;
  entities: ReviewReadyAnchorBoundPiiEntity[];
  binding_summary: PiiAnchorBindingSummary;
  mapping_summary: PiiEntityMappingSummary;
  needs_review_count: number;
}

/** Which text layer to highlight an entity in, and the range within it.
 *
 * Prefers the canonical reading text when a display mapping exists, and always falls back to the
 * raw range so an entity with a missing/partial/ambiguous/not-applicable mapping still renders
 * without throwing. The entity's stable identity is its anchor set, independent of this view. */
export function resolveHighlightRange(entity: ReviewReadyAnchorBoundPiiEntity): {
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
