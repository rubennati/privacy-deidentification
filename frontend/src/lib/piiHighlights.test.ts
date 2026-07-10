import { describe, expect, it } from "vitest";

import type { PiiEntityContractV1, ReviewReadyAnchorBoundPiiEntity } from "../api/piiEntityContract";
import type { PiiEntity } from "../api/workstations";
import {
  buildAnchorBoundHighlightSegments,
  buildAnchorBoundPiiHighlights,
  buildHighlightSegments,
} from "./piiHighlights";

function entity(
  id: string,
  text: string,
  start: number,
  end: number,
  score = 0.8,
  entityType = "PERSON",
): PiiEntity {
  return {
    id,
    entity_type: entityType,
    text,
    start_offset: start,
    end_offset: end,
    page_number: null,
    page_start_offset: null,
    page_end_offset: null,
    score,
    recognizer: "TestRecognizer",
  };
}

function anchorEntity(
  overrides: Partial<ReviewReadyAnchorBoundPiiEntity> = {},
): ReviewReadyAnchorBoundPiiEntity {
  const base: ReviewReadyAnchorBoundPiiEntity = {
    entity_id: "1".repeat(32),
    entity_type: "LOCATION",
    identity_basis: "anchor_exact",
    binding_status: "exact",
    binding_reasons: ["anchor_exact_match"],
    anchor_set: { anchor_ids: ["a".repeat(32)], binding_status: "exact", count: 1 },
    anchor_refs: [
      {
        anchor_id: "a".repeat(32),
        source_name: "technical_raw_text",
        source_range: { start: 0, end: 4 },
        binding_status: "exact",
        binding_role: "entity_span",
        confidence: 1,
        reason_codes: ["anchor_exact_match"],
      },
      {
        anchor_id: "a".repeat(32),
        source_name: "canonical_reading_text",
        source_range: { start: 7, end: 11 },
        binding_status: "exact",
        binding_role: "display_span",
        confidence: null,
        reason_codes: [],
      },
    ],
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
        binding_status: "exact",
        binding_reasons: ["anchor_exact_match"],
        provenance: null,
      },
    ],
    provenance: null,
    confidence: 0.9,
    value: "Wien",
    raw_text_range: { start: 0, end: 4, page_number: null, page_start: null, page_end: null },
    entity_group_id: "3".repeat(32),
    source_entity_ids: ["2".repeat(32)],
    mapping_status: "exact",
    canonical_reading_text_range: { start: 7, end: 11, projection_method: "offset_map" },
    review_state: "accepted",
    review_decision: null,
    decision_scope: null,
    display: {
      preferred_text_source: "canonical_reading_text",
      raw_highlight_range: { start: 0, end: 4 },
      canonical_highlight_range: { start: 7, end: 11 },
      display_label: "LOCATION",
      display_context_available: true,
      needs_review: false,
      review_reason_codes: [],
    },
    warnings: [],
  };
  return { ...base, ...overrides };
}

