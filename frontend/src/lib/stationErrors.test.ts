import { describe, expect, it } from "vitest";

import { WorkstationApiError } from "../api/workstations";
import { OCR_RUNTIME_FAILURE_MESSAGE, toStationError } from "./stationErrors";

describe("toStationError", () => {
  it("maps OCR 502/503/504 to one safe, OCR-specific message", () => {
    for (const status of [502, 503, 504]) {
      const result = toStationError(new WorkstationApiError("boom", status, null), "ocr");
      expect(result.message).toBe(OCR_RUNTIME_FAILURE_MESSAGE);
    }
  });

  it("does not leak a raw nginx 502 message for the OCR station", () => {
    const result = toStationError(
      new WorkstationApiError("<html>502 Bad Gateway</html>", 502, null),
      "ocr",
    );
    expect(result.message).toBe(OCR_RUNTIME_FAILURE_MESSAGE);
    expect(result.message).not.toContain("html");
  });

  it("preserves the correlation ID from a backend JSON error", () => {
    const result = toStationError(
      new WorkstationApiError("Der Text konnte nicht verarbeitet werden.", 422, "corr-9"),
      "pii",
    );
    expect(result.message).toBe("Der Text konnte nicht verarbeitet werden.");
    expect(result.correlationId).toBe("corr-9");
  });

  it("keeps the existing non-OCR mappings for gateway/runtime statuses", () => {
    // 503 on a non-OCR station still reports the runtime/model as unavailable.
    expect(toStationError(new WorkstationApiError("x", 503, null), "pii").message).toBe(
      "Die benötigte Runtime oder das Modell ist nicht verfügbar.",
    );
    // 502/504 on a non-OCR station gets a safe generic gateway message, not the raw body.
    expect(toStationError(new WorkstationApiError("x", 502, null), "audit").message).toBe(
      "Der Server ist vorübergehend nicht erreichbar. Bitte versuchen Sie es erneut.",
    );
  });

  it("keeps station-specific 409 and 422 messages", () => {
    expect(toStationError(new WorkstationApiError("x", 409, null), "ocr").message).toBe(
      "Zuerst ein gültiges Audit erstellen.",
    );
    expect(toStationError(new WorkstationApiError("x", 409, null), "pii").message).toBe(
      "Zuerst OCR/Text erzeugen.",
    );
    expect(toStationError(new WorkstationApiError("x", 422, null), "ocr").message).toBe(
      "Das Dokument konnte nicht verarbeitet werden.",
    );
  });

  it("reports a connection error for status 0", () => {
    expect(toStationError(new WorkstationApiError("x", 0, null), "ocr").message).toBe(
      "Keine Verbindung zum Server.",
    );
  });

  it("returns a generic message for a non-WorkstationApiError", () => {
    const result = toStationError(new Error("unexpected"), "ocr");
    expect(result.message).toBe("Ein unerwarteter Fehler ist aufgetreten.");
    expect(result.correlationId).toBeNull();
  });
});
