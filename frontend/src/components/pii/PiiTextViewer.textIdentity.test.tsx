// @vitest-environment jsdom
// Regression coverage: highlight rendering must never change the displayed text buffer.
//
// A highlight split by an overlapping highlight used to reuse the highlight's own start offset as
// the React key for every fragment; the resulting duplicate sibling keys corrupted the rendered
// text during reconciliation (fragments duplicated/moved into unrelated lines). These tests pin
// the text-identity invariant across renders for unsorted, adjacent, overlapping, duplicate,
// partial, and invalid ranges — in both the raw and the canonical view.
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PiiTextViewer } from "./PiiTextViewer";
import type { AnchorBoundPiiHighlight, PiiHighlightView } from "../../lib/piiHighlights";

afterEach(() => {
  cleanup();
});

function highlight(
  id: string,
  type: string,
  start: number,
  end: number,
  {
    confidence = 0.85,
    reviewState = "accepted" as "accepted" | "kept" | "rejected",
    sourceName = "technical_raw_text" as PiiHighlightView,
  } = {},
): AnchorBoundPiiHighlight {
  return {
    entity_id: id,
    entity_type: type,
    identity_basis: "anchor_exact",
    source_entity_ids: [id],
    primary_source_entity_id: id,
    anchor_ids: [`anchor-${id}`],
    source_name: sourceName,
    start,
    end,
    binding_status: "exact",
    mapping_status: "exact",
    review_state: reviewState,
    needs_review: false,
    reason_codes: [],
    confidence,
  };
}

const RAW_TEXT =
  "Angebot Sanierungsbau\n" +
  "Bmst. Ing. Wolfgang Reithofer, Tel. +43 664 1234567\n" +
  "office@sanierungsbau-\nreithofer.at\n" +
  "1010 Wien";

const CANONICAL_TEXT =
  "Angebot Sanierungsbau — Kanonischer Lesetext\n" +
  "Bmst. Ing. Wolfgang Reithofer, Tel. +43 664 1234567\n" +
  "office@sanierungsbau-reithofer.at · 1010 Wien";

function renderedText(container: HTMLElement): string | null {
  const content = container.querySelector('[data-testid="pii-text-content"]');
  return content ? content.textContent : null;
}

