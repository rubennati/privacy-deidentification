import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { PiiEngineSettingsPanel } from "./PiiEngineSettingsPanel";

describe("PiiEngineSettingsPanel", () => {
  it("shows dev controls only when enabled", () => {
    const hidden = renderToStaticMarkup(
      <PiiEngineSettingsPanel
        config={{
          defaultProfile: "structured-only",
          availableProfiles: ["structured-only", "insurance-at-de", "review-heavy"],
          candidateValidationEnabled: true,
          scoreThreshold: 0.5,
        }}
        devSettingsEnabled={false}
        selectedProfile=""
        artifactSettings={null}
        onProfileChange={vi.fn()}
      />,
    );

    const visible = renderToStaticMarkup(
      <PiiEngineSettingsPanel
        config={{
          defaultProfile: "structured-only",
          availableProfiles: ["structured-only", "insurance-at-de", "review-heavy"],
          candidateValidationEnabled: true,
          scoreThreshold: 0.5,
        }}
        devSettingsEnabled={true}
        selectedProfile=""
        artifactSettings={null}
        onProfileChange={vi.fn()}
      />,
    );

    expect(hidden).not.toContain("Dev Engine Settings");
    expect(visible).toContain("Dev Engine Settings");
    expect(visible).toContain("Backend-Default (structured-only)");
    expect(visible).toContain("insurance-at-de");
    expect(visible).not.toContain('<option value="structured-only"');
  });

  it("renders persisted artifact settings when present", () => {
    const html = renderToStaticMarkup(
      <PiiEngineSettingsPanel
        config={null}
        devSettingsEnabled={false}
        selectedProfile=""
        artifactSettings={{
          pii_profile: "review-heavy",
          candidate_validation_enabled: true,
          score_threshold: 0.5,
          source: "dev-ui-override",
        }}
        onProfileChange={vi.fn()}
      />,
    );

    expect(html).toContain("Aktuelle Artifact-Settings");
    expect(html).toContain("review-heavy");
    expect(html).toContain("Aktiv");
    expect(html).toContain("0.50");
    expect(html).toContain("Dev-UI-Override");
  });
});
