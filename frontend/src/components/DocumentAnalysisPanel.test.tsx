import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DocumentAnalysisPanel } from "./DocumentAnalysisPanel";
import type { AnalysisStep } from "../lib/documentAnalysis";

interface Props {
  step: AnalysisStep;
  hasCurrentAnalysis: boolean;
  error: { message: string; correlationId: string | null } | null;
}

function render({ step, hasCurrentAnalysis, error }: Props): string {
  return renderToStaticMarkup(
    <DocumentAnalysisPanel
      step={step}
      hasCurrentAnalysis={hasCurrentAnalysis}
      error={error}
      onRun={vi.fn()}
    />,
  );
}

describe("DocumentAnalysisPanel", () => {
  it("offers the first analysis when none is current", () => {
    const html = render({ step: "idle", hasCurrentAnalysis: false, error: null });

    expect(html).toContain("Dokument analysieren");
    expect(html).not.toContain("Analyse erneut ausführen");
    // Not running → the button is enabled (no disabled attribute).
    expect(html).not.toContain('disabled=""');
  });

  it("offers a re-run when a current analysis already exists", () => {
    const html = render({ step: "done", hasCurrentAnalysis: true, error: null });

    expect(html).toContain("Analyse erneut ausführen");
    expect(html).not.toContain("Dokument analysieren");
  });

  it("disables the button and shows the busy label while running", () => {
    const html = render({ step: "ocr", hasCurrentAnalysis: false, error: null });

    expect(html).toContain('disabled=""');
    expect(html).toContain("Analyse läuft …");
  });

  it.each([
    ["audit", "Dokument wird vorbereitet …"],
    ["ocr", "Text wird extrahiert …"],
    ["pii", "Sensible Daten werden erkannt …"],
  ])("shows the %s progress label while running", (step, label) => {
    const html = render({
      step: step as AnalysisStep,
      hasCurrentAnalysis: false,
      error: null,
    });

    expect(html).toContain(label);
  });

  it("renders only the safe error message with the existing error style", () => {
    const html = render({
      step: "idle",
      hasCurrentAnalysis: false,
      error: { message: "Keine Verbindung zum Server.", correlationId: "abc-123" },
    });

    expect(html).toContain("Keine Verbindung zum Server.");
    expect(html).toContain("Referenz: abc-123");
    // Reuses the existing StatusNotice error styling rather than a bespoke block.
    expect(html).toContain("text-red-800");
  });

  it("hides a previous error while a new run is in progress", () => {
    const html = render({
      step: "audit",
      hasCurrentAnalysis: false,
      error: { message: "Frühere Fehlermeldung", correlationId: null },
    });

    expect(html).not.toContain("Frühere Fehlermeldung");
  });
});
