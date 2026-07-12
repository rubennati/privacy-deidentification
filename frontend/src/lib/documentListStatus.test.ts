import { describe, expect, it } from "vitest";

import type { JobStatus } from "../api/workstations";
import { deriveAnalysisState } from "./documentListStatus";

function job(overrides: Partial<JobStatus>): JobStatus {
  return {
    job_id: "j1",
    document_id: "d1",
    kind: "ocr_text",
    status: "succeeded",
    execution_mode: "synchronous_inline",
    created_at: "2026-07-11T10:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-07-11T10:00:00Z",
    attempt_count: 1,
    error_code: null,
    error_message: null,
    result_artifact_id: null,
    result_artifact_type: null,
    metadata: {},
    ...overrides,
  };
}

describe("deriveAnalysisState", () => {
  it("returns none for a document without jobs", () => {
    expect(deriveAnalysisState([])).toBe("none");
  });

  it("returns running while any job is pending or running, even after a past success", () => {
    expect(
      deriveAnalysisState([
        job({ kind: "pii_detection", status: "succeeded" }),
        job({ kind: "ocr_text", status: "running" }),
      ]),
    ).toBe("running");
    expect(deriveAnalysisState([job({ status: "pending" })])).toBe("running");
  });

  it("returns analyzed once a PII detection succeeded", () => {
    expect(
      deriveAnalysisState([
        job({ kind: "ocr_text", status: "succeeded" }),
        job({ kind: "pii_detection", status: "succeeded" }),
      ]),
    ).toBe("analyzed");
  });

  it("does not count OCR alone or failed PII runs as analyzed", () => {
    expect(deriveAnalysisState([job({ kind: "ocr_text", status: "succeeded" })])).toBe("none");
    expect(deriveAnalysisState([job({ kind: "pii_detection", status: "failed" })])).toBe("none");
  });
});
