import { afterEach, describe, expect, it, vi } from "vitest";

import { runPii } from "./workstations";

describe("runPii", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends a profile override payload when requested", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            id: "artifact-id",
            document_id: "doc-id",
            artifact_type: "pii_result",
            station: "pii",
            input_text_artifact_id: "text-id",
            media_type: "application/json",
            created_at: "2026-07-02T10:00:00.000000Z",
            content: {
              document_id: "doc-id",
              input_text_artifact_id: "text-id",
              pii_version: "1",
              profile: "review-heavy",
              language: "de",
              score_threshold: 0.5,
              text_char_count: 0,
              configured_entity_types: [],
              entities: [],
              entity_counts: {},
              tool_versions: {},
              flags: [],
              validation: null,
              engine_settings: {
                pii_profile: "review-heavy",
                candidate_validation_enabled: true,
                score_threshold: 0.5,
                source: "dev-ui-override",
              },
            },
          }),
          { status: 201 },
        ),
      );

    await runPii("doc-42", { pii_profile: "review-heavy" });

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-42/pii", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pii_profile: "review-heavy" }),
    });
  });
});
