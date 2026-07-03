import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PII_REVIEW_DECISION_OPTIONS,
  buildReviewStatusMap,
  fetchPiiReview,
  reviewDecisionLabel,
  reviewStatusLabel,
  submitPiiReviewDecision,
  type PiiReviewResult,
} from "./piiReview";

const review: PiiReviewResult = {
  document_id: "doc-1",
  artifact_id: "art-1",
  groups: [
    {
      entity_group_id: "g".repeat(32),
      entity_type: "LOCATION",
      occurrence_ids: ["o".repeat(32)],
      occurrence_count: 1,
      normalized_fingerprint: "f".repeat(64),
      projection_summary: { exact_count: 1, partial_count: 0, unmapped_count: 0 },
      review_status: "accepted",
      review_decision: null,
      updated_at: null,
    },
  ],
  occurrences: [
    {
      occurrence_id: "o".repeat(32),
      entity_type: "LOCATION",
      entity_group_id: "g".repeat(32),
      raw_start: 0,
      raw_end: 4,
      score: 0.9,
      recognizer: "FakeRecognizer",
      projection_status: "exact",
      projection_method: "offset_map",
      reading_start_offset: 0,
      reading_end_offset: 4,
      review_status: "kept",
      review_decision: "keep",
      decision_scope: "entity_group",
    },
  ],
};

describe("fetchPiiReview", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("GETs the review result for a document and returns it", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(review), { status: 200 }));

    const result = await fetchPiiReview("doc-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-1/pii/review");
    expect(result).toEqual(review);
  });

  it("returns null when there is no PII result yet (404)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 404 }));
    expect(await fetchPiiReview("doc-1")).toBeNull();
  });

  it("returns null on a network failure instead of throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
    expect(await fetchPiiReview("doc-1")).toBeNull();
  });
});

describe("submitPiiReviewDecision", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs the decision payload to the document's review-decisions endpoint", async () => {
    const ack = {
      recorded: true,
      target_type: "entity_group" as const,
      target_id: "g".repeat(32),
      decision: "keep" as const,
      review_status: "kept" as const,
      updated_at: "2026-07-03T10:00:00Z",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(ack), { status: 201 }));

    const request = { target_type: "entity_group" as const, target_id: "g".repeat(32), decision: "keep" as const };
    const result = await submitPiiReviewDecision("doc-1", request);

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-1/pii/review/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    expect(result).toEqual(ack);
  });

  it("throws a WorkstationApiError on a non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
    );

    await expect(
      submitPiiReviewDecision("doc-1", {
        target_type: "occurrence",
        target_id: "o".repeat(32),
        decision: "false_positive",
      }),
    ).rejects.toMatchObject({ status: 404, message: "not found" });
  });

  it("throws a safe generic error when the response body is not JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>502</html>", { status: 502 }));

    await expect(
      submitPiiReviewDecision("doc-1", {
        target_type: "occurrence",
        target_id: "o".repeat(32),
        decision: "false_positive",
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it("throws on a connection failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));

    await expect(
      submitPiiReviewDecision("doc-1", {
        target_type: "occurrence",
        target_id: "o".repeat(32),
        decision: "keep",
      }),
    ).rejects.toMatchObject({ status: 0 });
  });
});

describe("buildReviewStatusMap", () => {
  it("tolerates a null review result", () => {
    expect(buildReviewStatusMap(null)).toEqual({});
  });

  it("maps occurrence id to its resolved review status", () => {
    const map = buildReviewStatusMap(review);
    expect(map[review.occurrences[0].occurrence_id]).toBe("kept");
  });
});

describe("label helpers", () => {
  it("labels every documented decision value", () => {
    for (const option of PII_REVIEW_DECISION_OPTIONS) {
      expect(reviewDecisionLabel(option.value)).toBe(option.label);
    }
  });

  it("labels every review status", () => {
    expect(reviewStatusLabel("accepted")).toBe("Wird pseudonymisiert");
    expect(reviewStatusLabel("kept")).toBe("Nicht pseudonymisiert");
    expect(reviewStatusLabel("rejected")).toBe("Abgelehnt");
  });
});
