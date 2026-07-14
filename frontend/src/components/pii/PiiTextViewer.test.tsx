// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnchorBoundPiiHighlight } from "../../lib/piiHighlights";
import { PiiTextViewer } from "./PiiTextViewer";

afterEach(() => {
  cleanup();
});

/**
 * Integration coverage for the real selection → callback wiring (PII L14, ADR-0035) — the part
 * `getCharacterOffsetsFromSelection`'s own unit tests (`lib/textSelection.test.ts`) can't reach,
 * since it needs an actually-mounted component and a real `mouseup` DOM event.
 */
describe("PiiTextViewer text selection", () => {
  it("calls onTextSelected with the selection's character offsets on mouseup", () => {
    const onTextSelected = vi.fn();
    const { container } = render(
      <PiiTextViewer text="Hallo Wien" highlights={[]} onTextSelected={onTextSelected} />,
    );
    const root = container.firstChild as HTMLElement;
    const textNode = root.firstChild!.firstChild!;

    const range = document.createRange();
    range.setStart(textNode, 6);
    range.setEnd(textNode, 10);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    fireEvent.mouseUp(root);

    expect(onTextSelected).toHaveBeenCalledTimes(1);
    expect(onTextSelected).toHaveBeenCalledWith({ start: 6, end: 10 });
  });

  it("does not call onTextSelected for a collapsed selection", () => {
    const onTextSelected = vi.fn();
    const { container } = render(
      <PiiTextViewer text="Hallo Wien" highlights={[]} onTextSelected={onTextSelected} />,
    );
    const root = container.firstChild as HTMLElement;
    const textNode = root.firstChild!.firstChild!;

    const range = document.createRange();
    range.setStart(textNode, 3);
    range.setEnd(textNode, 3);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    fireEvent.mouseUp(root);

    expect(onTextSelected).not.toHaveBeenCalled();
  });

  it("never throws on mouseup when onTextSelected is not provided", () => {
    const { container } = render(<PiiTextViewer text="Hallo Wien" highlights={[]} />);
    const root = container.firstChild as HTMLElement;

    expect(() => fireEvent.mouseUp(root)).not.toThrow();
  });
});

describe("PiiTextViewer keyboard access", () => {
  const highlight: AnchorBoundPiiHighlight = {
    entity_id: "1".repeat(32),
    entity_type: "LOCATION",
    identity_basis: "anchor_exact",
    source_entity_ids: ["a".repeat(32)],
    primary_source_entity_id: "a".repeat(32),
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
  };

  it("activates a decidable highlight with Enter and Space, but not other keys", () => {
    const onSelectEntity = vi.fn();
    const { container } = render(
      <PiiTextViewer text="Hallo Wien" highlights={[highlight]} onSelectEntity={onSelectEntity} />,
    );
    const mark = container.querySelector("mark")!;

    expect(mark.getAttribute("role")).toBe("button");
    expect(mark.getAttribute("tabindex")).toBe("0");
    expect(mark.getAttribute("aria-label")).toContain("Ort");

    fireEvent.keyDown(mark, { key: "Enter" });
    fireEvent.keyDown(mark, { key: " " });
    fireEvent.keyDown(mark, { key: "a" });

    expect(onSelectEntity).toHaveBeenCalledTimes(2);
    expect(onSelectEntity).toHaveBeenCalledWith("a".repeat(32), mark);
  });

  it("stays a plain non-focusable mark without a selection handler", () => {
    const { container } = render(<PiiTextViewer text="Hallo Wien" highlights={[highlight]} />);
    const mark = container.querySelector("mark")!;

    expect(mark.getAttribute("role")).toBeNull();
    expect(mark.getAttribute("tabindex")).toBeNull();
  });
});
