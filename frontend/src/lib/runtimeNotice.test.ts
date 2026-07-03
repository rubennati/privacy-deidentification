import { describe, expect, it } from "vitest";

import type { AppConfig } from "../api/config";
import { buildRuntimeNotice, buildStationRuntimeNotice } from "./runtimeNotice";

function makeConfig(ocrAvailable: boolean, piiAvailable: boolean): AppConfig {
  return {
    maxUploadBytes: 1024,
    allowedExtensions: ["pdf"],
    devEngineSettingsEnabled: false,
    pii: {
      defaultProfile: "structured-only",
      availableProfiles: ["structured-only"],
      candidateValidationEnabled: true,
      scoreThreshold: 0.5,
    },
    runtime: { ocrAvailable, piiAvailable },
  };
}

describe("buildRuntimeNotice", () => {
  it("returns null when config has not loaded yet", () => {
    expect(buildRuntimeNotice(null)).toBeNull();
  });

  it("returns null when both runtimes are available", () => {
    expect(buildRuntimeNotice(makeConfig(true, true))).toBeNull();
  });

  it("mentions only OCR when the PII runtime is available but OCR is not", () => {
    const notice = buildRuntimeNotice(makeConfig(false, true));
    expect(notice).toContain("Texterkennung (OCR)");
    expect(notice).not.toContain("PII");
  });

  it("mentions only PII when the OCR runtime is available but PII is not", () => {
    const notice = buildRuntimeNotice(makeConfig(true, false));
    expect(notice).toContain("Erkennung sensibler Daten (PII)");
    expect(notice).not.toContain("OCR");
  });

  it("mentions both when neither runtime is available", () => {
    const notice = buildRuntimeNotice(makeConfig(false, false));
    expect(notice).toContain("Texterkennung (OCR)");
    expect(notice).toContain("Erkennung sensibler Daten (PII)");
    expect(notice).toContain("sind");
  });
});

describe("buildStationRuntimeNotice", () => {
  it("returns null when config has not loaded yet", () => {
    expect(buildStationRuntimeNotice(null, "pii")).toBeNull();
  });

  it("returns null for a station whose runtime is available", () => {
    expect(buildStationRuntimeNotice(makeConfig(true, true), "ocr")).toBeNull();
    expect(buildStationRuntimeNotice(makeConfig(true, true), "pii")).toBeNull();
  });

  it("returns a PII-specific notice when only PII is unavailable", () => {
    const notice = buildStationRuntimeNotice(makeConfig(true, false), "pii");
    expect(notice).toContain("PII");
    expect(notice).toContain("nicht installiert");
  });

  it("returns an OCR-specific notice when only OCR is unavailable", () => {
    const notice = buildStationRuntimeNotice(makeConfig(false, true), "ocr");
    expect(notice).toContain("OCR");
  });

  it("is independent per station when both are unavailable", () => {
    expect(buildStationRuntimeNotice(makeConfig(false, false), "ocr")).toContain("OCR");
    expect(buildStationRuntimeNotice(makeConfig(false, false), "pii")).toContain("PII");
  });
});
