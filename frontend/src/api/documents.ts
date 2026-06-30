// Typed client for the documents endpoints (list + delete). Same-origin: nginx proxies
// /api to the backend.

export interface DocumentSummary {
  id: string;
  filename: string;
  size: number;
  content_type: string | null;
  uploaded_at: string;
  status: string;
}

interface ApiError {
  detail?: string;
}

export class DocumentsApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "DocumentsApiError";
    this.status = status;
  }
}

const DOCUMENTS_ENDPOINT = "/api/documents";
const GENERIC_ERROR = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";

export async function fetchDocuments(): Promise<DocumentSummary[]> {
  const response = await safeFetch(DOCUMENTS_ENDPOINT);
  if (!response.ok) {
    throw new DocumentsApiError(await readErrorDetail(response), response.status);
  }
  return (await response.json()) as DocumentSummary[];
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await safeFetch(`${DOCUMENTS_ENDPOINT}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new DocumentsApiError(await readErrorDetail(response), response.status);
  }
}

async function safeFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch {
    throw new DocumentsApiError("Keine Verbindung zum Server.", 0);
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as ApiError;
    return data.detail ?? GENERIC_ERROR;
  } catch {
    return GENERIC_ERROR;
  }
}
