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

  constructor(message: string, status: number) {
    super(message);
    this.name = "UploadError";
    this.status = status;
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
    throw new UploadError(await readErrorDetail(response), response.status);
  }

  return (await response.json()) as UploadAccepted;
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as ApiError;
    return data.detail ?? GENERIC_ERROR;
  } catch {
    return GENERIC_ERROR;
  }
}
