import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AnchorBoundPiiHighlightModel } from "../../lib/piiHighlights";
import { ReviewTextViewer } from "./ReviewTextViewer";

const entityId = "1".repeat(32);
const occurrenceId = "a".repeat(32);

const highlightModel: AnchorBoundPiiHighlightModel = {
  byView: {
    technical_raw_text: [
      {
        entity_id: entityId,
        entity_type: "LOCATION",
        identity_basis: "anchor_exact",
        source_entity_ids: [occurrenceId],
        primary_source_entity_id: occurrenceId,
        anchor_ids: ["b".repeat(32)],
        source_name: "technical_raw_text",
        start: 6,
        end: 10,
        binding_status: "exact",
        mapping_status: "exact",
        review_state: "accepted",
        needs_review: false,
        reason_codes: [],
        confidence: 0.9,
      },
    ],
    canonical_reading_text: [
      {
        entity_id: entityId,
        entity_type: "LOCATION",
        identity_basis: "anchor_exact",
        source_entity_ids: [occurrenceId],
        primary_source_entity_id: occurrenceId,
        anchor_ids: ["b".repeat(32)],
        source_name: "canonical_reading_text",
        start: 17,
        end: 21,
        binding_status: "exact",
        mapping_status: "exact",
        review_state: "accepted",
        needs_review: false,
        reason_codes: [],
        confidence: 0.9,
      },
    ],
    layout_text: [],
  },
  summary: {
    total_entities: 1,
    evidence_only_count: 0,
    missing_binding_count: 0,
    partial_binding_count: 0,
    ambiguous_binding_count: 0,
    missing_canonical_count: 0,
    ambiguous_canonical_count: 0,
    partial_canonical_count: 0,
    missing_layout_count: 1,
    binding_reason_counts: {},
    warning_codes: [],
  },
};

const unmappedHighlightModel: AnchorBoundPiiHighlightModel = {
  ...highlightModel,
  byView: {
    ...highlightModel.byView,
    canonical_reading_text: [],
  },
  summary: {
    ...highlightModel.summary,
    missing_canonical_count: 1,
  },
};

const evidenceOnlyHighlightModel: AnchorBoundPiiHighlightModel = {
  ...unmappedHighlightModel,
  byView: {
    ...unmappedHighlightModel.byView,
    technical_raw_text: [
      {
        ...highlightModel.byView.technical_raw_text[0],
        identity_basis: "evidence_only",
        binding_status: "missing",
        mapping_status: "missing",
        needs_review: true,
        reason_codes: ["anchor_binding_missing", "canonical_mapping_missing"],
      },
    ],
  },
  summary: {
    ...unmappedHighlightModel.summary,
    evidence_only_count: 1,
    missing_binding_count: 1,
    binding_reason_counts: { anchor_missing: 1, canonical_range_missing: 1 },
    warning_codes: ["anchor_missing", "canonical_range_missing"],
  },
};

const keptHighlightModel: AnchorBoundPiiHighlightModel = {
  ...highlightModel,
  byView: {
    technical_raw_text: [
      { ...highlightModel.byView.technical_raw_text[0], review_state: "kept" },
    ],
    canonical_reading_text: [
      { ...highlightModel.byView.canonical_reading_text[0], review_state: "kept" },
    ],
    layout_text: [],
  },
};

const rejectedHighlightModel: AnchorBoundPiiHighlightModel = {
  ...highlightModel,
  byView: { technical_raw_text: [], canonical_reading_text: [], layout_text: [] },
};

const layoutHighlightModel: AnchorBoundPiiHighlightModel = {
  ...highlightModel,
  byView: {
    ...highlightModel.byView,
    layout_text: [
      {
        ...highlightModel.byView.technical_raw_text[0],
        source_name: "layout_text",
        start: 0,
        end: 4,
      },
    ],
  },
};

const LEGACY_READING_TEXT = Symbol("legacy-reading-text");

function render(
  mode: "reading" | "raw" | "layout",
  layoutText: string | null | undefined,
  showEntityMeta?: boolean,
  readingText: string | null | typeof LEGACY_READING_TEXT = "Lesefreundliches Wien",
  devMode = true,
  model: AnchorBoundPiiHighlightModel = highlightModel,
): string {
  return renderToStaticMarkup(
    <ReviewTextViewer
      rawText="Hallo Wien"
      readingText={readingText === LEGACY_READING_TEXT ? undefined : readingText}
      layoutText={layoutText}
      highlightModel={model}
      mode={mode}
      onModeChange={vi.fn()}
      devMode={devMode}
      showEntityMeta={showEntityMeta}
    />,
  );
}

