// Builds a proactive, non-blocking hint when a station's runtime is not installed on this server,
// so a missing OCR/PII runtime is visible before a run instead of only surfacing as a 503 after
// the fact. Returns null once config hasn't loaded yet or both runtimes are available.

import type { AppConfig } from "../api/config";

export function buildRuntimeNotice(appConfig: AppConfig | null): string | null {
  if (!appConfig) {
    return null;
  }
  const missing: string[] = [];
  if (!appConfig.runtime.ocrAvailable) {
    missing.push("Texterkennung (OCR)");
  }
  if (!appConfig.runtime.piiAvailable) {
    missing.push("Erkennung sensibler Daten (PII)");
  }
  if (missing.length === 0) {
    return null;
  }
  const subject = missing.join(" und ");
  const verb = missing.length > 1 ? "sind" : "ist";
  return `Hinweis: ${subject} ${verb} auf diesem Server nicht installiert. Ein Lauf kann mit einem Laufzeit-Fehler enden.`;
}

const STATION_LABEL: Record<"ocr" | "pii", string> = {
  ocr: "Die Texterkennung (OCR)",
  pii: "Die Erkennung sensibler Daten (PII)",
};

/** Same idea as buildRuntimeNotice, scoped to one dev-view station panel. */
export function buildStationRuntimeNotice(
  appConfig: AppConfig | null,
  station: "ocr" | "pii",
): string | null {
  if (!appConfig) {
    return null;
  }
  const available =
    station === "ocr" ? appConfig.runtime.ocrAvailable : appConfig.runtime.piiAvailable;
  if (available) {
    return null;
  }
  return `${STATION_LABEL[station]} ist auf diesem Server nicht installiert. Ein Lauf endet mit einem Laufzeit-Fehler (503).`;
}
