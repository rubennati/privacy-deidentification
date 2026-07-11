import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AddPiiManualEntity } from "./AddPiiManualEntity";

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node);
}

describe("AddPiiManualEntity", () => {
  it("renders nothing without a current selection", () => {
    const html = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={["PERSON", "LOCATION"]}
        readingText="Hans Mueller wohnt in Wien."
        selection={null}
        onAdded={vi.fn()}
      />,
    );

    expect(html).toBe("");
  });

  it("shows a read-only preview of the current selection and the configured entity types", () => {
    const html = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={["PERSON", "LOCATION"]}
        readingText="Hans Mueller wohnt in Wien."
        selection={{ start: 22, end: 26 }}
        onAdded={vi.fn()}
      />,
    );

    expect(html).toContain("Wien");
    expect(html).toContain(">PERSON<");
    expect(html).toContain(">LOCATION<");
    expect(html).toContain("Als PII hinzufügen");
  });

  it("truncates a very long selection preview", () => {
    const longText = "A".repeat(200);
    const html = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={["PERSON"]}
        readingText={longText}
        selection={{ start: 0, end: 200 }}
        onAdded={vi.fn()}
      />,
    );

    expect(html).toContain("…");
    expect(html).not.toContain("A".repeat(150));
  });

  it("disables the submit control when no entity type is configured", () => {
    const html = render(
      <AddPiiManualEntity
        documentId="doc-1"
        entityTypes={[]}
        readingText="Hans Mueller wohnt in Wien."
        selection={{ start: 22, end: 26 }}
        onAdded={vi.fn()}
      />,
    );

    expect(html).toContain("disabled=\"\"");
  });
});
