import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PiiValidationTransparency } from "./PiiValidationTransparency";

describe("PiiValidationTransparency", () => {
  it("renders stored aggregate counts and deterministic reason-code ordering", () => {
    const html = renderToStaticMarkup(
      <PiiValidationTransparency
        validation={{
          enabled: true,
          kept: 7,
          dropped: 2,
          score_down: 1,
          dropped_by_reason: { FUNCTION_WORD_ONLY: 1, GENERIC_DOCUMENT_WORD: 1 },
          score_down_by_reason: { MISSING_REQUIRED_CONTEXT: 1 },
        }}
      />,
    );

    expect(html).toContain("Beibehalten");
    expect(html).toContain("7");
    expect(html).toContain("Verworfen");
    expect(html).toContain("Abgewertet");
    expect(html).toContain("MISSING_REQUIRED_CONTEXT");
    expect(html.indexOf("FUNCTION_WORD_ONLY")).toBeLessThan(
      html.indexOf("GENERIC_DOCUMENT_WORD"),
    );
  });

  it("explains legacy artifacts without a stored validation summary", () => {
    const html = renderToStaticMarkup(<PiiValidationTransparency validation={null} />);
    expect(html).toContain("ältere PII-Ergebnis");
  });

  it("distinguishes a disabled validation run", () => {
    const html = renderToStaticMarkup(
      <PiiValidationTransparency
        validation={{
          enabled: false,
          kept: 0,
          dropped: 0,
          score_down: 0,
          dropped_by_reason: {},
          score_down_by_reason: {},
        }}
      />,
    );
    expect(html).toContain("deaktiviert");
    expect(html).not.toContain("Beibehalten");
  });
});
