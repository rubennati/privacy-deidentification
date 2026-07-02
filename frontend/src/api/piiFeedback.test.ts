import { afterEach, describe, expect, it, vi } from "vitest";

import type { PiiEntity } from "./workstations";
import {
  buildIssueFeedback,
  buildPositiveFeedback,
  sendPiiFeedback,
} from "./piiFeedback";

const entity: PiiEntity = {
  id: "e".repeat(32),
  entity_type: "LOCATION",
  text: "Wien",
  start_offset: 10,
  end_offset: 14,
  page_number: 1,
  page_start_offset: 10,
  page_end_offset: 14,
  score: 0.9,
  recognizer: "FakeRecognizer",
};

describe("feedback payload builders", () => {
  it("builds a positive payload with issue_type 'correct' and no text", () => {
    const payload = buildPositiveFeedback("artifact-1", entity);
    expect(payload).toEqual({
      artifact_id: "artifact-1",
      entity: { type: "LOCATION", start: 10, end: 14, score: 0.9, recognizer: "FakeRecognizer" },
      feedback: { verdict: "positive", issue_type: "correct" },
    });
    expect(JSON.stringify(payload)).not.toContain("Wien");
  });

  it("builds an issue payload with a trimmed comment", () => {
    const payload = buildIssueFeedback("artifact-1", entity, "wrong_type", "  should be PERSON  ");
    expect(payload.feedback).toEqual({
      verdict: "issue",
      issue_type: "wrong_type",
      comment: "should be PERSON",
    });
  });

  it("omits an empty comment", () => {
    const payload = buildIssueFeedback("artifact-1", entity, "false_positive", "   ");
    expect(payload.feedback).toEqual({ verdict: "issue", issue_type: "false_positive" });
  });
});

describe("sendPiiFeedback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs the payload to the document feedback endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ recorded: true, schema_version: "1", recorded_at: "2026-07-02T10:00:00Z" }),
          { status: 201 },
        ),
      );

    const payload = buildPositiveFeedback("art-1", entity);
    await sendPiiFeedback("doc-42", payload);

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/doc-42/pii/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  });

  it("throws a WorkstationApiError on a non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "disabled" }), { status: 403 }),
    );

    await expect(
      sendPiiFeedback("doc-1", buildPositiveFeedback("art-1", entity)),
    ).rejects.toMatchObject({ status: 403 });
  });
});
