import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchPiiEntityContract,
  resolveHighlightRange,
  type PiiEntityContractV1,
  type ReviewReadyPiiEntity,
} from "./piiEntityContract";

function makeEntity(overrides: Partial<ReviewReadyPiiEntity> = {}): ReviewReadyPiiEntity {
  return {
    entity_id: "1".repeat(32),
    source_entity_id: "2".repeat(32),
    entity_group_id: "3".repeat(32),
    document_id: "doc-1",
    package_id: "4".repeat(32),
    text_artifact_id: "4".repeat(32),
    entity_type: "LOCATION",
    value: "Wien",
    confidence: 0.9,
    detection_source: "raw_text",
    source_role: "primary",
    page_number: null,
    raw_text_range: { start: 0, end: 4, page_number: null, page_start: null, page_end: null },
    canonical_reading_text_range: null,
    mapping_status: "missing",
    overlap_decision: null,
    provenance: null,
    review_state: "accepted",
    review_decision: null,
    decision_scope: null,
    display: {
      preferred_text_source: "technical_raw_text",
      raw_highlight_range: { start: 0, end: 4 },
      canonical_highlight_range: null,
      display_label: "LOCATION",
      display_context_available: false,
      needs_review: true,
      review_reason_codes: ["canonical_mapping_missing"],
    },
    warnings: ["canonical_mapping_missing"],
    ...overrides,
  };
}

function makeContract(entities: ReviewReadyPiiEntity[]): PiiEntityContractV1 {
  return {
    contract_version: "1.0",
    document_id: "doc-1",
    pii_artifact_id: "5".repeat(32),
    package_id: "4".repeat(32),
    text_artifact_id: "4".repeat(32),
    reading_text_available: true,
    input_contract: null,
    overlap_resolution: null,
    entities,
    mapping_summary: { exact: 0, projected: 0, partial: 0, missing: 1, ambiguous: 0, not_applicable: 0 },
    needs_review_count: 1,
  };
}

describe("fetchPiiEntityContract", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("GETs the entity contract for a document and returns it", async () => {
    const contract = makeContract([makeEntity()]);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(contract), { status: 200 }));

    const result = await fetchPiiEntityContract("doc-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-1/pii/entity-contract");
    expect(result).toEqual(contract);
  });

  it("returns null when there is no PII result yet (404)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 404 }));
    expect(await fetchPiiEntityContract("doc-1")).toBeNull();
  });

  it("returns null on a network failure instead of throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
    expect(await fetchPiiEntityContract("doc-1")).toBeNull();
  });
});

describe("resolveHighlightRange", () => {
  it("falls back to the raw range when the canonical mapping is missing", () => {
    const resolved = resolveHighlightRange(makeEntity());
    expect(resolved).toEqual({ source: "technical_raw_text", range: { start: 0, end: 4 } });
  });

  it("does not crash for partial, ambiguous, or not_applicable mapping statuses", () => {
    for (const mapping_status of ["partial", "ambiguous", "not_applicable"] as const) {
      const entity = makeEntity({ mapping_status, canonical_reading_text_range: null });
      expect(() => resolveHighlightRange(entity)).not.toThrow();
      expect(resolveHighlightRange(entity).source).toBe("technical_raw_text");
    }
  });

  it("prefers the canonical range when the mapping is exact", () => {
    const entity = makeEntity({
      mapping_status: "exact",
      canonical_reading_text_range: { start: 2, end: 6, projection_method: "offset_map" },
      display: {
        preferred_text_source: "canonical_reading_text",
        raw_highlight_range: { start: 0, end: 4 },
        canonical_highlight_range: { start: 2, end: 6 },
        display_label: "LOCATION",
        display_context_available: true,
        needs_review: false,
        review_reason_codes: [],
      },
    });
    expect(resolveHighlightRange(entity)).toEqual({
      source: "canonical_reading_text",
      range: { start: 2, end: 6 },
    });
  });
});
