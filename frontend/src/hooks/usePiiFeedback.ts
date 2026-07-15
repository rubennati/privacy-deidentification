import { useQuery } from "@tanstack/react-query";

import {
  buildFeedbackStatusMap,
  fetchPiiFeedbackSummary,
  type PiiFeedbackStatus,
} from "../api/piiFeedback";

export const piiFeedbackKey = (documentId: string | undefined, piiArtifactId: string | null) =>
  ["pii", "feedback", documentId ?? null, piiArtifactId] as const;

/** Dev-only per-entity feedback status for the current PII result. Empty unless the dev gate is on
 *  and a PII result exists — the same guard the previous effect applied, now a query `enabled`. */
export function usePiiFeedbackStatuses(
  documentId: string | undefined,
  piiArtifactId: string | null,
  enabled: boolean,
): Record<string, PiiFeedbackStatus> {
  const query = useQuery({
    queryKey: piiFeedbackKey(documentId, piiArtifactId),
    queryFn: () => fetchPiiFeedbackSummary(documentId as string, piiArtifactId as string),
    enabled: Boolean(documentId && piiArtifactId && enabled),
    select: buildFeedbackStatusMap,
  });
  return query.data ?? {};
}
