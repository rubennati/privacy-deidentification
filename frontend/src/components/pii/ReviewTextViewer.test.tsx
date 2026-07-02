import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { PiiEntity } from "../../api/workstations";
import { ReviewTextViewer } from "./ReviewTextViewer";

const entity: PiiEntity = {
  id: "a".repeat(32),
  entity_type: "LOCATION",
  text: "Wien",
  start_offset: 6,
  end_offset: 10,
  page_number: 1,
  page_start_offset: 6,
  page_end_offset: 10,
  score: 0.9,
  recognizer: "FakeRecognizer",
};

function render(
  mode: "canonical" | "layout",
  layoutText: string | null | undefined,
  showEntityMeta?: boolean,
): string {
  return renderToStaticMarkup(
    <ReviewTextViewer
      canonicalText="Hallo Wien"
      layoutText={layoutText}
      entities={[entity]}
      mode={mode}
      onModeChange={vi.fn()}
      showEntityMeta={showEntityMeta}
    />,
  );
}

describe("ReviewTextViewer", () => {
  it("offers both display modes when layout text is present", () => {
    const html = render("canonical", "Wien      Graz");

    expect(html).toContain("Canonical text");
    expect(html).toContain("Layout text");
    expect(html).toContain('aria-pressed="true"');
  });

  it("shows canonical text with the existing PII highlights", () => {
    const html = render("canonical", "Wien      Graz");

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).not.toContain("Layout text is for reading/review only");
  });

  it("renders the extracted text inside a centered A4 paper sheet", () => {
    const html = render("canonical", null);

    // The A4-width, centered paper container is the review's primary document surface.
    expect(html).toContain("max-w-[210mm]");
    expect(html).toContain("mx-auto");
  });

  it("exposes entity type/score as a hover title by default (dev view)", () => {
    const html = render("canonical", null);

    expect(html).toContain('title="LOCATION');
  });

  it("suppresses the entity hover title when meta is hidden (user view)", () => {
    const html = render("canonical", null, false);

    // The highlight itself remains; only the technical hover metadata is gone.
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).not.toContain('title="LOCATION');
  });

  it("shows layout text as unhighlighted plain text with the canonical-offset notice", () => {
    const html = render("layout", "Wien      Graz");

    expect(html).toContain("Wien      Graz");
    expect(html).toContain("Layout text is for reading/review only. PII highlights use canonical text.");
    expect(html).not.toContain("<mark");
  });

  it.each([
    ["null layout", null],
    ["legacy artifact without the field", undefined],
  ])("falls back cleanly to canonical text for %s", (_label, layoutText) => {
    const html = render("layout", layoutText);

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).not.toContain("Canonical text</button>");
    expect(html).not.toContain("Layout text</button>");
    expect(html).not.toContain("Layout text is for reading/review only");
  });
});
