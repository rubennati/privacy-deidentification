// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
