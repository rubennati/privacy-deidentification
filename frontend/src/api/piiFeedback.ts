// Dev-only client for capturing human review feedback on detected PII entities.
// Only offsets, type, recognizer, and score are ever sent — never entity or document text.

import { WorkstationApiError, type PiiEntity } from "./workstations";

export type PiiFeedbackVerdict = "positive" | "issue";

export type PiiFeedbackIssueType =
  | "correct"
  | "false_positive"
  | "wrong_type"
  | "span_too_long_left"
  | "span_too_long_right"
  | "span_too_short_left"
  | "span_too_short_right"
  | "duplicate_or_should_merge"
  | "overlap_conflict"
  | "missing_related_entity"
  | "other";

// Selectable issue reasons (excludes "correct", which is the positive-verdict path).
export const PII_FEEDBACK_ISSUE_OPTIONS: ReadonlyArray<{
  value: Exclude<PiiFeedbackIssueType, "correct">;
  label: string;
}> = [
  { value: "false_positive", label: "Kein PII (False Positive)" },
  { value: "wrong_type", label: "Falscher Typ" },
  { value: "span_too_long_left", label: "Span zu lang (links)" },
  { value: "span_too_long_right", label: "Span zu lang (rechts)" },
  { value: "span_too_short_left", label: "Span zu kurz (links)" },
  { value: "span_too_short_right", label: "Span zu kurz (rechts)" },
  { value: "duplicate_or_should_merge", label: "Duplikat / sollte zusammengeführt werden" },
  { value: "overlap_conflict", label: "Überlappungs-Konflikt" },
  { value: "missing_related_entity", label: "Verwandte Entity fehlt" },
  { value: "other", label: "Sonstiges" },
];

export interface PiiFeedbackEntityRef {
  type: string;
  start: number;
  end: number;
  score: number;
  recognizer: string;
}

export interface PiiFeedbackRequest {
  artifact_id: string;
  entity: PiiFeedbackEntityRef;
  feedback: {
    verdict: PiiFeedbackVerdict;
    issue_type: PiiFeedbackIssueType;
    comment?: string | null;
  };
}

/** The minimal, non-sensitive fingerprint of a detected entity (no text). */
export function entityRef(entity: PiiEntity): PiiFeedbackEntityRef {
  return {
    type: entity.entity_type,
    start: entity.start_offset,
    end: entity.end_offset,
    score: entity.score,
    recognizer: entity.recognizer,
  };
}

export function buildPositiveFeedback(
  artifactId: string,
  entity: PiiEntity,
): PiiFeedbackRequest {
  return {
    artifact_id: artifactId,
    entity: entityRef(entity),
    feedback: { verdict: "positive", issue_type: "correct" },
  };
}

export function buildIssueFeedback(
  artifactId: string,
  entity: PiiEntity,
  issueType: Exclude<PiiFeedbackIssueType, "correct">,
  comment?: string,
): PiiFeedbackRequest {
  const trimmed = comment?.trim();
  return {
    artifact_id: artifactId,
    entity: entityRef(entity),
    feedback: {
      verdict: "issue",
      issue_type: issueType,
      ...(trimmed ? { comment: trimmed } : {}),
    },
  };
}

export async function sendPiiFeedback(
  documentId: string,
  request: PiiFeedbackRequest,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/pii/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
    );
  } catch {
    throw new WorkstationApiError("Keine Verbindung zum Server.", 0);
  }
  if (!response.ok) {
    let detail = "Feedback konnte nicht gespeichert werden.";
    let correlationId: string | null = null;
    try {
      const data = (await response.json()) as {
        detail?: string;
        correlation_id?: string | null;
      };
      detail = data.detail ?? detail;
      correlationId = data.correlation_id ?? null;
    } catch {
      // Keep the safe fallback; error bodies must not be assumed to be JSON.
    }
    throw new WorkstationApiError(detail, response.status, correlationId);
  }
}
