import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteDocument, fetchDocuments } from "../api/documents";
import type { DocumentSummary } from "../api/documents";
import { fetchDocumentJobs } from "../api/workstations";
import { deriveAnalysisState, type DocumentAnalysisState } from "../lib/documentListStatus";

/** Stable query keys for the document read flows. Keep list/jobs keys distinct so a delete can
 *  invalidate the list without discarding still-valid per-document job caches. */
export const documentKeys = {
  all: ["documents"] as const,
  list: () => [...documentKeys.all, "list"] as const,
  jobs: (id: string) => [...documentKeys.all, "jobs", id] as const,
};

/** The document list. Loading/error/caching are declarative — no hand-managed state or effects. */
export function useDocuments() {
  return useQuery({
    queryKey: documentKeys.list(),
    queryFn: fetchDocuments,
  });
}

/** Per-document analysis badge state, derived from the metadata-only jobs endpoint. Each document
 *  polls only while it is still analyzing (refetchInterval), so "Analyse läuft" resolves on its own
 *  and stops once settled — replacing the page's manual setTimeout poll. A document whose jobs
 *  request fails stays out of the map (no badge) instead of guessing. */
export function useDocumentAnalysisStates(
  documents: readonly DocumentSummary[],
): Record<string, DocumentAnalysisState> {
  const results = useQueries({
    queries: documents.map((document) => ({
      queryKey: documentKeys.jobs(document.id),
      queryFn: () => fetchDocumentJobs(document.id),
      select: deriveAnalysisState,
      staleTime: 5_000,
      refetchInterval: (query: { state: { data: unknown } }) =>
        query.state.data && deriveAnalysisState(query.state.data as never) === "running"
          ? 8_000
          : (false as const),
    })),
  });

  const byId: Record<string, DocumentAnalysisState> = {};
  documents.forEach((document, index) => {
    const result = results[index];
    if (result?.isSuccess && result.data) {
      byId[document.id] = result.data;
    }
  });
  return byId;
}

/** Delete a document, then invalidate the list so it refetches. */
export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentKeys.list() });
    },
  });
}
