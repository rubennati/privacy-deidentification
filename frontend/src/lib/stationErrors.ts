// Maps a workstation API failure to a safe, user-facing message for a given station. Kept in its
// own module (not the page component) so the mapping — especially the OCR gateway/runtime handling
// — is directly unit-testable. It never returns raw backend/nginx bodies, document text, or PII;
// it works only from the HTTP status and station, preserving the correlation ID when the backend
// supplied one.

import { WorkstationApiError } from "../api/workstations";

export type StationName = "audit" | "ocr" | "pii";

export interface StationError {
  message: string;
  correlationId: string | null;
}

// Shown when the OCR/Text station fails with a gateway/runtime status (502/503/504). The common
// cause is the OCR runtime being unavailable or the backend being killed mid-OCR (e.g. OOM under a
// too-small memory limit), which nginx returns as a non-JSON 502. The message is deliberately
// generic-but-actionable and points power users to the dev view.
export const OCR_RUNTIME_FAILURE_MESSAGE =
  "Die Texterkennung ist fehlgeschlagen. Bitte versuchen Sie es erneut oder wechseln Sie in die Entwickleransicht.";

// Statuses that can arrive without the backend's JSON envelope — nginx synthesizes these as HTML
// when the upstream is unreachable, times out, or closes the connection (backend crash/OOM).
const GATEWAY_STATUSES = new Set([502, 503, 504]);

export function toStationError(error: unknown, station: StationName): StationError {
  if (!(error instanceof WorkstationApiError)) {
    return { message: "Ein unerwarteter Fehler ist aufgetreten.", correlationId: null };
  }
  return { message: stationMessage(error, station), correlationId: error.correlationId };
}

function stationMessage(error: WorkstationApiError, station: StationName): string {
  if (error.status === 0) {
    return "Keine Verbindung zum Server.";
  }
  if (GATEWAY_STATUSES.has(error.status)) {
    // OCR is the heavy, memory-hungry station: a 502/504 here usually means the backend was killed
    // mid-OCR, and a 503 means the OCR runtime/model is unavailable. All three map to one safe,
    // OCR-specific message rather than a generic "request failed".
    if (station === "ocr") {
      return OCR_RUNTIME_FAILURE_MESSAGE;
    }
    if (error.status === 503) {
      return "Die benötigte Runtime oder das Modell ist nicht verfügbar.";
    }
    return "Der Server ist vorübergehend nicht erreichbar. Bitte versuchen Sie es erneut.";
  }
  if (error.status === 409) {
    return station === "ocr"
      ? "Zuerst ein gültiges Audit erstellen."
      : station === "pii"
        ? "Zuerst OCR/Text erzeugen."
        : "Das Original-Artifact ist nicht verwendbar.";
  }
  if (error.status === 403) {
    return "Dev Engine Settings sind auf diesem Server deaktiviert.";
  }
  if (error.status === 422) {
    return station === "pii"
      ? "Der Text konnte nicht verarbeitet werden."
      : "Das Dokument konnte nicht verarbeitet werden.";
  }
  return error.message;
}
