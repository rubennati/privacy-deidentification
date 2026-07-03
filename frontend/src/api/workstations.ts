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
  // Additive OCR L6 metrics. Legacy/text-layer pages may omit them or return null/empty values.
  ocr_confidence?: number | null;
  ocr_line_confidences?: Array<{
    line_index: number;
    confidence: number;
    text_char_count: number;
  }>;
}

export interface LayoutBlock {
  page_number: number;
  order: number;
  block_type: "heading" | "body" | "caption" | "header" | "footer" | "fallback";
  text: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  source: "pdf_text_layer" | "paddleocr" | "fallback";
  confidence?: number | null;
}

export interface TextLineGeometry {
  line_index: number;
  canonical_start: number;
  canonical_end: number;
  page_start: number;
  page_end: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  source: "pdf_text_layer" | "paddleocr" | "fallback";
  confidence?: number | null;
}

export interface TextGeometryPage {
  page_number: number;
  page_width: number;
  page_height: number;
  coordinate_unit: "pdf_points" | "image_pixels";
  source: "pdf_text_layer" | "paddleocr" | "fallback";
  status: "complete" | "partial" | "unsupported";
  lines: TextLineGeometry[];
}

export interface TextGeometry {
  pages: TextGeometryPage[];
  coverage: number;
  flags: string[];
}

export interface StructuredSpan {
  canonical_start: number;
  canonical_end: number;
  page_start: number;
  page_end: number;
}

export interface StructuredBounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  coordinate_unit: "pdf_points" | "image_pixels";
}

export interface StructuredTableCell {
  row_index: number;
  column_index: number;
  row_span: number;
  column_span: number;
  span: StructuredSpan;
  bounds?: StructuredBounds | null;
  role: "header" | "data" | "label" | "value" | "unknown";
}

export interface StructuredTable {
  table_id: string;
  page_number: number;
  row_count: number;
  column_count: number;
  cells: StructuredTableCell[];
  caption?: string | null;
  bounds?: StructuredBounds | null;
  source: "layout_blocks" | "text_geometry" | "canonical_text" | "hybrid";
  confidence: number;
  flags: string[];
}

export interface StructuredField {
  field_id: string;
  page_number: number;
  label: string;
  label_span: StructuredSpan;
  value_span: StructuredSpan;
  bounds?: StructuredBounds | null;
  field_type_hint:
    | "person_name"
    | "company"
    | "address"
    | "iban"
    | "contract_id"
    | "invoice_id"
    | "customer_id"
    | "date"
    | "phone"
    | "email"
    | "unknown";
  confidence: number;
  source: "layout_blocks" | "text_geometry" | "canonical_text" | "hybrid";
  flags: string[];
}

export interface StructuredSection {
  section_id: string;
  page_number: number;
  heading: string;
  heading_span: StructuredSpan;
  span: StructuredSpan;
  field_ids: string[];
  table_ids: string[];
  source: "layout_blocks" | "text_geometry" | "canonical_text" | "hybrid";
  confidence: number;
  flags: string[];
}

