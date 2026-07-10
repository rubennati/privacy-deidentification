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
        review_status: "accepted",
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
        review_status: "accepted",
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
        review_status: "accepted",
        review_decision: null,
        decision_scope: null,
      },
    ],
    stale_decision_count: 0,
    has_stale_decisions: false,
    ...overrides,
  };
}

function render(review: PiiReviewResult | null, showTechnicalDetails?: boolean): string {
  return renderToStaticMarkup(
    <PiiReviewGroupList
      documentId="doc-1"
      review={review}
      onReviewChanged={vi.fn()}
      showTechnicalDetails={showTechnicalDetails}
    />,
  );
}

describe("PiiReviewGroupList", () => {
  it("renders nothing for a legacy document without any review groups", () => {
    expect(render(null)).toBe("");
    expect(render(baseReview({ groups: [], occurrences: [] }))).toBe("");
  });

  it("renders the grouped entity type, occurrence count, and default accepted status", () => {
    const html = render(baseReview());
    expect(html).toContain("LOCATION");
    expect(html).toContain("2× erkannt");
    expect(html).toContain("Wird pseudonymisiert");
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
    expect(html).toContain("Nicht pseudonymisieren");
    expect(html).toContain("Kein PII (False Positive)");
  });

  it("defaults the group-level select to pseudonymize when no explicit decision was made", () => {
    const html = render(baseReview());
    expect(html).toContain('<option value="pseudonymize" selected');
  });

  it("reflects the current group decision as the selected option", () => {
    const html = render(
      baseReview({
        groups: [
          {
            ...baseReview().groups[0],
            review_status: "kept",
            review_decision: "keep",
            updated_at: "2026-07-03T10:00:00Z",
          },
        ],
      }),
    );
    expect(html).toContain("Nicht pseudonymisiert");
    expect(html).toContain('<option value="keep" selected');
  });

  it("distinguishes rejected/kept group status from the accepted default", () => {
    const rejected = render(
      baseReview({
        groups: [{ ...baseReview().groups[0], review_status: "rejected", review_decision: "false_positive" }],
      }),
    );
    const kept = render(
      baseReview({
        groups: [{ ...baseReview().groups[0], review_status: "kept", review_decision: "keep" }],
      }),
    );
    expect(rejected).toContain("Abgelehnt");
    expect(kept).toContain("Nicht pseudonymisiert");
    expect(rejected).not.toContain("Nicht pseudonymisiert");
  });

  it("shows an expand control with the occurrence count and an occurrence-level override", () => {
    const html = render(baseReview());
    expect(html).toContain("Vorkommen anzeigen (2)");
    expect(html).toContain("Offset 0–4");
    expect(html).toContain("Offset 20–24");
    expect(html).toContain("Override …");
  });

  it("renders each occurrence's offset as a clickable jump-to-text control", () => {
    const html = render(baseReview());
    expect(html).toContain('title="Im extrahierten Text zu dieser Stelle springen"');
    // The offset text sits inside a <button>, not a plain <span>, so it is keyboard/click reachable.
    expect(html).toMatch(/<button[^>]*>Offset 0–4<\/button>/);
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

  describe("simplified mode (showTechnicalDetails=false, User View)", () => {
    it("still shows type, occurrence count, status, and the group decision select", () => {
      const html = render(baseReview(), false);
      expect(html).toContain("LOCATION");
      expect(html).toContain("2× erkannt");
      expect(html).toContain("Wird pseudonymisiert");
      expect(html).toContain("Pseudonymisieren");
    });

    it("hides the reading-text projection summary", () => {
      const html = render(baseReview(), false);
      expect(html).not.toContain("Lesetext-Abdeckung");
    });

    it("hides the per-occurrence expand control, offsets, and override select", () => {
      const html = render(baseReview(), false);
      expect(html).not.toContain("Vorkommen anzeigen");
      expect(html).not.toContain("Offset 0");
      expect(html).not.toContain("Override");
    });

    it("shows full technical detail by default when the prop is omitted", () => {
      const html = render(baseReview());
      expect(html).toContain("Lesetext-Abdeckung");
      expect(html).toContain("Vorkommen anzeigen");
    });
  });
});
