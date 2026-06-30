// Client-side upload validation. This is a UX convenience only — the backend is the
// authoritative trust boundary and re-validates every upload.

export const ALLOWED_EXTENSIONS = ["pdf", "docx", "png", "jpg", "jpeg"] as const;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MiB; mirrors the backend default.

export const ACCEPT_ATTRIBUTE = ".pdf,.docx,.png,.jpg,.jpeg";

export interface ValidationError {
  message: string;
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : "";
}

function formatMegabytes(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/** Returns a validation error, or `null` when the file is acceptable. */
export function validateFile(file: File): ValidationError | null {
  if (file.size === 0) {
    return { message: "Die Datei ist leer." };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      message: `Die Datei ist zu groß (max. ${formatMegabytes(MAX_UPLOAD_BYTES)}).`,
    };
  }
  const extension = extensionOf(file.name);
  if (!ALLOWED_EXTENSIONS.includes(extension as (typeof ALLOWED_EXTENSIONS)[number])) {
    return {
      message: `Nicht unterstützter Dateityp. Erlaubt: ${ALLOWED_EXTENSIONS.join(", ").toUpperCase()}.`,
    };
  }
  return null;
}