export interface StructuredContent {
  pages: Array<{
    page_number: number;
    tables: StructuredTable[];
    fields: StructuredField[];
    sections: StructuredSection[];
    source: "layout_blocks" | "text_geometry" | "canonical_text" | "hybrid";
    confidence: number;
    quality_flags: string[];
  }>;
  summary: {
    page_count: number;
    table_count: number;
    field_count: number;
    section_count: number;
  };
  flags: string[];
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
    // Optional OCR L8 readable rendering. Legacy artifacts omit it; canonical `text` stays the
    // only offset-bearing text and the active PII input.
    readable_text?: string | null;
    // OCR/Text L10.5 canonical reading text. It is the product-facing main text, while `text`
    // remains the legacy technical raw extraction and current PII offset basis.
    reading_text_version?: "1" | null;
    reading_text?: string | null;
    reading_text_status?: "heuristic" | "fallback" | null;
    reading_text_flags?: string[];
    reading_text_map_version?: "1" | null;
    reading_text_map?: Array<{
      reading_start: number;
      reading_end: number;
      raw_start: number;
      raw_end: number;
      page_number: number | null;
      mapping_status: "exact" | "normalized" | "partial";
      flags: string[];
    }>;
    // Optional display-only reconstruction. Legacy artifacts omit it; PII offsets stay on `text`.
    layout_text_result?: string | null;
    // Internal/experimental OCR L9 slice. It remains inactive as a PII input.
    pii_input_text?: string | null;
    // Additive OCR L9 review blocks with coarse normalized bounds and no offset guarantees.
    layout_blocks_version?: "1" | null;
    layout_blocks?: LayoutBlock[];
    // Additive OCR L10 span geometry: canonical line spans mapped to page-local line boxes for
    // review/debug. Not redaction-ready (that remains L15). Legacy artifacts omit it.
    text_geometry_version?: "1" | null;
    text_geometry?: TextGeometry | null;
    // Additive OCR L11 table/form structure. Values and cells stay span-backed; PII continues to
    // consume canonical `text` only.
    structured_content_version?: "1" | null;
    structured_content?: StructuredContent | null;
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
  // Engine-5 candidate validation. Absent on artifacts written before it existed.
  original_score?: number | null;
  validation_status?: "kept" | "score_down" | null;
  validation_reasons?: string[];
  reading_start_offset?: number | null;
  reading_end_offset?: number | null;
  projection_status?: "exact" | "partial" | "unmapped" | null;
  projection_method?: "offset_map" | "text_match" | null;
}

export interface PiiValidationSummary {
  enabled: boolean;
  kept: number;
  dropped: number;
  score_down: number;
  dropped_by_reason: Record<string, number>;
  score_down_by_reason: Record<string, number>;
}

export interface PiiArtifactEngineSettings {
  pii_profile: string;
  candidate_validation_enabled: boolean;
  score_threshold: number;
  source: "server-default" | "dev-ui-override";
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
    profile: string;
    language: string;
    score_threshold: number;
    text_char_count: number;
    reading_text_char_count?: number | null;
    configured_entity_types: string[];
    entities: PiiEntity[];
    entity_counts: Record<string, number>;
    tool_versions: Record<string, string>;
    flags: string[];
    // Engine-5 candidate validation summary. Absent on artifacts written before it existed.
    validation?: PiiValidationSummary | null;
    // Effective non-sensitive settings for this run. Absent on legacy artifacts.
    engine_settings?: PiiArtifactEngineSettings | null;
  };
}

export interface PiiRunRequest {
  pii_profile: string;
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

export function runPii(documentId: string, request?: PiiRunRequest): Promise<PiiArtifact> {
  return requestArtifact<PiiArtifact>(documentId, "pii", "POST", request);
}

async function requestArtifact<T>(
  documentId: string,
  station: Station,
  method: "GET" | "POST",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    const request: RequestInit = { method };
    if (body !== undefined) {
      request.headers = { "Content-Type": "application/json" };
      request.body = JSON.stringify(body);
    }
    response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/${station}`,
      request,
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
  const { detail, correlationId } = await readErrorBody(response);
  throw new WorkstationApiError(detail, response.status, correlationId);
}

const GENERIC_ERROR_DETAIL = "Die Anfrage ist fehlgeschlagen. Bitte versuchen Sie es erneut.";

/**
 * Reads the backend's JSON error envelope (`{detail, correlation_id}`) when the response actually
 * carries JSON. A non-JSON body — e.g. an nginx HTML `502`/`504` produced when the backend is
 * unreachable or was killed mid-request — is never surfaced: we return a safe generic message and
 * let the caller map the preserved HTTP status to a station-specific message. This guarantees raw
 * HTML/error text is never shown to the user (see toStationError for the 502/503/504 mapping).
 */
async function readErrorBody(
  response: Response,
): Promise<{ detail: string; correlationId: string | null }> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return { detail: GENERIC_ERROR_DETAIL, correlationId: null };
  }
  try {
    const data = (await response.json()) as ApiError;
    const detail =
      typeof data.detail === "string" && data.detail !== "" ? data.detail : GENERIC_ERROR_DETAIL;
    const correlationId = typeof data.correlation_id === "string" ? data.correlation_id : null;
    return { detail, correlationId };
  } catch {
    // A JSON content-type with an unparseable body still must not leak; keep the safe fallback.
    return { detail: GENERIC_ERROR_DETAIL, correlationId: null };
  }
}
