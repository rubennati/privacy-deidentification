import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DocumentCard } from "./DocumentCard";

function render(): string {
  return renderToStaticMarkup(
    <StaticRouter location="/">
      <DocumentCard
        id="doc-1"
        filename="bericht.pdf"
        size={1024}
        uploadedAt="2026-07-03T08:00:00Z"
        onDelete={vi.fn()}
      />
    </StaticRouter>,
  );
}

describe("DocumentCard", () => {
  it("renders the ready status label with the existing badge styling", () => {
    const html = render();

    expect(html).toContain("Bereit");
    expect(html).not.toContain("Entgegengenommen");
    expect(html).toContain("bg-accent-soft");
    expect(html).toContain("text-accent-dark");
  });
});
