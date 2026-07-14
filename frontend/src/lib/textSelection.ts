// Character-offset capture for manual PII additions (PII L14 / Review L10, ADR-0035). The reading
// text is rendered as multiple <span>/<mark> fragments (see PiiTextViewer.tsx), so a selection's
// character offset can't be read off a single text node directly.

/** The character offset of one selection boundary, relative to `container`'s full text content. */
function offsetWithinContainer(container: Node, node: Node, nodeOffset: number): number {
  const range = document.createRange();
  range.selectNodeContents(container);
  range.setEnd(node, nodeOffset);
  return range.toString().length;
}

/** Resolve the current window selection to character offsets within `container`'s rendered text.
 *  Returns `null` for a collapsed selection or one that reaches outside `container`. */
export function getCharacterOffsetsFromSelection(
  container: HTMLElement,
  selection: Selection,
): { start: number; end: number } | null {
  if (selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }
  const range = selection.getRangeAt(0);
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) {
    return null;
  }
  const start = offsetWithinContainer(container, range.startContainer, range.startOffset);
  const end = offsetWithinContainer(container, range.endContainer, range.endOffset);
  if (end <= start) {
    return null;
  }
  return { start, end };
}
