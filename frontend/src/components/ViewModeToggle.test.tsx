import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ViewModeToggle } from "./ViewModeToggle";

/** Return the `<button>…</button>` fragment whose text content contains `label`. */
function buttonFor(html: string, label: string): string {
  const fragment = html
    .split("</button>")
    .find((part) => part.includes(label));
  if (fragment === undefined) {
    throw new Error(`No button containing "${label}"`);
  }
  return fragment;
}

describe("ViewModeToggle", () => {
  it("renders both view options", () => {
    const html = renderToStaticMarkup(<ViewModeToggle mode="user" onChange={vi.fn()} />);

    expect(html).toContain("User view");
    expect(html).toContain("Dev view");
  });

  it("marks the active mode as pressed", () => {
    const userActive = renderToStaticMarkup(<ViewModeToggle mode="user" onChange={vi.fn()} />);
    expect(buttonFor(userActive, "User view")).toContain('aria-pressed="true"');
    expect(buttonFor(userActive, "Dev view")).toContain('aria-pressed="false"');

    const devActive = renderToStaticMarkup(<ViewModeToggle mode="dev" onChange={vi.fn()} />);
    expect(buttonFor(devActive, "Dev view")).toContain('aria-pressed="true"');
    expect(buttonFor(devActive, "User view")).toContain('aria-pressed="false"');
  });
});
