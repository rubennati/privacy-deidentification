// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PiiReviewResult } from "../../api/piiReview";
import { AddPiiManualEntity } from "./AddPiiManualEntity";

const reviewResult: PiiReviewResult = {
  document_id: "doc-1",
  artifact_id: "art-1",
  groups: [],
  occurrences: [],
  manual_additions: [
    {
      addition_id: "a".repeat(32),
      entity_type: "LOCATION",
      canonical_start: 6,
      canonical_end: 10,
      text_artifact_id: "b".repeat(32),
      raw_start: 6,
      raw_end: 10,
      raw_projection_status: "exact",
      origin: "human",
      note: null,
      created_at: "2026-07-11T10:00:00Z",
      review_status: "accepted",
      review_decision: null,
    },
  ],
  stale_decision_count: 0,
  has_stale_decisions: false,
};

/**
 * Real click → fetch → refetch → callback coverage (PII L14, ADR-0035) — the interactive part the
 * static-render tests in `AddPiiManualEntity.test.tsx` can't reach.
 */
describe("AddPiiManualEntity submit flow", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("posts the selection, refetches the review result, and calls onAdded", async () => {
    const onAdded = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/manual-additions")) {
        return new Response(
          JSON.stringify({
            recorded: true,
            addition_id: "a".repeat(32),
            entity_type: "LOCATION",
            canonical_start: 6,
            canonical_end: 10,
            raw_projection_status: "exact",
            created_at: "2026-07-11T10:00:00Z",
          }),
          { status: 201 },
        );
      }
      if (url.includes("/pii/review")) {
        return new Response(JSON.stringify(reviewResult), { status: 200 });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const { getByText } = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={["LOCATION", "PERSON"]}
        readingText="Hallo Wien"
        selection={{ start: 6, end: 10 }}
        onAdded={onAdded}
      />,
    );

    fireEvent.click(getByText("Als PII hinzufügen"));

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith(reviewResult));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/documents/doc-1/pii/review/manual-additions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ entity_type: "LOCATION", canonical_start: 6, canonical_end: 10 }),
      }),
    );
  });

  it("shows an error and does not call onAdded when the request fails", async () => {
    const onAdded = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "invalid" }), { status: 422 }),
    );

    const { getByText, findByText } = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={["LOCATION"]}
        readingText="Hallo Wien"
        selection={{ start: 6, end: 10 }}
        onAdded={onAdded}
      />,
    );

    fireEvent.click(getByText("Als PII hinzufügen"));

    expect(await findByText("Ergänzung konnte nicht gespeichert werden.")).toBeTruthy();
    expect(onAdded).not.toHaveBeenCalled();
  });
});