function contract(entities: ReviewReadyAnchorBoundPiiEntity[]): PiiEntityContractV1 {
  return {
    contract_version: "1.0",
    document_id: "d".repeat(32),
    pii_artifact_id: "p".repeat(32),
    package_id: "t".repeat(32),
    text_artifact_id: "t".repeat(32),
    reading_text_available: true,
    anchor_graph_available: true,
    anchor_graph_status: "valid",
    input_contract: null,
    overlap_resolution: null,
    entities,
    binding_summary: {
      total: entities.length,
      anchor_bound: entities.filter((item) => item.identity_basis !== "evidence_only").length,
      evidence_only: entities.filter((item) => item.identity_basis === "evidence_only").length,
      exact: entities.filter((item) => item.binding_status === "exact").length,
      partial: entities.filter((item) => item.binding_status === "partial").length,
      missing: entities.filter((item) => item.binding_status === "missing").length,
      ambiguous: entities.filter((item) => item.binding_status === "ambiguous").length,
      not_applicable: entities.filter((item) => item.binding_status === "not_applicable").length,
      total_entities: entities.length,
      anchor_bound_entities: entities.filter((item) => item.identity_basis !== "evidence_only")
        .length,
      evidence_only_entities: entities.filter((item) => item.identity_basis === "evidence_only")
        .length,
      exact_bound_entities: entities.filter((item) => item.binding_status === "exact").length,
      partial_bound_entities: entities.filter((item) => item.binding_status === "partial").length,
      ambiguous_bound_entities: entities.filter((item) => item.binding_status === "ambiguous")
        .length,
      entities_with_raw_range: entities.length,
      entities_with_canonical_range: entities.filter(
        (item) => item.display.canonical_highlight_range != null,
      ).length,
      entities_with_layout_range: entities.filter((item) =>
        item.anchor_refs.some(
          (ref) =>
            ref.source_name === "layout_text" &&
            ref.binding_role === "display_span" &&
            ref.source_range != null,
        ),
      ).length,
      missing_canonical_range_count: entities.filter(
        (item) => item.display.canonical_highlight_range == null,
      ).length,
      missing_layout_range_count: entities.filter(
        (item) =>
          !item.anchor_refs.some(
            (ref) =>
              ref.source_name === "layout_text" &&
              ref.binding_role === "display_span" &&
              ref.source_range != null,
          ),
      ).length,
      binding_reason_counts: {},
      warning_codes: [],
    },
    mapping_summary: {
      exact: entities.filter((item) => item.mapping_status === "exact").length,
      projected: entities.filter((item) => item.mapping_status === "projected").length,
      partial: entities.filter((item) => item.mapping_status === "partial").length,
      missing: entities.filter((item) => item.mapping_status === "missing").length,
      ambiguous: entities.filter((item) => item.mapping_status === "ambiguous").length,
      not_applicable: entities.filter((item) => item.mapping_status === "not_applicable").length,
    },
    needs_review_count: entities.filter((item) => item.display.needs_review).length,
  };
}

