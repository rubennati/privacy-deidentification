// Fetches the effective upload constraints from the backend (the single source of truth),
// so client-side validation messages and the file picker mirror the server instead of
// hardcoding their own copy. Falls back to built-in defaults if the request fails.

export interface UploadConfig {
  maxUploadBytes: number;
  allowedExtensions: string[];
}

interface ConfigResponse {
  max_upload_bytes: number;
  allowed_extensions: string[];
}

export async function fetchUploadConfig(): Promise<UploadConfig | null> {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return null;
    }
    const data = (await response.json()) as ConfigResponse;
    return {
      maxUploadBytes: data.max_upload_bytes,
      allowedExtensions: data.allowed_extensions,
    };
  } catch {
    return null;
  }
}
