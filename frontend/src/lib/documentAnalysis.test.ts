import { beforeEach, describe, expect, it, vi } from "vitest";

import { isAnalysisRunning, runDocumentAnalysis } from "./documentAnalysis";
import {
  runAudit,
  runOcr,
  runPii,
  type AuditArtifact,
  type PiiArtifact,
  type TextArtifact,
} from "../api/workstations";

vi.mock("../api/workstations", () => ({
  runAudit: vi.fn(),
  runOcr: vi.fn(),
  runPii: vi.fn(),
}));

const mockRunAudit = vi.mocked(runAudit);
const mockRunOcr = vi.mocked(runOcr);
const mockRunPii = vi.mocked(runPii);

// The orchestration only passes artifacts through to the handlers, so minimal stand-ins suffice.
const audit = { id: "audit-1" } as unknown as AuditArtifact;
const text = { id: "text-1" } as unknown as TextArtifact;
const pii = { id: "pii-1" } as unknown as PiiArtifact;

function makeHandlers() {
  return {
    onStep: vi.fn(),
    onAudit: vi.fn(),
    onText: vi.fn(),
    onPii: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("runDocumentAnalysis", () => {
  it("runs Audit → OCR → PII in order and applies each returned artifact", async () => {
    mockRunAudit.mockResolvedValue(audit);
    mockRunOcr.mockResolvedValue(text);
    mockRunPii.mockResolvedValue(pii);
    const handlers = makeHandlers();

    await runDocumentAnalysis("doc-1", handlers);

    expect(mockRunAudit).toHaveBeenCalledWith("doc-1");
    expect(mockRunOcr).toHaveBeenCalledWith("doc-1");
    expect(mockRunPii).toHaveBeenCalledWith("doc-1");

    const auditOrder = mockRunAudit.mock.invocationCallOrder[0];
    const ocrOrder = mockRunOcr.mock.invocationCallOrder[0];
    const piiOrder = mockRunPii.mock.invocationCallOrder[0];
    expect(auditOrder).toBeLessThan(ocrOrder);
    expect(ocrOrder).toBeLessThan(piiOrder);

    expect(handlers.onAudit).toHaveBeenCalledWith(audit);
    expect(handlers.onText).toHaveBeenCalledWith(text);
    expect(handlers.onPii).toHaveBeenCalledWith(pii);
    expect(handlers.onStep).toHaveBeenLastCalledWith("done");
  });

  it("does not run OCR or PII when Audit fails", async () => {
    mockRunAudit.mockRejectedValue(new Error("audit boom"));
    const handlers = makeHandlers();

    await expect(runDocumentAnalysis("doc-1", handlers)).rejects.toThrow();

    expect(mockRunOcr).not.toHaveBeenCalled();
    expect(mockRunPii).not.toHaveBeenCalled();
    expect(handlers.onAudit).not.toHaveBeenCalled();
    expect(handlers.onStep).not.toHaveBeenCalledWith("done");
  });

  it("preserves the Audit result and skips PII when OCR fails", async () => {
    mockRunAudit.mockResolvedValue(audit);
    mockRunOcr.mockRejectedValue(new Error("ocr boom"));
    const handlers = makeHandlers();

    await expect(runDocumentAnalysis("doc-1", handlers)).rejects.toThrow();

    expect(handlers.onAudit).toHaveBeenCalledWith(audit);
    expect(mockRunPii).not.toHaveBeenCalled();
    expect(handlers.onText).not.toHaveBeenCalled();
    expect(handlers.onPii).not.toHaveBeenCalled();
    expect(handlers.onStep).not.toHaveBeenCalledWith("done");
  });

  it("preserves the Audit and OCR results when PII fails", async () => {
    mockRunAudit.mockResolvedValue(audit);
    mockRunOcr.mockResolvedValue(text);
    mockRunPii.mockRejectedValue(new Error("pii boom"));
    const handlers = makeHandlers();

    await expect(runDocumentAnalysis("doc-1", handlers)).rejects.toThrow();

    expect(handlers.onAudit).toHaveBeenCalledWith(audit);
    expect(handlers.onText).toHaveBeenCalledWith(text);
    expect(handlers.onPii).not.toHaveBeenCalled();
    expect(handlers.onStep).not.toHaveBeenCalledWith("done");
  });
});

describe("isAnalysisRunning", () => {
  it("is true only for the in-flight station steps", () => {
    expect(isAnalysisRunning("audit")).toBe(true);
    expect(isAnalysisRunning("ocr")).toBe(true);
    expect(isAnalysisRunning("pii")).toBe(true);
    expect(isAnalysisRunning("idle")).toBe(false);
    expect(isAnalysisRunning("done")).toBe(false);
  });
});
