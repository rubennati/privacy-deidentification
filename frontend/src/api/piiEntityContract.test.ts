import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchPiiEntityContract,
  resolveHighlightRange,
  type PiiEntityContractV1,
  type ReviewReadyAnchorBoundPiiEntity,
} from "./piiEntityContract";

function makeEntity(
  overrides: Partial<ReviewReadyAnchorBoundPiiEntity> = {},
): ReviewReadyAnchorBoundPiiEntity {
  return {
    entity_id: "1".repeat(32),
    entity_type: "LOCATION",
    identity_basis: "evidence_only",
    binding_status: "missing",
    binding_reasons: ["anchor_missing", "detection_evidence_only"],
    anchor_set: { anchor_ids: [], binding_status: "missing", count: 0 },
    anchor_refs: [],
    source_observations: [
      {
        detection_id: "2".repeat(32),
        recognizer: "TestRecognizer",
        entity_type: "LOCATION",
        source_name: "technical_raw_text",
        detection_source: "raw_text",
        detection_role: "primary",
        source_range: { start: 0, end: 4, page_number: null, page_start: null, page_end: null },
        confidence: 0.9,
        binding_status: "missing",
        binding_reasons: ["anchor_missing", "detection_evidence_only"],
        provenance: null,
      },
    ],
    provenance: null,
    confidence: 0.9,
    value: "Wien",
    raw_text_range: { start: 0, end: 4, page_number: null, page_start: null, page_end: null },
    entity_group_id: "3".repeat(32),
    source_entity_ids: ["2".repeat(32)],
    mapping_status: "missing",
    canonical_reading_text_range: null,
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
      review_reason_codes: ["anchor_binding_missing", "canonical_mapping_missing"],
    },
    warnings: ["anchor_binding_missing", "canonical_mapping_missing"],
    ...overrides,
  };
}

function makeContract(entities: ReviewReadyAnchorBoundPiiEntity[]): PiiEntityContractV1 {
  return {
    contract_version: "1.0",
    document_id: "doc-1",
    pii_artifact_id: "5".repeat(32),
    package_id: "4".repeat(32),
    text_artifact_id: "4".repeat(32),
    reading_text_available: true,
    anchor_graph_available: false,
    anchor_graph_status: null,
    input_contract: null,
    overlap_resolution: null,
    entities,
    binding_summary: {
      total: 1,
      anchor_bound: 0,
      evidence_only: 1,
      exact: 0,
      partial: 0,
      missing: 1,
      ambiguous: 0,
      not_applicable: 0,
      total_entities: 1,
      anchor_bound_entities: 0,
      evidence_only_entities: 1,
      exact_bound_entities: 0,
      partial_bound_entities: 0,
      ambiguous_bound_entities: 0,
      entities_with_raw_range: 1,
      entities_with_canonical_range: 0,
      entities_with_layout_range: 0,
      missing_canonical_range_count: 1,
      missing_layout_range_count: 1,
      binding_reason_counts: { anchor_missing: 1, detection_evidence_only: 1 },
      warning_codes: ["anchor_missing", "detection_evidence_only"],
    },
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

  it("prefers the canonical range when the entity is anchor-bound and the mapping is exact", () => {
    const entity = makeEntity({
      identity_basis: "anchor_exact",
      binding_status: "exact",
      binding_reasons: ["anchor_exact_match"],
      anchor_set: { anchor_ids: ["a".repeat(32)], binding_status: "exact", count: 1 },
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