describe("buildHighlightSegments", () => {
  it("marks a simple entity", () => {
    expect(buildHighlightSegments("Hallo Anna!", [entity("a", "Anna", 6, 10)])).toEqual([
      { kind: "text", text: "Hallo " },
      { kind: "entity", text: "Anna", entity: entity("a", "Anna", 6, 10) },
      { kind: "text", text: "!" },
    ]);
  });

  it("sorts and marks multiple entities", () => {
    const anna = entity("a", "Anna", 0, 4);
    const wien = entity("b", "Wien", 8, 12, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna in Wien", [wien, anna])).toEqual([
      { kind: "entity", text: "Anna", entity: anna },
      { kind: "text", text: " in " },
      { kind: "entity", text: "Wien", entity: wien },
    ]);
  });

  it("uses Unicode codepoints when an emoji precedes an entity", () => {
    const anna = entity("a", "Anna", 2, 6);
    expect(buildHighlightSegments("🙂 Anna", [anna])).toEqual([
      { kind: "text", text: "🙂 " },
      { kind: "entity", text: "Anna", entity: anna },
    ]);
  });

  it("ignores invalid offsets", () => {
    expect(buildHighlightSegments("Anna", [entity("a", "Anna", -1, 3)])).toEqual([
      { kind: "text", text: "Anna" },
    ]);
  });

  it("ignores entity text mismatches", () => {
    expect(buildHighlightSegments("Anna", [entity("a", "Anne", 0, 4)])).toEqual([
      { kind: "text", text: "Anna" },
    ]);
  });

  it("prefers the higher score for overlapping entities", () => {
    const low = entity("low", "Anna", 0, 4, 0.5);
    const high = entity("high", "Anna Wien", 0, 9, 0.9, "LOCATION");
    const segments = buildHighlightSegments("Anna Wien", [low, high]);
    expect(segments).toEqual([{ kind: "entity", text: "Anna Wien", entity: high }]);
  });

  it("prefers the longer entity when overlapping scores match", () => {
    const short = entity("short", "Anna", 0, 4, 0.8);
    const long = entity("long", "Anna Wien", 0, 9, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna Wien", [short, long])).toEqual([
      { kind: "entity", text: "Anna Wien", entity: long },
    ]);
  });

  it("uses entity type and id as deterministic final tie breakers", () => {
    const personB = entity("b", "Anna", 0, 4, 0.8, "PERSON");
    const personA = entity("a", "Anna", 0, 4, 0.8, "PERSON");
    const location = entity("z", "Anna", 0, 4, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna", [personB, personA, location])).toEqual([
      { kind: "entity", text: "Anna", entity: location },
    ]);
    expect(buildHighlightSegments("Anna", [personB, personA])).toEqual([
      { kind: "entity", text: "Anna", entity: personA },
    ]);
  });

  describe("review status", () => {
    it("excludes a rejected (false-positive) entity from the highlighted segments", () => {
      const anna = entity("a", "Anna", 0, 4);
      const segments = buildHighlightSegments("Anna in Wien", [anna], { a: "rejected" });
      expect(segments).toEqual([{ kind: "text", text: "Anna in Wien" }]);
    });

    it("attaches the resolved review status to an accepted/kept entity's segment", () => {
      const anna = entity("a", "Anna", 0, 4);
      const accepted = buildHighlightSegments("Anna", [anna], { a: "accepted" });
      expect(accepted).toEqual([{ kind: "entity", text: "Anna", entity: anna, reviewStatus: "accepted" }]);

      const kept = buildHighlightSegments("Anna", [anna], { a: "kept" });
      expect(kept).toEqual([{ kind: "entity", text: "Anna", entity: anna, reviewStatus: "kept" }]);
    });

    it("renders unresolved entities exactly as before (no status map)", () => {
      const anna = entity("a", "Anna", 0, 4);
      expect(buildHighlightSegments("Anna", [anna])).toEqual([
        { kind: "entity", text: "Anna", entity: anna },
      ]);
      expect(buildHighlightSegments("Anna", [anna], {})).toEqual([
        { kind: "entity", text: "Anna", entity: anna },
      ]);
    });

    it("only excludes the rejected entity, letting an accepted duplicate-span sibling stand", () => {
      const rejected = entity("a", "Anna", 0, 4, 0.9);
      const accepted = entity("b", "Anna", 0, 4, 0.5);
      const segments = buildHighlightSegments("Anna", [rejected, accepted], {
        a: "rejected",
        b: "accepted",
      });
      expect(segments).toEqual([
        { kind: "entity", text: "Anna", entity: accepted, reviewStatus: "accepted" },
      ]);
    });
  });
});

