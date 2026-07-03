import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { PiiReviewResult } from "../../api/piiReview";
import { PiiReviewGroupList } from "./PiiReviewGroupList";

function baseReview(overrides: Partial<PiiReviewResult> = {}): PiiReviewResult {
  return {
    document_id: "doc-1",
    artifact_id: "art-1",
    groups: [
      {
        entity_group_id: "g".repeat(32),
        entity_type: "LOCATION",
        occurrence_ids: ["o1".padEnd(32, "0"), "o2".padEnd(32, "0")],
        occurrence_count: 2,
        normalized_fingerprint: "f".repeat(64),
        projection_summary: { exact_count: 1, partial_count: 0, unmapped_count: 1 },
        review_status: "pending",
        review_decision: null,
        updated_at: null,
      },
    ],
    occurrences: [
      {
        occurrence_id: "o1".padEnd(32, "0"),
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
        review_status: "pending",
        review_decision: null,
        decision_scope: null,
      },
      {
        occurrence_id: "o2".padEnd(32, "0"),
        entity_type: "LOCATION",
        entity_group_id: "g".repeat(32),
        raw_start: 20,
        raw_end: 24,
        score: 0.8,
        recognizer: "FakeRecognizer",
        projection_status: "unmapped",
        projection_method: null,
        reading_start_offset: null,
        reading_end_offset: null,
        review_status: "pending",
        review_decision: null,
        decision_scope: null,
      },
    ],
    ...overrides,
  };
}

function render(review: PiiReviewResult | null): string {
  return renderToStaticMarkup(
    <PiiReviewGroupList documentId="doc-1" review={review} onReviewChanged={vi.fn()} />,
  );
}

describe("PiiReviewGroupList", () => {
  it("renders nothing for a legacy document without any review groups", () => {
    expect(render(null)).toBe("");
    expect(render(baseReview({ groups: [], occurrences: [] }))).toBe("");
  });

  it("renders the grouped entity type, occurrence count, and pending status", () => {
    const html = render(baseReview());
    expect(html).toContain("LOCATION");
    expect(html).toContain("2× erkannt");
    expect(html).toContain("Ausstehend");
  });

  it("shows the projection coverage summary", () => {
    const html = render(baseReview());
    expect(html).toContain("1 exakt");
    expect(html).toContain("0 teilweise");
    expect(html).toContain("1 nur Rohtext");
  });

  it("lists every decision option in the group-level select", () => {
    const html = render(baseReview());
    expect(html).toContain("Pseudonymisieren");
    expect(html).toContain("Beibehalten");
    expect(html).toContain("Ignorieren");
    expect(html).toContain("Kein PII (False Positive)");
  });

  it("reflects the current group decision as the selected option", () => {
    const html = render(
      baseReview({
        groups: [
          {
            ...baseReview().groups[0],
            review_status: "accepted",
            review_decision: "keep",
            updated_at: "2026-07-03T10:00:00Z",
          },
        ],
      }),
    );
    expect(html).toContain("Bestätigt");
    expect(html).toContain('<option value="keep" selected');
  });

  it("distinguishes rejected/ignored group status from pending/accepted", () => {
    const rejected = render(
      baseReview({
        groups: [{ ...baseReview().groups[0], review_status: "rejected", review_decision: "false_positive" }],
      }),
    );
    const ignored = render(
      baseReview({
        groups: [{ ...baseReview().groups[0], review_status: "ignored", review_decision: "ignore" }],
      }),
    );
    expect(rejected).toContain("Abgelehnt");
    expect(ignored).toContain("Ignoriert");
    expect(rejected).not.toContain("Ignoriert");
  });

  it("shows an expand control with the occurrence count and an occurrence-level override", () => {
    const html = render(baseReview());
    expect(html).toContain("Vorkommen anzeigen (2)");
    expect(html).toContain("Offset 0–4");
    expect(html).toContain("Offset 20–24");
    expect(html).toContain("Override …");
  });

  it("marks an occurrence-level override distinctly from the inherited group decision", () => {
    const review = baseReview();
    review.occurrences[0] = {
      ...review.occurrences[0],
      review_status: "rejected",
      review_decision: "false_positive",
      decision_scope: "occurrence",
    };
    const html = render(review);
    expect(html).toContain("individuell");
  });

  it("does not render an occurrence sub-list when a group has no matching occurrences (malformed data)", () => {
    const html = render(
      baseReview({
        occurrences: [],
      }),
    );
    // Still renders the group row itself without crashing.
    expect(html).toContain("LOCATION");
    expect(html).not.toContain("Vorkommen anzeigen");
  });
});
