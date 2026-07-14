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
    const now = new Date("2026-07-11T10:01:00Z");
    expect(
      deriveAnalysisState(
        [
          job({ kind: "pii_detection", status: "succeeded" }),
          job({ kind: "ocr_text", status: "running" }),
        ],
        now,
      ),
    ).toBe("running");
    expect(deriveAnalysisState([job({ status: "pending" })], now)).toBe("running");
  });

  it("stops reporting an abandoned running job as active after 15 minutes without progress", () => {
    // Runtime Phase 3 has no stale-lease reclaim: a worker killed mid-job leaves the row
    // "running" forever. The badge must fall back instead of claiming endless activity.
    const now = new Date("2026-07-11T11:00:00Z");
    expect(deriveAnalysisState([job({ status: "running" })], now)).toBe("none");
    expect(
      deriveAnalysisState(
        [job({ status: "running" }), job({ kind: "pii_detection", status: "succeeded" })],
        now,
      ),
    ).toBe("analyzed");
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
