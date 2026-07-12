import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { DocumentAnalysisState } from "../../lib/documentListStatus";
import { DocumentCard } from "./DocumentCard";

function render(analysis?: DocumentAnalysisState): string {
  return renderToStaticMarkup(
    <StaticRouter location="/">
      <DocumentCard
        id="doc-1"
        filename="bericht.pdf"
        size={1024}
        uploadedAt="2026-07-03T08:00:00Z"
        analysis={analysis}
        onDelete={vi.fn()}
      />
    </StaticRouter>,
  );
}

describe("DocumentCard", () => {
  it("shows the analyzed badge for an analyzed document", () => {
    const html = render("analyzed");

    expect(html).toContain("Analysiert");
    expect(html).toContain("bg-accent-soft");
    expect(html).not.toContain("Bereit");
  });

  it("shows running and not-analyzed states distinctly", () => {
    expect(render("running")).toContain("Analyse läuft");
    expect(render("none")).toContain("Nicht analysiert");
  });

  it("renders no badge while the analysis state is unknown", () => {
    const html = render(undefined);

    expect(html).not.toContain("analysis-badge");
    expect(html).toContain("bericht.pdf");
  });
});