describe("PiiTextViewer text identity", () => {
  it("renders raw text character-identically with overlapping cross-type highlights", () => {
    const highlights = [
      highlight("p1", "PERSON", 22, 51),
      highlight("t1", "PHONE_NUMBER", 36, 73, { confidence: 0.95 }),
      highlight("e1", "EMAIL_ADDRESS", 74, 108, { confidence: 0.9 }),
      highlight("o1", "ORGANIZATION", 8, 95, { confidence: 0.7 }),
    ];
    const { container } = render(<PiiTextViewer text={RAW_TEXT} highlights={highlights} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
  });

  it("preserves the raw buffer across re-renders that add, change, and remove highlights", () => {
    const person = highlight("p1", "PERSON", 22, 51);
    const phone = highlight("t1", "PHONE_NUMBER", 36, 73, { confidence: 0.95 });
    const email = highlight("e1", "EMAIL_ADDRESS", 74, 108, { confidence: 0.9 });
    const org = highlight("o1", "ORGANIZATION", 8, 95, { confidence: 0.7 });

    const { container, rerender } = render(<PiiTextViewer text={RAW_TEXT} highlights={[]} />);
    expect(renderedText(container)).toBe(RAW_TEXT);

    rerender(<PiiTextViewer text={RAW_TEXT} highlights={[person, phone, email, org]} />);
    expect(renderedText(container)).toBe(RAW_TEXT);

    // A decision refresh changes review state and list identity.
    rerender(
      <PiiTextViewer
        text={RAW_TEXT}
        highlights={[highlight("p1", "PERSON", 22, 51, { reviewState: "kept" }), phone, email, org]}
      />,
    );
    expect(renderedText(container)).toBe(RAW_TEXT);

    // A rejected entity disappears, then a re-decision brings it back.
    rerender(<PiiTextViewer text={RAW_TEXT} highlights={[phone, email, org]} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
    rerender(<PiiTextViewer text={RAW_TEXT} highlights={[person, phone, email, org]} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
  });

  it("preserves the canonical buffer and survives switching between text buffers", () => {
    const rawHighlights = [
      highlight("p1", "PERSON", 22, 51),
      highlight("t1", "PHONE_NUMBER", 36, 73, { confidence: 0.95 }),
    ];
    const canonicalHighlights = [
      highlight("p1", "PERSON", 45, 74, { sourceName: "canonical_reading_text" }),
      highlight("t1", "PHONE_NUMBER", 59, 96, {
        confidence: 0.95,
        sourceName: "canonical_reading_text",
      }),
    ];

    const { container, rerender } = render(
      <PiiTextViewer text={RAW_TEXT} highlights={rawHighlights} />,
    );
    expect(renderedText(container)).toBe(RAW_TEXT);

    rerender(<PiiTextViewer text={CANONICAL_TEXT} highlights={canonicalHighlights} />);
    expect(renderedText(container)).toBe(CANONICAL_TEXT);

    rerender(<PiiTextViewer text={RAW_TEXT} highlights={rawHighlights} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
  });

  it("does not duplicate text for duplicate and nested ranges", () => {
    const highlights = [
      highlight("a1", "PERSON", 22, 51),
      highlight("a2", "ORGANIZATION", 22, 51, { confidence: 0.6 }),
      highlight("a3", "PERSON", 27, 40, { confidence: 0.99 }),
    ];
    const { container, rerender } = render(
      <PiiTextViewer text={RAW_TEXT} highlights={highlights} />,
    );
    expect(renderedText(container)).toBe(RAW_TEXT);
    rerender(<PiiTextViewer text={RAW_TEXT} highlights={[...highlights].reverse()} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
  });

  it("keeps adjacent ranges intact and in order", () => {
    const highlights = [
      highlight("a1", "PERSON", 0, 7),
      highlight("a2", "LOCATION", 7, 21),
    ];
    const { container } = render(<PiiTextViewer text={RAW_TEXT} highlights={highlights} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
    const marks = [...container.querySelectorAll("mark")].map((mark) => mark.textContent);
    expect(marks).toEqual(["Angebot", " Sanierungsbau"]);
  });

  it("drops out-of-bounds and invalid ranges without corrupting the view, and says so", () => {
    const highlights = [
      highlight("ok", "PERSON", 22, 51),
      highlight("oob", "LOCATION", 0, RAW_TEXT.length + 50),
      highlight("neg", "LOCATION", -3, 4),
      highlight("empty", "LOCATION", 10, 10),
    ];
    const { container } = render(<PiiTextViewer text={RAW_TEXT} highlights={highlights} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
    // Exactly the valid highlight renders; the dropped ones are surfaced, not silent.
    expect(container.querySelectorAll("mark")).toHaveLength(1);
    const notice = container.querySelector('[data-testid="pii-invalid-highlight-notice"]');
    expect(notice?.textContent).toContain("3 Markierung(en)");
  });

  it("assigns each jump-target mark id exactly once even when a highlight is split", () => {
    const highlights = [
      highlight("p1", "PERSON", 22, 51),
      highlight("t1", "PHONE_NUMBER", 36, 45, { confidence: 0.99 }),
    ];
    const { container } = render(<PiiTextViewer text={RAW_TEXT} highlights={highlights} />);
    expect(renderedText(container)).toBe(RAW_TEXT);
    expect(container.querySelectorAll("#pii-mark-p1")).toHaveLength(1);
    expect(container.querySelectorAll("#pii-mark-t1")).toHaveLength(1);
  });
});
