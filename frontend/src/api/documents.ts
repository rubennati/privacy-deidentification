// Typed client for the documents endpoints. Same-origin: nginx proxies
// /api to the backend.

export interface OriginalArtifact {
  id: string;
  document_id: string;
  kind: "original";
  storage_filename: string;
  sha256: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  size: number;
  content_type: string | null;
  uploaded_at: string;
  status: string;
  sha256: string | null;
  detected_mime_type: string | null;
  original_artifact: OriginalArtifact | null;
}

interface ApiError {
  detail?: string;
  correlation_id?: string | null;
}

export class DocumentsApiError extends Error {
  readonly status: number;
  readonly correlationId: string | null;

  constructor(message: string, status: number, correlationId: string | null = null) {
    super(message);
    this.name = "DocumentsApiError";
    this.status = status;
    this.correlationId = correlationId;
  }
}

const DOCUMENTS_ENDPOINT = "/api/documents";
const GENERIC_ERROR = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";

export async function fetchDocuments(): Promise<DocumentSummary[]> {
  const response = await safeFetch(DOCUMENTS_ENDPOINT);
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as DocumentSummary[];
}

export async function fetchDocument(id: string): Promise<DocumentSummary> {
  const response = await safeFetch(`${DOCUMENTS_ENDPOINT}/${encodeURIComponent(id)}`);
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as DocumentSummary;
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await safeFetch(`${DOCUMENTS_ENDPOINT}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
}

async function safeFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch {
    throw new DocumentsApiError("Keine Verbindung zum Server.", 0);
  }
}

async function throwApiError(response: Response): Promise<never> {
  let detail = GENERIC_ERROR;
  let correlationId: string | null = null;
  try {
    const data = (await response.json()) as ApiError;
    detail = data.detail ?? GENERIC_ERROR;
    correlationId = data.correlation_id ?? null;
  } catch {
    // keep defaults
  }
  throw new DocumentsApiError(detail, response.status, correlationId);
}
