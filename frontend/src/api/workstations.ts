// Typed client for the Audit, OCR/Text, PII, and safe job-status endpoints.

import { jobActivityStore, pollJobUntilTerminal } from "../lib/jobActivity";

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

// Where one entity came from and how deterministic overlap resolution (PII L12) treated it.
// Structural only (recognizer names, reason codes, counts, ids) — never raw entity text (ADR-0028).
export interface PiiEntityProvenance {
  detection_source:
    | "raw_text"
    | "canonical_reading_text"
    | "structured_hint"
    | "projected"
    | "recognizer";
  source_role: "primary" | "contextual" | "structured_hint" | "quality_hint";
  recognizers: string[];
  candidate_count: number;
  merge_reason?: string | null;
  overlap_decision?: string | null;
  review_required: boolean;
  superseded_candidate_ids: string[];
  // Structural-context validation outcomes (ADR-0043). Additive/optional: omitted on artifacts
  // written before the stage, empty unless it clipped or trimmed this entity's span.
  structural_reasons?: string[];
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
  // Detection source/role and overlap-resolution outcome. Absent on legacy artifacts (ADR-0028).
  provenance?: PiiEntityProvenance | null;
}

// Records that PII consumed an OCR Output Contract v1 Document Text Package (ADR-0027/0028).
export interface PiiInputContractSummary {
  contract_version: string;
  contract_status: "valid" | "degraded" | "invalid";
  package_id: string;
  primary_source: "technical_raw_text";
  canonical_available: boolean;
  layout_available: boolean;
  structured_available: boolean;
  quality_evidence_available: boolean;
  warnings: string[];
  missing_optional_layers: string[];
}

// Deterministic overlap-resolution outcome counts (PII L12). Reason codes and counts only.
export interface PiiOverlapResolutionSummary {
  applied: boolean;
  input_candidate_count: number;
  output_entity_count: number;
  merged_count: number;
  dropped_count: number;
  review_required_count: number;
  by_reason: Record<string, number>;
}

export interface PiiStructuralValidationSummary {
  applied: boolean;
  input_candidate_count: number;
  output_entity_count: number;
  clipped_count: number;
  trimmed_count: number;
  dropped_count: number;
  by_reason: Record<string, number>;
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
    // OCR Output Contract v1 package PII consumed for this run. Absent on legacy artifacts.
    input_contract?: PiiInputContractSummary | null;
    // Deterministic overlap-resolution summary (PII L12). Absent on legacy artifacts.
    overlap_resolution?: PiiOverlapResolutionSummary | null;
    // Structural-context validation summary (ADR-0043). Absent on legacy artifacts or when the
    // stage was disabled for this run.
    structural_validation?: PiiStructuralValidationSummary | null;
  };
}

export interface PiiRunRequest {
  pii_profile: string;
}

export interface JobStatus {
  job_id: string;
  document_id: string;
  kind: "ocr_text" | "pii_detection";
  status: "pending" | "running" | "succeeded" | "failed" | "canceled";
  execution_mode: "synchronous_inline" | "future_worker";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
  result_artifact_id: string | null;
  result_artifact_type: string | null;
  metadata: Record<string, string>;
  // Additive (Runtime Job UX v1). Older cached/mocked responses may omit it; treat as unknown
  // rather than assuming terminal — callers should tolerate `undefined`.
  is_terminal?: boolean;
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

const OCR_JOB_POLL_INTERVAL_MS = 2000;
const OCR_JOB_TIMEOUT_MS = 30 * 60 * 1000;

const INCOMPATIBLE_PAYLOAD_DETAIL =
  "Die Serverantwort hat ein unbekanntes Format. Bitte laden Sie die Anwendung neu.";

/** A payload this build cannot understand. Never retryable: the response arrived fine and will
 * look exactly the same on the next attempt — polling code gives up immediately on it. */
export class IncompatibleApiPayloadError extends WorkstationApiError {
  readonly incompatiblePayload = true;

  constructor() {
    super(INCOMPATIBLE_PAYLOAD_DETAIL, 502);
    this.name = "IncompatibleApiPayloadError";
  }
}

const KNOWN_JOB_STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "running",
  "succeeded",
  "failed",
  "canceled",
]);

/**
 * Validate a job-status payload before it drives client behavior (ADR-0041).
 *
 * The polling loop's semantics hang off these fields — an unknown `status` could neither be
 * classified as terminal nor safely waited on, and a missing `job_id` would poll a nonsense URL —
 * so an incompatible payload fails closed with an explicit error instead of being accepted
 * through an unchecked cast. Additive unknown fields remain tolerated.
 */