describe("ReviewTextViewer", () => {
  it("offers reading, raw, and layout modes in the dev view", () => {
    const html = render("reading", "Wien      Graz");

    expect(html).toContain("Kanonischer Lesetext");
    expect(html).toContain("Technischer Rohtext");
    expect(html).toContain("Layout-Text");
    expect(html).not.toContain("Canonical text");
    expect(html).toContain('aria-pressed="true"');
  });

  it("shows technical raw text with the existing PII highlights", () => {
    const html = render("raw", "Wien      Graz");

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain(`data-entity-id="${entityId}"`);
    expect(html).not.toContain("PII-Markierungen verwenden derzeit");
  });

  it("shows canonical reading text with projected PII highlights", () => {
    const html = render("reading", "Wien      Graz");

    expect(html).toContain("Lesefreundliches ");
    expect(html).toContain(">Wien</mark>");
    expect(html).toContain("lesefreundliche Hauptansicht");
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain("anchor-gebundenen Entity-Vertrag");
  });

  it("does not globally highlight repeated words without a contract range", () => {
    const html = render("reading", null, undefined, "Lesefreundliches Wien und Wien", true);

    expect(html.match(/<mark/g) ?? []).toHaveLength(1);
    expect(html).toContain(">Wien</mark>");
  });

  it("renders the extracted text inside a centered A4 paper sheet", () => {
    const html = render("reading", null);

    // The A4-width, centered paper container is the review's primary document surface.
    expect(html).toContain("max-w-[210mm]");
    expect(html).toContain("mx-auto");
  });

  it("exposes entity type/score as a hover title by default (dev view)", () => {
    const html = render("raw", null);

    expect(html).toContain('title="LOCATION');
  });

  it("suppresses the entity hover title when meta is hidden (user view)", () => {
    const html = render("raw", null, false);

    // The highlight itself remains; only the technical hover metadata is gone.
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).not.toContain('title="LOCATION');
  });

  it("shows layout text as plain text with an explicit missing-layout notice", () => {
    const html = render("layout", "Wien      Graz");

    expect(html).toContain("Wien      Graz");
    expect(html).toContain("Layout-Text dient der Orientierung");
    expect(html).toContain("keine Layout-Ranges");
    expect(html).toContain("Layout-Ranges fehlen");
    expect(html).not.toContain("<mark");
  });

  it("renders layout highlights when the contract provides layout ranges", () => {
    const html = render("layout", "Wien      Graz", undefined, "Lesefreundliches Wien", true, layoutHighlightModel);

    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain('data-source-name="layout_text"');
  });

  it("falls back cleanly to technical raw text for null reading text", () => {
    const html = render("reading", null, undefined, null);

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
  });

  it("falls back cleanly for a legacy artifact without reading text", () => {
    const html = render("reading", null, undefined, LEGACY_READING_TEXT);

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
  });

  it("defaults the user view to reading text and keeps raw-highlight access", () => {
    const html = render("reading", "Wien      Graz", false, "Lesefreundliches Wien", false);

    expect(html).toContain("Lesefreundliches ");
    expect(html).toContain(">Wien</mark>");
    expect(html).toContain("Kanonischer Lesetext");
    expect(html).toContain("Technischer Rohtext");
    expect(html).not.toContain("Layout-Text</button>");
  });

  it("does not highlight unmapped entities and shows the raw-only notice", () => {
    const html = render(
      "reading",
      null,
      undefined,
      "Lesefreundliches Wien",
      true,
      unmappedHighlightModel,
    );

    expect(html).not.toContain("<mark");
    expect(html).toContain("Fehlende Lesetext-Markierungen");
  });

  it("keeps the raw-only notice when projected and unmapped entities are mixed", () => {
    const mixed = {
      ...highlightModel,
      summary: { ...highlightModel.summary, missing_canonical_count: 1 },
    };
    const html = render("reading", null, undefined, "Lesefreundliches Wien", true, mixed);

    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain("Fehlende Lesetext-Markierungen");
  });

  it("ignores malformed projected offsets instead of crashing", () => {
    const malformed = {
      ...highlightModel,
      byView: {
        ...highlightModel.byView,
        canonical_reading_text: [
          { ...highlightModel.byView.canonical_reading_text[0], end: 999 },
        ],
      },
    };
    const html = render("reading", null, undefined, "Lesefreundliches Wien", true, malformed);
    expect(html).not.toContain("<mark");
  });

  it("shows evidence-only fallback state without crashing", () => {
    const html = render("raw", null, undefined, "Lesefreundliches Wien", true, evidenceOnlyHighlightModel);

    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain("Evidence-only Fallback");
    expect(html).toContain("Anchor-Bindung fehlt");
  });
});

describe("ReviewTextViewer review-decision awareness", () => {
  function renderWithReview(
    mode: "reading" | "raw",
    model: AnchorBoundPiiHighlightModel,
    onSelectEntity?: (entityId: string) => void,
  ): string {
    return renderToStaticMarkup(
      <ReviewTextViewer
        rawText="Hallo Wien"
        readingText="Lesefreundliches Wien"
        layoutText={null}
        highlightModel={model}
        mode={mode}
        onModeChange={vi.fn()}
        devMode
        showEntityMeta
        onSelectEntity={onSelectEntity}
      />,
    );
  }

  it("does not highlight a rejected (false-positive) entity in raw mode", () => {
    const html = renderWithReview("raw", rejectedHighlightModel);
    expect(html).not.toContain("<mark");
  });

  it("does not highlight a rejected (false-positive) entity in reading mode either", () => {
    const html = renderWithReview("reading", rejectedHighlightModel);
    expect(html).not.toContain("<mark");
  });

  it("keeps highlighting a kept entity distinguishably in both modes", () => {
    const raw = renderWithReview("raw", keptHighlightModel);
    const reading = renderWithReview("reading", keptHighlightModel);
    expect(raw).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(reading).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(raw).toContain("opacity-60");
    expect(reading).toContain("opacity-60");
  });

  it("renders exactly as before when no review data has loaded (legacy/missing)", () => {
    const withoutMap = renderWithReview("raw", highlightModel);
    expect(withoutMap).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(withoutMap).not.toContain("opacity-60");
  });

  it("renders the default accepted (pseudonymize) status with no special modifier", () => {
    // "accepted" is the assumed default for every detected entity, so it must look like a plain
    // highlight — only "kept" gets a distinguishing style.
    const html = renderWithReview("raw", highlightModel);
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).not.toContain("opacity-60");
    expect(html).not.toContain("ring-emerald");
  });

  it("makes a highlight clickable only when a selection handler is provided", () => {
    const withHandler = renderWithReview("raw", highlightModel, vi.fn());
    const withoutHandler = renderWithReview("raw", highlightModel);
    expect(withHandler).toContain("cursor-pointer");
    expect(withoutHandler).not.toContain("cursor-pointer");
  });
});
