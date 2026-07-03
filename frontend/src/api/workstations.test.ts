import { afterEach, describe, expect, it, vi } from "vitest";

import { runOcr, runPii, WorkstationApiError } from "./workstations";

const GENERIC_ERROR_DETAIL = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";

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

describe("workstation API error handling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not surface a non-JSON 502 HTML body and preserves the status", async () => {
    const html = "<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(html, {
        status: 502,
        headers: { "Content-Type": "text/html" },
      }),
    );

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    const apiError = error as WorkstationApiError;
    expect(apiError.status).toBe(502);
    expect(apiError.correlationId).toBeNull();
    // The raw nginx HTML must never leak into the user-facing message.
    expect(apiError.message).toBe(GENERIC_ERROR_DETAIL);
    expect(apiError.message).not.toContain("html");
    expect(apiError.message).not.toContain("nginx");
  });

  it("preserves the backend JSON detail and correlation ID on a structured error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Audit result does not reference the current original artifact.",
          correlation_id: "corr-123",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    const apiError = error as WorkstationApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.message).toBe(
      "Audit result does not reference the current original artifact.",
    );
    expect(apiError.correlationId).toBe("corr-123");
  });

  it("falls back to a safe message when a JSON error body has no detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ correlation_id: null }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    const apiError = error as WorkstationApiError;
    expect(apiError.status).toBe(500);
    expect(apiError.message).toBe(GENERIC_ERROR_DETAIL);
    expect(apiError.correlationId).toBeNull();
  });
});
