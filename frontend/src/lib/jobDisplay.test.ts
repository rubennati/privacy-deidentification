import { describe, expect, it } from "vitest";

import type { JobStatus } from "../api/workstations";
import { describeJob } from "./jobDisplay";

function job(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    job_id: "job-1",
    document_id: "doc-1",
    kind: "ocr_text",
    status: "pending",
    execution_mode: "future_worker",
    created_at: "2026-07-09T10:00:00.000000Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-07-09T10:00:00.000000Z",
    attempt_count: 0,
    error_code: null,
    error_message: null,
    result_artifact_id: null,
    result_artifact_type: null,
    metadata: {},
    is_terminal: false,
    ...overrides,
  };
}

describe("describeJob", () => {
  it("describes a pending job as accepted/waiting", () => {
    expect(describeJob(job({ status: "pending" }))).toEqual({
      tone: "info",
      message: "Die Texterkennung (OCR) wurde angenommen und wartet auf Verarbeitung …",
    });
  });

  it("describes a running job", () => {
    expect(describeJob(job({ status: "running" })).tone).toBe("info");
    expect(describeJob(job({ status: "running" })).message).toContain("läuft");
  });

  it("describes a succeeded job", () => {
    expect(describeJob(job({ status: "succeeded" })).tone).toBe("success");
  });

  it("uses the sanitized error_message for a failed job when present", () => {
    const view = describeJob(
      job({ status: "failed", error_code: "api_error_503", error_message: "PaddleOCR is not available." }),
    );
    expect(view.tone).toBe("error");
    expect(view.message).toBe("PaddleOCR is not available.");
  });

  it("falls back to a generic failure message when error_message is missing", () => {
    const view = describeJob(job({ status: "failed", error_code: null, error_message: null }));
    expect(view.tone).toBe("error");
    expect(view.message).toContain("fehlgeschlagen");
  });

  it("describes a canceled job", () => {
    expect(describeJob(job({ status: "canceled" })).tone).toBe("error");
  });

  it("never crashes for a pii_detection job kind", () => {
    expect(() => describeJob(job({ kind: "pii_detection", status: "running" }))).not.toThrow();
  });
});