describe("buildAnchorBoundPiiHighlights", () => {
  it("builds raw and canonical highlights from one anchor-bound identity", () => {
    const model = buildAnchorBoundPiiHighlights(contract([anchorEntity()]));

    expect(model.byView.technical_raw_text).toMatchObject([
      { entity_id: "1".repeat(32), entity_type: "LOCATION", start: 0, end: 4 },
    ]);
    expect(model.byView.canonical_reading_text).toMatchObject([
      { entity_id: "1".repeat(32), entity_type: "LOCATION", start: 7, end: 11 },
    ]);
  });

  it("renders raw and canonical highlights as the same entity identity across views", () => {
    const model = buildAnchorBoundPiiHighlights(contract([anchorEntity()]));
    const [raw] = model.byView.technical_raw_text;
    const [canonical] = model.byView.canonical_reading_text;

    // One anchor-bound entity powers both views: same entity id and type, view-specific ranges.
    expect(raw.entity_id).toBe(canonical.entity_id);
    expect(raw.entity_type).toBe(canonical.entity_type);
    expect(raw.source_name).toBe("technical_raw_text");
    expect(canonical.source_name).toBe("canonical_reading_text");
    expect(raw.anchor_ids).toEqual(canonical.anchor_ids);
    // The frontend renders the contract-supplied ranges verbatim; it does not re-derive them.
    expect({ start: raw.start, end: raw.end }).toEqual({ start: 0, end: 4 });
    expect({ start: canonical.start, end: canonical.end }).toEqual({ start: 7, end: 11 });
  });

  it("builds layout highlights only from layout anchor refs", () => {
    const model = buildAnchorBoundPiiHighlights(
      contract([
        anchorEntity({
          anchor_refs: [
            ...anchorEntity().anchor_refs,
            {
              anchor_id: "a".repeat(32),
              source_name: "layout_text",
              source_range: { start: 2, end: 6 },
              binding_status: "exact",
              binding_role: "display_span",
              confidence: null,
              reason_codes: [],
            },
          ],
        }),
      ]),
    );

    expect(model.byView.layout_text).toMatchObject([
      { entity_id: "1".repeat(32), source_name: "layout_text", start: 2, end: 6 },
    ]);
    expect(model.summary.missing_layout_count).toBe(0);
  });

  it("keeps evidence-only fallback raw highlights but marks the fallback state", () => {
    const evidenceOnly = anchorEntity({
      identity_basis: "evidence_only",
      binding_status: "missing",
      binding_reasons: ["anchor_missing", "detection_evidence_only"],
      anchor_set: { anchor_ids: [], binding_status: "missing", count: 0 },
      anchor_refs: [],
      mapping_status: "missing",
      canonical_reading_text_range: null,
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
    });

    const model = buildAnchorBoundPiiHighlights(contract([evidenceOnly]));

    expect(model.byView.technical_raw_text[0]).toMatchObject({
      entity_id: "1".repeat(32),
      identity_basis: "evidence_only",
      binding_status: "missing",
      needs_review: true,
    });
    expect(model.byView.canonical_reading_text).toEqual([]);
    expect(model.summary.evidence_only_count).toBe(1);
    expect(model.summary.missing_binding_count).toBe(1);
    expect(model.summary.missing_canonical_count).toBe(1);
    expect(model.summary.binding_reason_counts.anchor_missing).toBe(1);
    expect(model.summary.warning_codes).toContain("anchor_missing");
  });

  it("does not invent canonical highlights for missing, partial, or ambiguous mappings", () => {
    const entities = (["missing", "partial", "ambiguous"] as const).map((mapping_status, index) =>
      anchorEntity({
        entity_id: `${index + 1}`.repeat(32),
        mapping_status,
        canonical_reading_text_range: null,
        display: {
          preferred_text_source: "technical_raw_text",
          raw_highlight_range: { start: index * 5, end: index * 5 + 4 },
          canonical_highlight_range: null,
          display_label: "LOCATION",
          display_context_available: false,
          needs_review: true,
          review_reason_codes: [`canonical_mapping_${mapping_status}`],
        },
      }),
    );

    const model = buildAnchorBoundPiiHighlights(contract(entities));

    expect(model.byView.technical_raw_text).toHaveLength(3);
    expect(model.byView.canonical_reading_text).toEqual([]);
    expect(model.summary.missing_canonical_count).toBe(1);
    expect(model.summary.partial_canonical_count).toBe(1);
    expect(model.summary.ambiguous_canonical_count).toBe(1);
  });

  it("uses contract ranges instead of globally highlighting repeated words by value", () => {
    const model = buildAnchorBoundPiiHighlights(contract([anchorEntity()]));
    const segments = buildAnchorBoundHighlightSegments(
      "Wien und Wien",
      model.byView.technical_raw_text,
    );

    expect(segments.filter((segment) => segment.kind === "entity")).toHaveLength(1);
  });

  it("does not copy private values into highlight metadata", () => {
    const model = buildAnchorBoundPiiHighlights(contract([anchorEntity({ value: "Secret Value" })]));
    const metadata = JSON.stringify(model.byView);

    expect(metadata).not.toContain("Secret Value");
    expect(metadata).not.toContain("Wien");
  });
});
