import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PiiEntity } from "../../api/workstations";
import { PiiEntityFeedback } from "./PiiEntityFeedback";
import { PiiEntityList } from "./PiiEntityList";

const entity: PiiEntity = {
  id: "a".repeat(32),
  entity_type: "LOCATION",
  text: "Wien",
  start_offset: 0,
  end_offset: 4,
  page_number: 1,
  page_start_offset: 0,
  page_end_offset: 4,
  score: 0.9,
  recognizer: "FakeRecognizer",
};

describe("PiiEntityFeedback", () => {
  it("renders nothing when the dev gate is disabled", () => {
    const html = renderToStaticMarkup(
      <PiiEntityFeedback documentId="doc-1" artifactId="art-1" entity={entity} enabled={false} />,
    );
    expect(html).toBe("");
  });

  it("renders the positive button, issue picker, and save control when enabled", () => {
    const html = renderToStaticMarkup(
      <PiiEntityFeedback documentId="doc-1" artifactId="art-1" entity={entity} enabled={true} />,
    );
    expect(html).toContain("Passt");
    expect(html).toContain("Problem auswählen");
    expect(html).toContain("Falscher Typ");
    expect(html).toContain("Feedback speichern");
  });
});

describe("PiiEntityList with feedback", () => {
  it("shows per-entity feedback controls only when enabled", () => {
    const withFeedback = renderToStaticMarkup(
      <PiiEntityList
        entities={[entity]}
        stale={false}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
      />,
    );
    const withoutFeedback = renderToStaticMarkup(
      <PiiEntityList
        entities={[entity]}
        stale={false}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={false}
      />,
    );
    expect(withFeedback).toContain("Passt");
    // The entity itself always renders; only the feedback controls are gated.
    expect(withoutFeedback).toContain("LOCATION");
    expect(withoutFeedback).not.toContain("Passt");
  });
});
