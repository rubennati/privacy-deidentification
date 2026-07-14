import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { PiiManualAddition } from "../../api/piiReview";
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
  byView: {
    technical_raw_text: [
      { ...highlightModel.byView.technical_raw_text[0], review_state: "rejected" },
    ],
    canonical_reading_text: [
      { ...highlightModel.byView.canonical_reading_text[0], review_state: "rejected" },
    ],
    layout_text: [],
  },
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
  manualAdditions: readonly PiiManualAddition[] = [],
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
      manualAdditions={manualAdditions}
    />,
  );
}

function manualAddition(overrides: Partial<PiiManualAddition> = {}): PiiManualAddition {
  // Deliberately non-overlapping with `highlightModel`'s own 6–10 (raw) / 17–21 (canonical) entity,
  // so these tests observe the manual-addition mark in isolation from highlight overlap priority.
  return {
    addition_id: "d".repeat(32),
    entity_type: "LOCATION",
    canonical_start: 0,
    canonical_end: 4,
    text_artifact_id: "e".repeat(32),
    raw_start: 0,
    raw_end: 5,
    raw_projection_status: "exact",
    origin: "human",
    note: null,
    created_at: "2026-07-11T10:00:00Z",
    review_status: "accepted",
    review_decision: null,
    ...overrides,
  };
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

  it("replaces the technical hover title with a plain-language one when meta is hidden (user view)", () => {
    const html = render("raw", null, false);

    // The highlight itself remains; the technical enum/score tooltip becomes a readable label.
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).not.toContain('title="LOCATION');
    expect(html).toContain('title="Ort · Wird pseudonymisiert"');
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
    // User view uses plain toggle labels; the technical names stay dev-view-only.
    expect(html).toContain("Lesetext");
    expect(html).toContain("Technische Ansicht");
    expect(html).not.toContain("Kanonischer Lesetext");
    expect(html).not.toContain("Technischer Rohtext");
    expect(html).not.toContain("Layout-Text</button>");
  });

  it("hides the technical diagnostics hints in user view", () => {
    const html = render(
      "reading",
      null,
      false,
      "Lesefreundliches Wien",
      false,
      evidenceOnlyHighlightModel,
    );

    expect(html).not.toContain("anchor-gebundenen Entity-Vertrag");
    expect(html).not.toContain("lesefreundliche Hauptansicht");
    expect(html).not.toContain("Anchor-Bindung");
    expect(html).not.toContain("Evidence-only Fallback");
    expect(html).not.toContain("Kanonische Ranges fehlen");
    // The one reader-relevant fact stays, in plain language: some marks exist only in raw view.
    expect(html).toContain("nur in der technischen Ansicht sichtbar");
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

  it("renders a rejected (false-positive) entity as a dismissed ghost in raw mode", () => {
    // The decision stays visible and revisable in place: no fill, dashed frame, still a mark.
    const html = renderWithReview("raw", rejectedHighlightModel);
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain('data-review-state="rejected"');
    expect(html).toContain("bg-transparent");
    expect(html).not.toContain("bg-emerald-200");
  });

  it("renders a rejected (false-positive) entity as a dismissed ghost in reading mode too", () => {
    const html = renderWithReview("reading", rejectedHighlightModel);
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain('data-review-state="rejected"');
    expect(html).not.toContain("bg-emerald-200");
  });

  it("keeps highlighting a kept entity distinguishably in both modes", () => {
    // "kept" (not pseudonymized): no fill, solid frame — still visible, still clickable.
    const raw = renderWithReview("raw", keptHighlightModel);
    const reading = renderWithReview("reading", keptHighlightModel);
    expect(raw).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(reading).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(raw).toContain("ring-slate-400");
    expect(reading).toContain("ring-slate-400");
    expect(raw).not.toContain("bg-emerald-200");
  });

  it("renders exactly as before when no review data has loaded (legacy/missing)", () => {
    const withoutMap = renderWithReview("raw", highlightModel);
    expect(withoutMap).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(withoutMap).not.toContain("bg-transparent");
  });

  it("renders the default accepted (pseudonymize) status as a plain colored highlight", () => {
    // "accepted" is the assumed default for every detected entity, so it must look like a plain
    // highlight — only "kept"/"rejected" get a distinguishing style.
    const html = renderWithReview("raw", highlightModel);
    expect(html).toContain(`<mark id="pii-mark-${occurrenceId}"`);
    expect(html).toContain("bg-emerald-200");
    expect(html).not.toContain("bg-transparent");
  });

  it("makes a highlight clickable only when a selection handler is provided", () => {
    const withHandler = renderWithReview("raw", highlightModel, vi.fn());
    const withoutHandler = renderWithReview("raw", highlightModel);
    expect(withHandler).toContain("cursor-pointer");
    expect(withoutHandler).not.toContain("cursor-pointer");
  });

  it("preserves both identities from partially overlapping contract ranges", () => {
    const secondEntityId = "2".repeat(32);
    const secondOccurrenceId = "c".repeat(32);
    const first = highlightModel.byView.technical_raw_text[0];
    const overlappingModel: AnchorBoundPiiHighlightModel = {
      ...highlightModel,
      byView: {
        ...highlightModel.byView,
        technical_raw_text: [
          first,
          {
            ...first,
            entity_id: secondEntityId,
            source_entity_ids: [secondOccurrenceId],
            primary_source_entity_id: secondOccurrenceId,
            anchor_ids: ["d".repeat(32)],
            start: 3,
            end: 8,
            confidence: 0.8,
          },
        ],
      },
      summary: { ...highlightModel.summary, total_entities: 2 },
    };

    const html = renderWithReview("raw", overlappingModel, vi.fn());

    expect(html).toContain(`data-entity-id="${entityId}"`);
    expect(html).toContain(`data-entity-id="${secondEntityId}"`);
    expect(html).toContain(`data-entity-ids="${entityId} ${secondEntityId}"`);
    expect(html).toContain(`pii-mark-${occurrenceId}`);
    expect(html).toContain(`pii-mark-${secondOccurrenceId}`);
  });

  it("highlights a manual addition in the canonical reading-text view (PII L14, ADR-0035)", () => {
    const html = render(
      "reading",
      "Wien      Graz",
      undefined,
      "Lesefreundliches Wien",
      true,
      highlightModel,
      [manualAddition()],
    );

    expect(html).toContain(`<mark id="pii-mark-${"d".repeat(32)}"`);
    expect(html).toContain("ring-sky-500");
  });

  it("highlights a manual addition in raw view only when the reverse projection is exact", () => {
    const exact = render(
      "raw",
      null,
      undefined,
      "Lesefreundliches Wien",
      true,
      highlightModel,
      [manualAddition({ raw_projection_status: "exact" })],
    );
    expect(exact).toContain(`<mark id="pii-mark-${"d".repeat(32)}"`);

    const unmapped = render(
      "raw",
      null,
      undefined,
      "Lesefreundliches Wien",
      true,
      highlightModel,
      [manualAddition({ raw_projection_status: "unmapped", raw_start: null, raw_end: null })],
    );
    expect(unmapped).not.toContain(`pii-mark-${"d".repeat(32)}`);
  });

  it("shows a rejected manual addition as a dismissed ghost, not a colored highlight", () => {
    const html = render(
      "reading",
      null,
      undefined,
      "Lesefreundliches Wien",
      true,
      highlightModel,
      [manualAddition({ review_status: "rejected" })],
    );

    expect(html).toContain(`pii-mark-${"d".repeat(32)}`);
    expect(html).toContain('data-review-state="rejected"');
    // The manual-origin ring marks a pending pseudonymize-bound addition; a decided one uses the
    // shared state look instead.
    expect(html).not.toContain("ring-sky-500");
  });
});
