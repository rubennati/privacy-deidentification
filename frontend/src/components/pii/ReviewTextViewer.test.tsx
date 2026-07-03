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
  reading_start_offset: 17,
  reading_end_offset: 21,
  projection_status: "exact",
};

const LEGACY_READING_TEXT = Symbol("legacy-reading-text");

function render(
  mode: "reading" | "raw" | "layout",
  layoutText: string | null | undefined,
  showEntityMeta?: boolean,
  readingText: string | null | typeof LEGACY_READING_TEXT = "Lesefreundliches Wien",
  devMode = true,
  entities: readonly PiiEntity[] = [entity],
): string {
  return renderToStaticMarkup(
    <ReviewTextViewer
      rawText="Hallo Wien"
      readingText={readingText === LEGACY_READING_TEXT ? undefined : readingText}
      layoutText={layoutText}
      entities={entities}
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
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).not.toContain("PII-Markierungen verwenden derzeit");
  });

  it("shows canonical reading text with projected PII highlights", () => {
    const html = render("reading", "Wien      Graz");

    expect(html).toContain("Lesefreundliches ");
    expect(html).toContain(">Wien</mark>");
    expect(html).toContain("lesefreundliche Hauptansicht");
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).toContain("projizierte Lesetext-Offsets");
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
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
    expect(html).not.toContain('title="LOCATION');
  });

  it("shows layout text as unhighlighted plain text with the raw-offset notice", () => {
    const html = render("layout", "Wien      Graz");

    expect(html).toContain("Wien      Graz");
    expect(html).toContain("Layout-Text dient der Orientierung");
    expect(html).toContain("technischen Rohtext");
    expect(html).not.toContain("<mark");
  });

  it("falls back cleanly to technical raw text for null reading text", () => {
    const html = render("reading", null, undefined, null);

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
  });

  it("falls back cleanly for a legacy artifact without reading text", () => {
    const html = render("reading", null, undefined, LEGACY_READING_TEXT);

    expect(html).toContain("Hallo ");
    expect(html).toContain(`<mark id="pii-mark-${entity.id}"`);
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
    const unmapped = {
      ...entity,
      reading_start_offset: null,
      reading_end_offset: null,
      projection_status: "unmapped" as const,
    };
    const html = render("reading", null, undefined, "Lesefreundliches Wien", true, [unmapped]);

    expect(html).not.toContain("<mark");
    expect(html).toContain("nur im technischen Rohtext sichtbar");
  });

  it("ignores malformed projected offsets instead of crashing", () => {
    const malformed = { ...entity, reading_end_offset: 999 };
    const html = render("reading", null, undefined, "Lesefreundliches Wien", true, [malformed]);
    expect(html).not.toContain("<mark");
  });
});
