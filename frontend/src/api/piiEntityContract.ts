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
  total_entities: number;
  anchor_bound_entities: number;
  evidence_only_entities: number;
  exact_bound_entities: number;
  partial_bound_entities: number;
  ambiguous_bound_entities: number;
  entities_with_raw_range: number;
  entities_with_canonical_range: number;
  entities_with_layout_range: number;
  missing_canonical_range_count: number;
  missing_layout_range_count: number;
  binding_reason_counts: Record<string, number>;
  warning_codes: string[];
  // Metrics-only coverage ratios (pii-binding-quality-suite, ADR-0033): the fraction of entities
  // that received any anchor binding (exact or partial) vs. purely exact. `0` when there are no
  // entities.
  anchor_bound_ratio: number;
  exact_bound_ratio: number;
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

/** Outcome of fetching the entity contract: `not_found` (no PII result yet, a normal 404 product
 *  state, never shown as an error) is kept distinct from `error` (an unexpected network/server
 *  failure — the contract-fetch-failure notice) so the UI never renders both the same way. */
export type PiiEntityContractFetchResult =
  | { status: "ok"; contract: PiiEntityContractV1 }
  | { status: "not_found" }
  | { status: "error" };

/** Fetch the review-ready entity contract for a document. Never throws. */
export async function fetchPiiEntityContract(
  documentId: string,
): Promise<PiiEntityContractFetchResult> {
  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/pii/entity-contract`,
    );
    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (!response.ok) {
      return { status: "error" };
    }
    const contract = (await response.json()) as PiiEntityContractV1;
    return { status: "ok", contract };
  } catch {
    return { status: "error" };
  }
}
