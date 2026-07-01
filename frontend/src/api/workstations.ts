// Typed client for the synchronous Audit, OCR/Text, and PII workstation endpoints.

export interface AuditPageResult {
  page_number: number;
  text_char_count: number;
  has_text_layer: boolean;
}

export interface AuditArtifact {
  id: string;
  document_id: string;
  artifact_type: "audit_result";
  station: "audit";
  input_artifact_id: string;
  media_type: "application/json";
  created_at: string;
  content: {
    document_id: string;
    input_artifact_id: string;
    detected_mime_type: string;
    audit_version: "1";
    document_kind: "pdf" | "docx" | "image";
    page_count: number | null;
    paragraph_count: number | null;
    image_format: string | null;
    width: number | null;
    height: number | null;
    has_text_layer: boolean;
    text_char_count: number;
    pages: AuditPageResult[];
    flags: string[];
    tool_versions: Record<string, string>;
  };
}

export interface TextPageResult {
  page_number: number;
  source: "pdf_text_layer" | "paddleocr";
  has_text_layer: boolean;
  ocr_used: boolean;
  text: string;
  text_char_count: number;
}

export interface TextArtifact {
  id: string;
  document_id: string;
  artifact_type: "text_result";
  station: "ocr";
  input_artifact_id: string;
  input_audit_artifact_id: string;
  media_type: "application/json";
  created_at: string;
  content: {
    document_id: string;
    input_artifact_id: string;
    input_audit_artifact_id: string;
    source: "pdf_mixed" | "pdf_text_layer" | "docx_text" | "paddleocr";
    ocr_version: "1";
    text: string;
    text_char_count: number;
    pages: TextPageResult[];
    tool_versions: Record<string, string>;
    flags: string[];
  };
}

export interface PiiEntity {
  id: string;
  entity_type: string;
  text: string;
  start_offset: number;
  end_offset: number;
  page_number: number | null;
  page_start_offset: number | null;
  page_end_offset: number | null;
  score: number;
  recognizer: string;
}

export interface PiiArtifact {
  id: string;
  document_id: string;
  artifact_type: "pii_result";
  station: "pii";
  input_text_artifact_id: string;
  media_type: "application/json";
  created_at: string;
  content: {
    document_id: string;
    input_text_artifact_id: string;
    pii_version: "1";
    language: string;
    score_threshold: number;
    text_char_count: number;
    configured_entity_types: string[];
    entities: PiiEntity[];
    entity_counts: Record<string, number>;
    tool_versions: Record<string, string>;
    flags: string[];
  };
}

interface ApiError {
  detail?: string;
  correlation_id?: string | null;
}

export class WorkstationApiError extends Error {
  readonly status: number;
  readonly correlationId: string | null;

  constructor(message: string, status: number, correlationId: string | null = null) {
    super(message);
    this.name = "WorkstationApiError";
    this.status = status;
    this.correlationId = correlationId;
  }
}

type Station = "audit" | "ocr" | "pii";

export function fetchAudit(documentId: string): Promise<AuditArtifact> {
  return requestArtifact<AuditArtifact>(documentId, "audit", "GET");
}

export function runAudit(documentId: string): Promise<AuditArtifact> {
  return requestArtifact<AuditArtifact>(documentId, "audit", "POST");
}

export function fetchOcr(documentId: string): Promise<TextArtifact> {
  return requestArtifact<TextArtifact>(documentId, "ocr", "GET");
}

export function runOcr(documentId: string): Promise<TextArtifact> {
  return requestArtifact<TextArtifact>(documentId, "ocr", "POST");
}

export function fetchPii(documentId: string): Promise<PiiArtifact> {
  return requestArtifact<PiiArtifact>(documentId, "pii", "GET");
}

export function runPii(documentId: string): Promise<PiiArtifact> {
  return requestArtifact<PiiArtifact>(documentId, "pii", "POST");
}

async function requestArtifact<T>(
  documentId: string,
  station: Station,
  method: "GET" | "POST",
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/${station}`,
      { method },
    );
  } catch {
    throw new WorkstationApiError("Keine Verbindung zum Server.", 0);
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as T;
}

async function throwApiError(response: Response): Promise<never> {
  let detail = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";
  let correlationId: string | null = null;
  try {
    const data = (await response.json()) as ApiError;
    detail = data.detail ?? detail;
    correlationId = data.correlation_id ?? null;
  } catch {
    // Keep the safe fallback; response bodies must not be assumed to be JSON.
  }
  throw new WorkstationApiError(detail, response.status, correlationId);
}
