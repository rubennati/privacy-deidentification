import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { JobStatus } from "../api/workstations";
import { JobStatusBanner } from "./JobStatusBanner";

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

describe("JobStatusBanner", () => {
  it("renders nothing without a job", () => {
    expect(renderToStaticMarkup(<JobStatusBanner job={null} />)).toBe("");
    expect(renderToStaticMarkup(<JobStatusBanner job={undefined} />)).toBe("");
  });

  it("renders an accepted/pending notice", () => {
    const html = renderToStaticMarkup(<JobStatusBanner job={job({ status: "pending" })} />);
    expect(html).toContain("wurde angenommen");
  });

  it("renders a running notice", () => {
    const html = renderToStaticMarkup(<JobStatusBanner job={job({ status: "running" })} />);
    expect(html).toContain("läuft");
  });

  it("renders a succeeded notice", () => {
    const html = renderToStaticMarkup(<JobStatusBanner job={job({ status: "succeeded" })} />);
    expect(html).toContain("abgeschlossen");
  });

  it("renders a failed job's sanitized error message", () => {
    const html = renderToStaticMarkup(
      <JobStatusBanner
        job={job({ status: "failed", error_message: "PaddleOCR is not available." })}
      />,
    );
    expect(html).toContain("PaddleOCR is not available.");
  });

  it("does not crash and falls back to a generic message when error fields are missing", () => {
    const html = renderToStaticMarkup(
      <JobStatusBanner job={job({ status: "failed", error_code: null, error_message: null })} />,
    );
    expect(html).toContain("fehlgeschlagen");
  });
});
