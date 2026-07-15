import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchPiiEntityContract,
  type PiiEntityContractFetchResult,
} from "../api/piiEntityContract";
import { fetchPiiReview, type PiiReviewResult } from "../api/piiReview";

export const piiReviewKeys = {
  review: (documentId: string | undefined, piiArtifactId: string | null) =>
    ["pii", "review", documentId ?? null, piiArtifactId] as const,
  contract: (
    documentId: string | undefined,
    piiArtifactId: string | null,
    textArtifactId: string | null,
  ) => ["pii", "entity-contract", documentId ?? null, piiArtifactId, textArtifactId] as const,
};

/** Same shape the page used as local state, so consumers stay unchanged. */
export type PiiEntityContractState = { status: "idle" | "loading" } | PiiEntityContractFetchResult;

/** The review overlay (groups + decisions) and the anchor-bound entity contract for the current PII
 *  result. The contract is fetched only when the PII result's input text matches the current OCR
 *  text (lineage); otherwise it stays `idle` — the UI's "nicht verfügbar" state, byte-for-byte the
 *  same gate the previous imperative effect applied, now declarative and race-free. */
export function usePiiReviewAndContract(
  documentId: string | undefined,
  piiArtifactId: string | null,
  textArtifactId: string | null,
  piiInputTextArtifactId: string | null,
): { reviewResult: PiiReviewResult | null; piiEntityContractState: PiiEntityContractState } {
  const reviewEnabled = Boolean(documentId && piiArtifactId);
  const lineageOk = Boolean(textArtifactId) && piiInputTextArtifactId === textArtifactId;
  const contractEnabled = reviewEnabled && lineageOk;

  const reviewQuery = useQuery({
    queryKey: piiReviewKeys.review(documentId, piiArtifactId),
    queryFn: () => fetchPiiReview(documentId as string),
    enabled: reviewEnabled,
  });
  const contractQuery = useQuery({
    queryKey: piiReviewKeys.contract(documentId, piiArtifactId, textArtifactId),
    queryFn: () =>
      fetchPiiEntityContract(documentId as string, piiArtifactId as string, textArtifactId as string),
    enabled: contractEnabled,
  });

  const piiEntityContractState: PiiEntityContractState = !contractEnabled
    ? { status: "idle" }
    : contractQuery.isPending
      ? { status: "loading" }
      : (contractQuery.data ?? { status: "error" });

  return { reviewResult: reviewQuery.data ?? null, piiEntityContractState };
}

/** Apply a fresh review result after a decision: push it into the cache (instant) and refetch the
 *  contract (suppression/highlights depend on decisions). Replaces the manual refresh flow. */
export function usePiiReviewInvalidation() {
  const queryClient = useQueryClient();
  return (
    documentId: string | undefined,
    piiArtifactId: string | null,
    textArtifactId: string | null,
    review: PiiReviewResult,
  ) => {
    queryClient.setQueryData(piiReviewKeys.review(documentId, piiArtifactId), review);
    return queryClient.invalidateQueries({
      queryKey: piiReviewKeys.contract(documentId, piiArtifactId, textArtifactId),
    });
  };
}
