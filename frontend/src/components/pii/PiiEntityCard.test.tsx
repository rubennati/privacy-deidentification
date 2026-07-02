import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PiiEntity } from "../../api/workstations";
import { PiiEntityCard } from "./PiiEntityCard";
import { PiiEntityList } from "./PiiEntityList";

const entity: PiiEntity = {
  id: "a".repeat(32),
  entity_type: "LOCATION",
  text: "Wien",
  start_offset: 12,
  end_offset: 16,
  page_number: 1,
  page_start_offset: 12,
  page_end_offset: 16,
  score: 0.9,
  recognizer: "FakeRecognizer",
};

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node);
}

describe("PiiEntityCard header controls", () => {
  it("hides feedback controls entirely when the gate is off", () => {
    const html = render(
      <PiiEntityCard
        entity={entity}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={false}
        existingStatus={null}
      />,
    );
    expect(html).not.toContain("Passt");
    expect(html).not.toContain("Feedback speichern");
    // The entity itself still renders.
    expect(html).toContain("LOCATION");
  });

  it("renders the Passt button in the header next to the confidence", () => {
    const html = render(
      <PiiEntityCard
        entity={entity}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
        existingStatus={null}
      />,
    );
    // Confidence and the Passt button both live in the header, before the entity text.
    const headerEnd = html.indexOf("Wien");
    expect(html.slice(0, headerEnd)).toContain("90 %");
    expect(html.slice(0, headerEnd)).toContain("Passt");
    expect(html).toContain("Feedback speichern");
  });

  it("renders a clickable offset link", () => {
    const html = render(
      <PiiEntityCard
        entity={entity}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={false}
        existingStatus={null}
      />,
    );
    expect(html).toContain("12–16");
    expect(html).toContain("Im extrahierten Text zu dieser Stelle springen");
  });
});

describe("PiiEntityCard locked state", () => {
  it("shows a positive saved status and no form when feedback already exists", () => {
    const html = render(
      <PiiEntityCard
        entity={entity}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
        existingStatus={{ verdict: "positive", issue_type: "correct" }}
      />,
    );
    expect(html).toContain("Feedback gespeichert: Passt");
    expect(html).not.toContain("Feedback speichern");
    expect(html).not.toContain("Problem auswählen");
  });

  it("shows the issue label for an existing issue verdict", () => {
    const html = render(
      <PiiEntityCard
        entity={entity}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
        existingStatus={{ verdict: "issue", issue_type: "wrong_type" }}
      />,
    );
    expect(html).toContain("Feedback gespeichert: Falscher Typ");
    expect(html).not.toContain("Feedback speichern");
  });
});

describe("PiiEntityList", () => {
  it("renders the entity-type legend", () => {
    const html = render(
      <PiiEntityList
        entities={[entity]}
        stale={false}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={false}
        feedbackStatuses={{}}
      />,
    );
    expect(html).toContain("Was bedeuten die Entity-Typen?");
    expect(html).toContain("Personennamen");
  });

  it("does not break for a legacy artifact without engine settings (no statuses)", () => {
    const html = render(
      <PiiEntityList
        entities={[entity]}
        stale={false}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
        feedbackStatuses={{}}
      />,
    );
    expect(html).toContain("LOCATION");
    expect(html).toContain("Passt");
  });

  it("restores a saved status from the feedback map by entity key", () => {
    const html = render(
      <PiiEntityList
        entities={[entity]}
        stale={false}
        documentId="doc-1"
        artifactId="art-1"
        feedbackEnabled={true}
        feedbackStatuses={{
          "LOCATION|12|16|FakeRecognizer": { verdict: "issue", issue_type: "false_positive" },
        }}
      />,
    );
    expect(html).toContain("Feedback gespeichert: Kein PII (False Positive)");
    expect(html).not.toContain("Feedback speichern");
  });
});