function parseJobStatus(value: unknown): JobStatus {
  if (typeof value !== "object" || value === null) {
    throw new IncompatibleApiPayloadError();
  }
  const candidate = value as Record<string, unknown>;
  const requiredStrings = ["job_id", "document_id", "kind", "status", "created_at", "updated_at"];
  for (const field of requiredStrings) {
    if (typeof candidate[field] !== "string" || candidate[field] === "") {
      throw new IncompatibleApiPayloadError();
    }
  }
  if (!KNOWN_JOB_STATUSES.has(candidate.status as string)) {
    throw new IncompatibleApiPayloadError();
  }
  return value as JobStatus;
}

function parseJobStatusList(value: unknown): JobStatus[] {
  if (!Array.isArray(value)) {
    throw new IncompatibleApiPayloadError();
  }
  return value.map(parseJobStatus);
}

export function fetchAudit(documentId: string): Promise<AuditArtifact> {
  return requestArtifact<AuditArtifact>(documentId, "audit", "GET");
}

export function runAudit(documentId: string): Promise<AuditArtifact> {
  return requestArtifact<AuditArtifact>(documentId, "audit", "POST");
}

export function fetchOcr(documentId: string, artifactId?: string): Promise<TextArtifact> {
  const suffix = artifactId ? `?artifact_id=${encodeURIComponent(artifactId)}` : "";
  return requestArtifact<TextArtifact>(documentId, `ocr${suffix}`, "GET");
}

export async function runOcr(documentId: string): Promise<TextArtifact> {
  const response = await requestStation(documentId, "ocr", "POST");
  if (response.status === 202) {
    const queuedJob = parseJobStatus(await response.json());
    // Recorded immediately so any subscribed UI shows "accepted" before the first poll tick.
    jobActivityStore.record(queuedJob);
    const completedJob = await waitForOcrJob(queuedJob.job_id);
    if (!completedJob.result_artifact_id) {
      throw new WorkstationApiError("Das OCR-Ergebnis ist nicht verfügbar.", 502);
    }
    return fetchOcr(documentId, completedJob.result_artifact_id);
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as TextArtifact;
}

export function fetchPii(documentId: string): Promise<PiiArtifact> {
  return requestArtifact<PiiArtifact>(documentId, "pii", "GET");
}

/** Newest-first job metadata for one document (`GET /api/documents/{id}/jobs`). Used for reload
 * recovery when a job id was not (or could no longer be) tracked in `localStorage`. */
export async function fetchDocumentJobs(documentId: string): Promise<JobStatus[]> {
  let response: Response;
  try {
    response = await fetch(`/api/documents/${encodeURIComponent(documentId)}/jobs`, {
      method: "GET",
    });
  } catch {
    throw new WorkstationApiError("Keine Verbindung zum Server.", 0);
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return parseJobStatusList(await response.json());
}

export function runPii(documentId: string, request?: PiiRunRequest): Promise<PiiArtifact> {
  return requestArtifact<PiiArtifact>(documentId, "pii", "POST", request);
}

async function requestArtifact<T>(
  documentId: string,
  station: string,
  method: "GET" | "POST",
  body?: unknown,
): Promise<T> {
  const response = await requestStation(documentId, station, method, body);
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as T;
}

async function requestStation(
  documentId: string,
  station: string,
  method: "GET" | "POST",
  body?: unknown,
): Promise<Response> {
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
  return response;
}

export async function fetchJobStatus(jobId: string): Promise<JobStatus> {
  let response: Response;
  try {
    response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
  } catch {
    throw new WorkstationApiError("Keine Verbindung zum Server.", 0);
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return parseJobStatus(await response.json());
}

// Polling itself is owned by jobActivity's shared, de-duplicated poll loop (see
// `pollJobUntilTerminal`) so a reload-recovery resume can never race a live `runOcr` call into
// double-polling the same job id.
async function waitForOcrJob(jobId: string): Promise<JobStatus> {
  const job = await pollJobUntilTerminal(jobActivityStore, jobId, fetchJobStatus, {
    intervalMs: OCR_JOB_POLL_INTERVAL_MS,
    deadlineAt: Date.now() + OCR_JOB_TIMEOUT_MS,
  });
  if (job.status === "succeeded") {
    return job;
  }
  if (job.status === "failed" || job.status === "canceled") {
    throw jobStatusError(job);
  }
  // Still pending/running when the deadline was reached.
  throw new WorkstationApiError(
    "Die OCR-Verarbeitung dauert zu lange. Bitte versuchen Sie es später erneut.",
    504,
  );
}

function jobStatusError(job: JobStatus): WorkstationApiError {
  const status = statusFromJobErrorCode(job.error_code) ?? 500;
  const message =
    job.error_message && job.error_message !== ""
      ? job.error_message
      : "Die OCR-Verarbeitung ist fehlgeschlagen.";
  return new WorkstationApiError(message, status);
}

function statusFromJobErrorCode(errorCode: string | null): number | null {
  const match = errorCode?.match(/^api_error_(\d{3})$/);
  if (!match) {
    return null;
  }
  return Number(match[1]);
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
