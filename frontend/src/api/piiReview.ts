// Client for the PII review-entity layer: grouped occurrences and their review decisions.
// This sits between detection (workstations.ts) and future pseudonymization — no text is ever
// replaced here, and raw/projected offsets are never mutated by a decision.

import { WorkstationApiError } from "./workstations";

export type PiiReviewDecisionScope = "entity_group" | "occurrence";
// A freshly detected entity is assumed "pseudonymize" by default — there is no separate "pending"
// value. A reviewer only has to act to opt an entity *out* of pseudonymization: "keep" it as-is,
// or mark it a "false_positive" (not PII at all).
export type PiiReviewDecisionValue = "pseudonymize" | "keep" | "false_positive";
export type PiiReviewStatus = "accepted" | "kept" | "rejected";

export const PII_REVIEW_DECISION_OPTIONS: ReadonlyArray<{
  value: PiiReviewDecisionValue;
  label: string;
}> = [
  { value: "pseudonymize", label: "Pseudonymisieren" },
  { value: "keep", label: "Nicht pseudonymisieren" },
  { value: "false_positive", label: "Kein PII (False Positive)" },
];

export function reviewDecisionLabel(decision: PiiReviewDecisionValue): string {
  return PII_REVIEW_DECISION_OPTIONS.find((option) => option.value === decision)?.label ?? decision;
}

const STATUS_LABELS: Record<PiiReviewStatus, string> = {
  accepted: "Wird pseudonymisiert",
  kept: "Nicht pseudonymisiert",
  rejected: "Abgelehnt",
};

export function reviewStatusLabel(status: PiiReviewStatus): string {
  return STATUS_LABELS[status];
}

export interface PiiEntityGroupProjectionSummary {
  exact_count: number;
  partial_count: number;
  unmapped_count: number;
}

export interface PiiEntityGroupReview {
  entity_group_id: string;
  entity_type: string;
  occurrence_ids: string[];
  occurrence_count: number;
  normalized_fingerprint: string;
  projection_summary: PiiEntityGroupProjectionSummary;
  review_status: PiiReviewStatus;
  review_decision: PiiReviewDecisionValue | null;
  updated_at: string | null;
}

export interface PiiReviewOccurrence {
  occurrence_id: string;
  entity_type: string;
  entity_group_id: string;
  raw_start: number;
  raw_end: number;
  score: number;
  recognizer: string;
  projection_status: "exact" | "partial" | "unmapped" | null;
  projection_method: "offset_map" | "text_match" | null;
  reading_start_offset: number | null;
  reading_end_offset: number | null;
  review_status: PiiReviewStatus;
  review_decision: PiiReviewDecisionValue | null;
  decision_scope: PiiReviewDecisionScope | null;
}

export interface PiiReviewResult {
  document_id: string;
  artifact_id: string;
  groups: PiiEntityGroupReview[];
  occurrences: PiiReviewOccurrence[];
}

export interface PiiReviewDecisionRequest {
  target_type: PiiReviewDecisionScope;
  target_id: string;
  decision: PiiReviewDecisionValue;
  note?: string;
}

export interface PiiReviewDecisionAck {
  recorded: boolean;
  target_type: PiiReviewDecisionScope;
  target_id: string;
  decision: PiiReviewDecisionValue;
  review_status: PiiReviewStatus;
  updated_at: string;
}

/** Stable per-occurrence key → review status lookup, e.g. for highlight suppression. */
export function buildReviewStatusMap(
  review: PiiReviewResult | null,
): Record<string, PiiReviewStatus> {
  const map: Record<string, PiiReviewStatus> = {};
  for (const occurrence of review?.occurrences ?? []) {
    map[occurrence.occurrence_id] = occurrence.review_status;
  }
  return map;
}

/** Fetch the reviewable groups/occurrences for a document. Returns null on any failure (missing
 *  PII result, network error, legacy/unreachable server) so the UI degrades to "no review data"
 *  instead of breaking. */
export async function fetchPiiReview(documentId: string): Promise<PiiReviewResult | null> {
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/pii/review`);
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as PiiReviewResult;
  } catch {
    return null;
  }
}

export async function submitPiiReviewDecision(
  documentId: string,
  request: PiiReviewDecisionRequest,
): Promise<PiiReviewDecisionAck> {
  let response: Response;
  try {
    response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/pii/review/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new WorkstationApiError("Keine Verbindung zum Server.", 0);
  }
  if (!response.ok) {
    let detail = "Entscheidung konnte nicht gespeichert werden.";
    let correlationId: string | null = null;
    try {
      const data = (await response.json()) as { detail?: string; correlation_id?: string | null };
      detail = data.detail ?? detail;
      correlationId = data.correlation_id ?? null;
    } catch {
      // Keep the safe fallback; error bodies must not be assumed to be JSON.
    }
    throw new WorkstationApiError(detail, response.status, correlationId);
  }
  return (await response.json()) as PiiReviewDecisionAck;
}
