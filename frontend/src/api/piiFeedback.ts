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

export type PiiIssueOnly = Exclude<PiiFeedbackIssueType, "correct">;

// Selectable issue reasons (excludes "correct", which is the positive-verdict path). Each carries
// a short reviewer-facing explanation shown once the reason is selected.
export const PII_FEEDBACK_ISSUE_OPTIONS: ReadonlyArray<{
  value: PiiIssueOnly;
  label: string;
  description: string;
}> = [
  {
    value: "false_positive",
    label: "Kein PII (False Positive)",
    description: "Diese Stelle enthält keine schützenswerte Information / kein PII.",
  },
  {
    value: "wrong_type",
    label: "Falscher Typ",
    description:
      "Die Stelle ist PII, aber die Kategorie ist falsch. Beispiel: Straße wurde als LOCATION erkannt.",
  },
  {
    value: "span_too_long_left",
    label: "Span zu lang (links)",
    description: "Links wurde zu viel Text in die Entity aufgenommen.",
  },
  {
    value: "span_too_long_right",
    label: "Span zu lang (rechts)",
    description: "Rechts wurde zu viel Text in die Entity aufgenommen.",
  },
  {
    value: "span_too_short_left",
    label: "Span zu kurz (links)",
    description: "Links fehlt ein Teil der Entity.",
  },
  {
    value: "span_too_short_right",
    label: "Span zu kurz (rechts)",
    description: "Rechts fehlt ein Teil der Entity.",
  },
  {
    value: "duplicate_or_should_merge",
    label: "Duplikat / sollte zusammengeführt werden",
    description: "Diese Entity sollte mit anderen gleichen Vorkommen zusammengeführt werden.",
  },
  {
    value: "overlap_conflict",
    label: "Überlappungs-Konflikt",
    description: "Diese Entity überschneidet sich widersprüchlich mit einer anderen Entity.",
  },
  {
    value: "missing_related_entity",
    label: "Verwandte Entity fehlt",
    description: "Eine zusammengehörige Entity fehlt oder wurde getrennt erkannt.",
  },
  {
    value: "other",
    label: "Anderes Problem",
    description: "Anderes Problem; bitte Kommentar verwenden.",
  },
];

const ISSUE_LABELS: Record<PiiFeedbackIssueType, string> = {
  correct: "Passt",
  ...Object.fromEntries(PII_FEEDBACK_ISSUE_OPTIONS.map((o) => [o.value, o.label])),
} as Record<PiiFeedbackIssueType, string>;

const ISSUE_DESCRIPTIONS: Record<PiiIssueOnly, string> = Object.fromEntries(
  PII_FEEDBACK_ISSUE_OPTIONS.map((o) => [o.value, o.description]),
) as Record<PiiIssueOnly, string>;

/** Human label for any issue_type (incl. "correct"), e.g. for a saved-status line. */
export function issueTypeLabel(issueType: PiiFeedbackIssueType): string {
  return ISSUE_LABELS[issueType] ?? issueType;
}

/** Short explanation for a selected issue reason, or undefined for the empty/"correct" case. */
export function issueExplanation(issueType: string): string | undefined {
  return (ISSUE_DESCRIPTIONS as Record<string, string>)[issueType];
}

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

export interface PiiFeedbackStatus {
  verdict: PiiFeedbackVerdict;
  issue_type: PiiFeedbackIssueType;
}

export interface PiiFeedbackSummaryItem extends PiiFeedbackStatus {
  type: string;
  start: number;
  end: number;
  recognizer: string;
  recorded_at: string;
}

export interface PiiFeedbackSummary {
  document_id: string;
  artifact_id: string;
  items: PiiFeedbackSummaryItem[];
}

/** Stable per-entity key shared by the summary lookup and each rendered entity. */
export function entityFeedbackKey(entity: PiiEntity): string {
  return [entity.entity_type, entity.start_offset, entity.end_offset, entity.recognizer].join("|");
}

function summaryItemKey(item: PiiFeedbackSummaryItem): string {
  return [item.type, item.start, item.end, item.recognizer].join("|");
}

/** Collapse a summary into a key→status map the entity list can look up per entity. */
export function buildFeedbackStatusMap(
  summary: PiiFeedbackSummary | null,
): Record<string, PiiFeedbackStatus> {
  const map: Record<string, PiiFeedbackStatus> = {};
  for (const item of summary?.items ?? []) {
    map[summaryItemKey(item)] = { verdict: item.verdict, issue_type: item.issue_type };
  }
  return map;
}

/** Fetch the latest feedback per entity for one artifact. Returns null on any failure so the
 *  review UI degrades to "no prior feedback" instead of breaking. */
export async function fetchPiiFeedbackSummary(
  documentId: string,
  artifactId: string,
): Promise<PiiFeedbackSummary | null> {
  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/pii/feedback?artifact_id=${encodeURIComponent(artifactId)}`,
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as PiiFeedbackSummary;
  } catch {
    return null;
  }
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
