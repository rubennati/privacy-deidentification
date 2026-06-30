// Client-side upload validation. This is a UX convenience only — the backend is the
// authoritative trust boundary and re-validates every upload. Constraints default to the
// backend defaults but can be overridden at runtime from GET /api/config (see api/config.ts).

export const DEFAULT_ALLOWED_EXTENSIONS = ["pdf", "docx", "png", "jpg", "jpeg"];
export const DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MiB; mirrors the backend default.

export interface UploadConstraints {
  allowedExtensions: string[];
  maxUploadBytes: number;
}

export const DEFAULT_CONSTRAINTS: UploadConstraints = {
  allowedExtensions: DEFAULT_ALLOWED_EXTENSIONS,
  maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
};

export interface ValidationError {
  message: string;
}

/** Build the `<input accept>` attribute from a list of extensions, e.g. ".pdf,.docx". */
export function buildAcceptAttribute(extensions: string[]): string {
  return extensions.map((extension) => `.${extension}`).join(",");
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : "";
}

function formatMegabytes(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/** Returns a validation error, or `null` when the file is acceptable. */
export function validateFile(
  file: File,
  constraints: UploadConstraints = DEFAULT_CONSTRAINTS,
): ValidationError | null {
  if (file.size === 0) {
    return { message: "Die Datei ist leer." };
  }
  if (file.size > constraints.maxUploadBytes) {
    return {
      message: `Die Datei ist zu groß (max. ${formatMegabytes(constraints.maxUploadBytes)}).`,
    };
  }
  if (!constraints.allowedExtensions.includes(extensionOf(file.name))) {
    return {
      message: `Nicht unterstützter Dateityp. Erlaubt: ${constraints.allowedExtensions
        .join(", ")
        .toUpperCase()}.`,
    };
  }
  return null;
}
