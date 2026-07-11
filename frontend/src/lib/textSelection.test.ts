// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { getCharacterOffsetsFromSelection } from "./textSelection";

/** Build a container the same shape PiiTextViewer renders: alternating <span>/<mark> fragments,
 *  never one contiguous text node — exactly the case a naive single-text-node offset read would
 *  get wrong. */
function buildFragmentedContainer(parts: string[]): HTMLElement {
  const container = document.createElement("div");
  for (const part of parts) {
    const el = document.createElement(part.startsWith("*") ? "mark" : "span");
    el.textContent = part.startsWith("*") ? part.slice(1) : part;
    container.appendChild(el);
  }
  document.body.appendChild(container);
  return container;
}

function selectAcross(
  startNode: Node,
  startOffset: number,
  endNode: Node,
  endOffset: number,
): Selection {
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  const selection = window.getSelection();
  if (!selection) {
    throw new Error("window.getSelection() unavailable in this environment");
  }
  selection.removeAllRanges();
  selection.addRange(range);
  return selection;
}

describe("getCharacterOffsetsFromSelection", () => {
  it("computes offsets for a selection within a single fragment", () => {
    const container = buildFragmentedContainer(["Hallo ", "*Wien", "!"]);
    const markText = container.querySelector("mark")!.firstChild!;
    const selection = selectAcross(markText, 0, markText, 4);

    expect(getCharacterOffsetsFromSelection(container, selection)).toEqual({ start: 6, end: 10 });
  });

  it("computes offsets for a selection spanning multiple sibling fragments", () => {
    // "Hans Mueller wohnt in " + "Wien" + ". Kontakt: " + "hans@example.com"
    const container = buildFragmentedContainer([
      "Hans Mueller wohnt in ",
      "*Wien",
      ". Kontakt: ",
      "*hans@example.com",
    ]);
    const startNode = container.childNodes[1].firstChild!; // "Wien" inside <mark>
    const endNode = container.childNodes[3].firstChild!; // the email inside the second <mark>
    const selection = selectAcross(startNode, 0, endNode, 4); // "Wien" ... "hans"

    const offsets = getCharacterOffsetsFromSelection(container, selection);
    const fullText = container.textContent ?? "";
    expect(offsets).not.toBeNull();
    expect(fullText.slice(offsets!.start, offsets!.end)).toBe("Wien. Kontakt: hans");
  });

  it("returns null for a collapsed selection", () => {
    const container = buildFragmentedContainer(["Hallo Wien"]);
    const textNode = container.firstChild!.firstChild!;
    const selection = selectAcross(textNode, 3, textNode, 3);

    expect(getCharacterOffsetsFromSelection(container, selection)).toBeNull();
  });

  it("returns null for a selection outside the given container", () => {
    const container = buildFragmentedContainer(["Hallo Wien"]);
    const outside = document.createElement("p");
    outside.textContent = "Nicht im Container";
    document.body.appendChild(outside);
    const selection = selectAcross(outside.firstChild!, 0, outside.firstChild!, 5);

    expect(getCharacterOffsetsFromSelection(container, selection)).toBeNull();
  });

  it("returns null when there is no active selection", () => {
    const container = buildFragmentedContainer(["Hallo Wien"]);
    const selection = window.getSelection()!;
    selection.removeAllRanges();

    expect(getCharacterOffsetsFromSelection(container, selection)).toBeNull();
  });
});
