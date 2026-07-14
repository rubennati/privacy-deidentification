import { afterEach, describe, expect, it, vi } from "vitest";

import { jobActivityStore } from "../lib/jobActivity";
import { runOcr, runPii, WorkstationApiError } from "./workstations";

const GENERIC_ERROR_DETAIL = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";
const JOB_ID = "1234567890abcdef1234567890abcdef";

const textArtifact = {
  id: "text-id",
  document_id: "doc-1",
  artifact_type: "text_result",
  station: "ocr",
  input_artifact_id: "original-id",
  input_audit_artifact_id: "audit-id",
  media_type: "application/json",
  created_at: "2026-07-02T10:00:00.000000Z",
  content: {
    document_id: "doc-1",
    input_artifact_id: "original-id",
    input_audit_artifact_id: "audit-id",
    source: "docx_text",
    ocr_version: "1",
    text: "Synthetic text",
    text_char_count: 14,
    pages: [],
    tool_versions: {},
    flags: [],
  },
};

function jobStatus(status: "pending" | "running" | "succeeded" | "failed") {
  return {
    job_id: JOB_ID,
    document_id: "doc-1",
    kind: "ocr_text",
    status,
    execution_mode: "future_worker",
    created_at: "2026-07-02T10:00:00.000000Z",
    started_at: status === "pending" ? null : "2026-07-02T10:00:01.000000Z",
    finished_at:
      status === "succeeded" || status === "failed" ? "2026-07-02T10:00:02.000000Z" : null,
    updated_at: "2026-07-02T10:00:02.000000Z",
    attempt_count: status === "pending" ? 0 : 1,
    error_code: null,
    error_message: null,
    result_artifact_id: status === "succeeded" ? "text-id" : null,
    result_artifact_type: status === "succeeded" ? "text_result" : null,
    metadata: {},
  };
}

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

describe("runOcr", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the text artifact directly in sync fallback mode", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(textArtifact), { status: 201 }));

    const result = await runOcr("doc-1");

    expect(result).toEqual(textArtifact);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-1/ocr", { method: "POST" });
  });

  it("polls a worker job after a 202 response and then fetches the text artifact", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(jobStatus("pending")), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(jobStatus("succeeded")), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(textArtifact), { status: 200 }));

    const result = await runOcr("doc-1");

    expect(result).toEqual(textArtifact);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/documents/doc-1/ocr", {
      method: "POST",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, `/api/jobs/${JOB_ID}`, { method: "GET" });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/documents/doc-1/ocr?artifact_id=text-id", {
      method: "GET",
    });
    // The 202 job is tracked immediately, and the shared store reflects its terminal status once
    // the (single, de-duplicated) poll loop observes it — this is what lets a status banner and a
    // reload recovery both read the same up-to-date state.
    expect(jobActivityStore.getJob(JOB_ID)?.status).toBe("succeeded");
  });

  it("turns failed worker job metadata into a workstation error", async () => {
    const failedJob = {
      ...jobStatus("failed"),
      error_code: "api_error_503",
      error_message: "PaddleOCR is not available.",
    };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(jobStatus("pending")), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(failedJob), { status: 200 }));

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    const apiError = error as WorkstationApiError;
    expect(apiError.status).toBe(503);
    expect(apiError.message).toBe("PaddleOCR is not available.");
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

describe("incompatible job payloads fail closed (ADR-0041)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects a 202 body without a job_id instead of polling a nonsense URL", async () => {
    const broken = { ...jobStatus("pending"), job_id: undefined };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(broken), { status: 202 }));

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    expect((error as WorkstationApiError).status).toBe(502);
    // No poll request was ever issued for the unusable payload.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a job status value this build does not understand", async () => {
    const futureStatus = { ...jobStatus("pending"), status: "paused" };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(futureStatus), { status: 202 }));

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    expect((error as WorkstationApiError).status).toBe(502);
  });

  it("rejects a job-status poll response with an unknown status instead of waiting forever", async () => {
    const futureStatus = { ...jobStatus("running"), status: "hibernating" };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(jobStatus("pending")), { status: 202 }))
      .mockResolvedValue(new Response(JSON.stringify(futureStatus), { status: 200 }));

    const error = await runOcr("doc-1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkstationApiError);
    expect((error as WorkstationApiError).status).toBe(502);
  });
});
