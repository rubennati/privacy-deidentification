// Typed client for the upload endpoint. Same-origin: nginx proxies /api to the backend.

export interface UploadAccepted {
  id: string;
  filename: string;
  size: number;
  status: string;
}

interface ApiError {
  detail?: string;
  correlation_id?: string | null;
}

export class UploadError extends Error {
  readonly status: number;
  readonly correlationId: string | null;

  constructor(message: string, status: number, correlationId: string | null = null) {
    super(message);
    this.name = "UploadError";
    this.status = status;
    this.correlationId = correlationId;
  }
}

const UPLOADS_ENDPOINT = "/api/uploads";
const GENERIC_ERROR = "Der Upload ist fehlgeschlagen. Bitte versuchen Sie es erneut.";

export async function uploadDocument(file: File): Promise<UploadAccepted> {
  const form = new FormData();
  form.append("file", file);

  let response: Response;
  try {
    response = await fetch(UPLOADS_ENDPOINT, { method: "POST", body: form });
  } catch {
    throw new UploadError("Keine Verbindung zum Server.", 0);
  }

  if (!response.ok) {
    const { detail, correlationId } = await readError(response);
    throw new UploadError(detail, response.status, correlationId);
  }

  return (await response.json()) as UploadAccepted;
}

async function readError(response: Response): Promise<{ detail: string; correlationId: string | null }> {
  try {
    const data = (await response.json()) as ApiError;
    return { detail: data.detail ?? GENERIC_ERROR, correlationId: data.correlation_id ?? null };
  } catch {
    return { detail: GENERIC_ERROR, correlationId: null };
  }
}
