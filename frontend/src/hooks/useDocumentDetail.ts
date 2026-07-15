import { useQuery } from "@tanstack/react-query";

import { DocumentsApiError, fetchDocument, type DocumentSummary } from "../api/documents";
import {
  fetchAudit,
  fetchOcr,
  fetchPii,
  WorkstationApiError,
  type AuditArtifact,
  type PiiArtifact,
  type TextArtifact,
} from "../api/workstations";
import { toStationError } from "../lib/stationErrors";

export interface UiError {
  message: string;
  correlationId: string | null;
}

/** Cache keys for the document + its immutable artifacts. Exported so a mutation (analysis run,
 *  recovered OCR job) can push a freshly produced artifact straight into the cache. */
export const documentDetailKeys = {
  document: (id: string | undefined) => ["document", id ?? null] as const,
  audit: (id: string | undefined) => ["document", id ?? null, "audit"] as const,
  ocr: (id: string | undefined) => ["document", id ?? null, "ocr"] as const,
  pii: (id: string | undefined) => ["document", id ?? null, "pii"] as const,
};

export function useDocument(documentId: string | undefined) {
  return useQuery<DocumentSummary>({
    queryKey: documentDetailKeys.document(documentId),
    queryFn: () => fetchDocument(documentId as string),
    enabled: Boolean(documentId),
  });
}

export function toDocumentError(error: unknown): UiError {
  if (error instanceof DocumentsApiError) {
    return {
      message: error.status === 404 ? "Dokument nicht gefunden." : error.message,
      correlationId: error.correlationId,
    };
  }
  return { message: "Dokument konnte nicht geladen werden.", correlationId: null };
}

/** An artifact that 404s just hasn't been produced yet (a normal "not analyzed" state), so it maps
 *  to `null`, not an error. Any other failure surfaces as a station error. */
async function loadOptionalArtifact<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof WorkstationApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export interface DocumentArtifacts {
  audit: AuditArtifact | null;
  text: TextArtifact | null;
  pii: PiiArtifact | null;
  stationErrors: Record<"audit" | "ocr" | "pii", UiError | null>;
  isPending: boolean;
}

/** The three immutable OCR/PII artifacts for a document. Each loads independently (optional), so a
 *  document that isn't analyzed yet simply has nulls — the same shape the page's coordinated effect
 *  produced, now declarative and fail-closed on document change (the query key carries documentId). */
export function useDocumentArtifacts(documentId: string | undefined): DocumentArtifacts {
  const enabled = Boolean(documentId);
  const auditQuery = useQuery({
    queryKey: documentDetailKeys.audit(documentId),
    queryFn: () => loadOptionalArtifact(() => fetchAudit(documentId as string)),
    enabled,
  });
  const ocrQuery = useQuery({
    queryKey: documentDetailKeys.ocr(documentId),
    queryFn: () => loadOptionalArtifact(() => fetchOcr(documentId as string)),
    enabled,
  });
  const piiQuery = useQuery({
    queryKey: documentDetailKeys.pii(documentId),
    queryFn: () => loadOptionalArtifact(() => fetchPii(documentId as string)),
    enabled,
  });

  return {
    audit: auditQuery.data ?? null,
    text: ocrQuery.data ?? null,
    pii: piiQuery.data ?? null,
    stationErrors: {
      audit: auditQuery.error ? toStationError(auditQuery.error, "audit") : null,
      ocr: ocrQuery.error ? toStationError(ocrQuery.error, "ocr") : null,
      pii: piiQuery.error ? toStationError(piiQuery.error, "pii") : null,
    },
    isPending: enabled && (auditQuery.isPending || ocrQuery.isPending || piiQuery.isPending),
  };
}
