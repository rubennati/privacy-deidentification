"""Pydantic response models for the API (the trust-boundary contract)."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.pii_profiles import PiiProfileName


class OriginalArtifact(BaseModel):
    """Stored, byte-identical source artifact created for an uploaded document."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$", description="Server-generated artifact identifier.")
    document_id: str = Field(
        pattern=r"^[0-9a-f]{32}$", description="Identifier of the owning document."
    )
    kind: Literal["original"] = Field(default="original", description="Artifact role.")
    storage_filename: str = Field(
        pattern=r"^[0-9a-f]{32}\.[a-z0-9]{1,10}$",
        description="Server-side filename in upload storage.",
    )
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Lowercase SHA-256 digest of the stored bytes.",
    )
    mime_type: str = Field(description="MIME type verified from the stored content.")
    size_bytes: int = Field(description="Stored artifact size in bytes.", ge=0)
    created_at: str = Field(description="Artifact creation timestamp, UTC ISO 8601.")


class AuditPageResult(BaseModel):
    """Text-layer statistics and quality assessment for one PDF page.

    The quality fields are additive and optional so audit artifacts written before the text-layer
    quality gate still validate. ``has_text_layer`` keeps its original meaning (the page has any
    extractable text); ``needs_ocr`` is the routing decision derived from ``text_quality_status``.
    """

    page_number: int = Field(ge=1)
    text_char_count: int = Field(ge=0)
    has_text_layer: bool
    text_quality_status: (
        Literal[
            "GOOD_TEXT_LAYER",
            "LOW_CONFIDENCE_TEXT_LAYER",
            "BROKEN_TEXT_LAYER",
            "EMPTY_TEXT_LAYER",
        ]
        | None
    ) = None
    text_quality_score: int | None = Field(default=None, ge=0, le=100)
    text_quality_reasons: list[str] = Field(default_factory=list)
    recommended_text_source: Literal["text_layer", "ocr"] | None = None
    needs_ocr: bool | None = None


class AuditContent(BaseModel):
    """Versioned, format-specific output produced by the audit station."""

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    detected_mime_type: str
    audit_version: Literal["1"] = "1"
    document_kind: Literal["pdf", "docx", "image"]
    page_count: int | None = Field(default=None, ge=0)
    paragraph_count: int | None = Field(default=None, ge=0)
    image_format: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    has_text_layer: bool
    text_char_count: int = Field(ge=0)
    pages: list[AuditPageResult] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_pdf_page_summary(self) -> AuditContent:
        if self.document_kind != "pdf":
            return self
        if self.page_count != len(self.pages):
            raise ValueError("PDF page count does not match page results")
        if [page.page_number for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("PDF page numbers must be contiguous and start at 1")
        if self.text_char_count != sum(page.text_char_count for page in self.pages):
            raise ValueError("PDF text character count does not match page results")
        if self.has_text_layer != any(page.has_text_layer for page in self.pages):
            raise ValueError("PDF text-layer summary does not match page results")
        return self


class AuditArtifact(BaseModel):
    """Immutable JSON artifact emitted by the audit station."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_type: Literal["audit_result"] = "audit_result"
    station: Literal["audit"] = "audit"
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: Literal["application/json"] = "application/json"
    created_at: str
    content: AuditContent

    @model_validator(mode="after")
    def _validate_content_identity(self) -> AuditArtifact:
        if self.content.document_id != self.document_id:
            raise ValueError("audit content belongs to a different document")
        if self.content.input_artifact_id != self.input_artifact_id:
            raise ValueError("audit content references a different input artifact")
        return self


class OcrLineConfidence(BaseModel):
    """Metric-only confidence for one PaddleOCR-recognized line."""

    line_index: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    text_char_count: int = Field(ge=0)


class LayoutBlock(BaseModel):
    """One additive OCR L9 review block with coarse, page-relative bounds.

    Bounds describe only the block region used for deterministic ordering and display. They are
    not canonical offsets, reusable line/word geometry, or redaction-ready coordinates.
    """

    page_number: int = Field(ge=1)
    order: int = Field(ge=1)
    block_type: Literal["heading", "body", "caption", "header", "footer", "fallback"]
    text: str = Field(min_length=1)
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    source: Literal["pdf_text_layer", "paddleocr", "fallback"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_bounds_and_confidence(self) -> LayoutBlock:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("layout block bounds must have positive width and height")
        if self.confidence is not None and self.source != "paddleocr":
            raise ValueError("only PaddleOCR layout blocks may carry confidence")
        return self


class TextLineGeometry(BaseModel):
    """One additive OCR L10 line box mapping a canonical text span to a page-local region.

    Offsets are half-open. ``canonical_start``/``canonical_end`` index ``TextContent.text``;
    ``page_start``/``page_end`` index the matching ``TextContent.pages[].text``. ``bounds`` are
    page-local in the owning :class:`TextGeometryPage`'s ``coordinate_unit``. This is line-level
    source-anchoring geometry for review/debug and traceability, and a foundation for future
    placeholder mapping in AI-ready pseudonymized document generation. It does not perform
    pseudonymization, placeholder mapping, document export, or pixel-perfect visual redaction, and
    carries no raw line text.
    """

    line_index: int = Field(ge=1)
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(ge=0)
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)
    x0: float = Field(ge=0.0)
    y0: float = Field(ge=0.0)
    x1: float = Field(ge=0.0)
    y1: float = Field(ge=0.0)
    source: Literal["pdf_text_layer", "paddleocr", "fallback"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_line_geometry(self) -> TextLineGeometry:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("line box bounds must have x1 >= x0 and y1 >= y0")
        if self.canonical_end < self.canonical_start:
            raise ValueError("canonical offsets must have canonical_end >= canonical_start")
        if self.page_end < self.page_start:
            raise ValueError("page offsets must have page_end >= page_start")
        if self.confidence is not None and self.source != "paddleocr":
            raise ValueError("only PaddleOCR line geometry may carry confidence")
        return self


class TextGeometryPage(BaseModel):
    """Page-local line geometry for one page, plus its coordinate frame and coverage status."""

    page_number: int = Field(ge=1)
    page_width: float = Field(gt=0.0)
    page_height: float = Field(gt=0.0)
    coordinate_unit: Literal["pdf_points", "image_pixels"]
    source: Literal["pdf_text_layer", "paddleocr", "fallback"]
    status: Literal["complete", "partial", "unsupported"]
    lines: list[TextLineGeometry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_page_geometry(self) -> TextGeometryPage:
        if self.status == "unsupported" and self.lines:
            raise ValueError("unsupported geometry pages must not carry line boxes")
        if self.status != "unsupported" and not self.lines:
            raise ValueError("complete/partial geometry pages must carry at least one line box")
        indexes = [line.line_index for line in self.lines]
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("line indexes must be contiguous and start at 1 per page")
        for line in self.lines:
            if line.x1 > self.page_width or line.y1 > self.page_height:
                raise ValueError("line box bounds must be page-local")
        return self


class TextGeometry(BaseModel):
    """Versioned OCR L10 span geometry: an ordered set of per-page line boxes plus coverage."""

    pages: list[TextGeometryPage] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_geometry(self) -> TextGeometry:
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != sorted(page_numbers) or len(page_numbers) != len(set(page_numbers)):
            raise ValueError("geometry pages must have unique page numbers in sorted order")
        return self


class StructuredBounds(BaseModel):
    """Optional page-local bounds for one OCR L11 structure."""

    x0: float = Field(ge=0.0)
    y0: float = Field(ge=0.0)
    x1: float = Field(ge=0.0)
    y1: float = Field(ge=0.0)
    coordinate_unit: Literal["pdf_points", "image_pixels"]

    @model_validator(mode="after")
    def _validate_bounds(self) -> StructuredBounds:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("structured bounds must have positive width and height")
        return self


class StructuredSpan(BaseModel):
    """Half-open canonical and page-local offsets without duplicated source text."""

    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(ge=0)
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_offsets(self) -> StructuredSpan:
        if self.canonical_end <= self.canonical_start:
            raise ValueError("structured canonical span must be non-empty")
        if self.page_end <= self.page_start:
            raise ValueError("structured page span must be non-empty")
        if self.canonical_end - self.canonical_start != self.page_end - self.page_start:
            raise ValueError("structured canonical and page spans must have equal lengths")
        return self


class StructuredTableCell(BaseModel):
    """One table cell represented by offsets into immutable canonical/page text."""

    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    span: StructuredSpan
    bounds: StructuredBounds | None = None
    role: Literal["header", "data", "label", "value", "unknown"] = "unknown"


class StructuredTable(BaseModel):
    """Conservatively reconstructed OCR L11 table."""

    table_id: str = Field(pattern=r"^table-p[1-9][0-9]*-[1-9][0-9]*$")
    page_number: int = Field(ge=1)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    cells: list[StructuredTableCell] = Field(default_factory=list)
    caption: str | None = Field(default=None, min_length=1, max_length=160)
    bounds: StructuredBounds | None = None
    source: Literal["layout_blocks", "text_geometry", "canonical_text", "hybrid"]
    confidence: float = Field(ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_cells(self) -> StructuredTable:
        if not self.cells:
            if not self.flags:
                raise ValueError("empty structured tables must be flagged")
            return self
        if self.row_count == 0 or self.column_count == 0:
            raise ValueError("non-empty structured tables require rows and columns")
        keys: set[tuple[int, int]] = set()
        for cell in self.cells:
            if cell.row_index + cell.row_span > self.row_count:
                raise ValueError("table cell row index/span exceeds row count")
            if cell.column_index + cell.column_span > self.column_count:
                raise ValueError("table cell column index/span exceeds column count")
            key = (cell.row_index, cell.column_index)
            if key in keys:
                raise ValueError("table cells must have unique row/column indexes")
            keys.add(key)
        return self


class StructuredField(BaseModel):
    """A label/value pair whose value remains referenced, not duplicated."""

    field_id: str = Field(pattern=r"^field-p[1-9][0-9]*-[1-9][0-9]*$")
    page_number: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=80)
    label_span: StructuredSpan
    value_span: StructuredSpan
    bounds: StructuredBounds | None = None
    field_type_hint: Literal[
        "person_name",
        "company",
        "address",
        "iban",
        "contract_id",
        "invoice_id",
        "customer_id",
        "date",
        "phone",
        "email",
        "unknown",
    ] = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["layout_blocks", "text_geometry", "canonical_text", "hybrid"]
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pair(self) -> StructuredField:
        if self.label_span.canonical_end > self.value_span.canonical_start:
            raise ValueError("structured field label must precede its value")
        return self


class StructuredSection(BaseModel):
    """A simple heading-bound range containing reconstructed fields or tables."""

    section_id: str = Field(pattern=r"^section-p[1-9][0-9]*-[1-9][0-9]*$")
    page_number: int = Field(ge=1)
    heading: str = Field(min_length=1, max_length=160)
    heading_span: StructuredSpan
    span: StructuredSpan
    field_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    source: Literal["layout_blocks", "text_geometry", "canonical_text", "hybrid"]
    confidence: float = Field(ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_section_span(self) -> StructuredSection:
        if not (
            self.span.canonical_start <= self.heading_span.canonical_start
            and self.heading_span.canonical_end <= self.span.canonical_end
        ):
            raise ValueError("section span must contain its heading span")
        if not self.field_ids and not self.table_ids and not self.flags:
            raise ValueError("empty structured sections must be flagged")
        return self


class StructuredPageContent(BaseModel):
    """Structured OCR L11 output for one physical or logical page."""

    page_number: int = Field(ge=1)
    tables: list[StructuredTable] = Field(default_factory=list)
    fields: list[StructuredField] = Field(default_factory=list)
    sections: list[StructuredSection] = Field(default_factory=list)
    source: Literal["layout_blocks", "text_geometry", "canonical_text", "hybrid"]
    confidence: float = Field(ge=0.0, le=1.0)
    quality_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_page_structures(self) -> StructuredPageContent:
        item_page_numbers = [
            *(table.page_number for table in self.tables),
            *(field.page_number for field in self.fields),
            *(section.page_number for section in self.sections),
        ]
        if any(page_number != self.page_number for page_number in item_page_numbers):
            raise ValueError("structured item belongs to a different page")
        ids = [
            *(table.table_id for table in self.tables),
            *(field.field_id for field in self.fields),
            *(section.section_id for section in self.sections),
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("structured item ids must be unique per page")
        if not ids and not self.quality_flags:
            raise ValueError("empty structured pages must be flagged")
        field_ids = {field.field_id for field in self.fields}
        table_ids = {table.table_id for table in self.tables}
        for section in self.sections:
            if not set(section.field_ids) <= field_ids or not set(section.table_ids) <= table_ids:
                raise ValueError("structured section references an unknown item")
        return self


class StructuredContentSummary(BaseModel):
    """Metrics-only counts safe for logs and benchmark-style reporting."""

    page_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    field_count: int = Field(ge=0)
    section_count: int = Field(ge=0)


class StructuredContent(BaseModel):
    """Additive OCR L11 tables, fields, and sections beside canonical text."""

    pages: list[StructuredPageContent] = Field(default_factory=list)
    summary: StructuredContentSummary
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_summary(self) -> StructuredContent:
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != sorted(page_numbers) or len(page_numbers) != len(set(page_numbers)):
            raise ValueError("structured pages must have unique page numbers in sorted order")
        if not self.pages and not self.flags:
            raise ValueError("empty structured content must be flagged")
        expected = StructuredContentSummary(
            page_count=len(self.pages),
            table_count=sum(len(page.tables) for page in self.pages),
            field_count=sum(len(page.fields) for page in self.pages),
            section_count=sum(len(page.sections) for page in self.pages),
        )
        if self.summary != expected:
            raise ValueError("structured content summary does not match its pages")
        return self


def _structured_page_spans(page: StructuredPageContent) -> list[StructuredSpan]:
    return [
        *(cell.span for table in page.tables for cell in table.cells),
        *(field.label_span for field in page.fields),
        *(field.value_span for field in page.fields),
        *(section.heading_span for section in page.sections),
        *(section.span for section in page.sections),
    ]


def _validate_structured_page_text(
    page: StructuredPageContent,
    canonical_text: str,
    page_text: str,
    canonical_base: int,
) -> None:
    for span in _structured_page_spans(page):
        if span.canonical_end > len(canonical_text) or span.page_end > len(page_text):
            raise ValueError("structured span exceeds canonical or page text length")
        if canonical_text[span.canonical_start : span.canonical_end] != page_text[
            span.page_start : span.page_end
        ]:
            raise ValueError("structured canonical and page spans reference different text")
        if span.canonical_start != canonical_base + span.page_start:
            raise ValueError("structured canonical/page offsets are inconsistent")
    for field in page.fields:
        label = canonical_text[
            field.label_span.canonical_start : field.label_span.canonical_end
        ]
        if label != field.label:
            raise ValueError("structured field label does not match its canonical span")


class TextPageResult(BaseModel):
    """Ordered text extracted from one PDF or image page."""

    page_number: int = Field(ge=1)
    source: Literal["pdf_text_layer", "paddleocr"]
    has_text_layer: bool
    ocr_used: bool
    text: str
    text_char_count: int = Field(ge=0)
    # OCR L6 metrics are additive and never carry duplicate raw line text. Legacy artifacts omit
    # these fields; non-OCR pages keep ``None``/an empty list.
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ocr_line_confidences: list[OcrLineConfidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_page_summary(self) -> TextPageResult:
        if self.text_char_count != len(self.text):
            raise ValueError("page text character count does not match text")
        expected = (self.source == "pdf_text_layer", self.source == "paddleocr")
        if (self.has_text_layer, self.ocr_used) != expected:
            raise ValueError("page source does not match text-layer and OCR flags")
        if not self.ocr_used and (
            self.ocr_confidence is not None or self.ocr_line_confidences
        ):
            raise ValueError("non-OCR pages must not carry OCR confidence")
        line_indexes = [line.line_index for line in self.ocr_line_confidences]
        if line_indexes != sorted(set(line_indexes)):
            raise ValueError("OCR line confidence indexes must be unique and ordered")
        return self


class ReadingTextMapSegment(BaseModel):
    """Offset-only lineage from canonical reading text back to technical raw text."""

    reading_start: int = Field(ge=0)
    reading_end: int = Field(ge=1)
    raw_start: int = Field(ge=0)
    raw_end: int = Field(ge=1)
    page_number: int | None = Field(default=None, ge=1)
    mapping_status: Literal["exact", "normalized", "partial"]
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ranges(self) -> ReadingTextMapSegment:
        if self.reading_end <= self.reading_start or self.raw_end <= self.raw_start:
            raise ValueError("reading text map ranges must be non-empty and ordered")
        return self


# OCR/Text L14 quality evidence and lineage coverage. This is additive, metrics-only evidence about
# how the OCR/Text chain produced its artifact — where the text came from, how it was reconstructed,
# and how well the derived reading text maps back to technical raw text. It never carries raw
# document text: every locator is an offset range, page zone, coarse bound, count, flag, or stable
# reason code. It does not change PII input, PII decisions, or any existing text layer.
# OCR/Text L15 extends the same additive model with noise/token artifact *evidence* (see
# ocr_noise.py): glyph artifacts, suspicious token shapes, character-confusion candidates, and
# spacing candidates. It is suspicion, not truth — it never corrects, removes, or rewrites text.
QualityEvidenceLevel = Literal[
    "document",
    "page",
    "block",
    "row",
    "span",
    "table",
    "form",
    "reading_text",
    "structured_content",
    "projection_lineage",
]
QualityEvidenceType = Literal[
    "source_text",
    "pdf_text_layer",
    "ocr_engine",
    "positioned_rows",
    "page_geometry",
    "page_zone",
    "reading_order",
    "reading_text_map",
    "multi_column_reconstruction",
    "table_reconstruction",
    "form_reconstruction",
    "structured_content",
    "fallback",
    "skipped_reconstruction",
    "low_confidence",
    "lineage_coverage",
    "projection_lineage",
    # OCR/Text L15 noise/token artifact evidence types (see ocr_noise.py). These are additive,
    # deterministic shape-based *suspicion* signals — never a correction, never raw token text.
    "glyph_artifact",
    "suspicious_token_shape",
    "suspicious_spacing",
    "character_confusion",
    "low_information_symbol_run",
    "joined_word_candidate",
    "split_word_candidate",
    "non_text_artifact",
    "ocr_noise_summary",
]
QualityEvidenceStatus = Literal[
    "confident",
    "partial",
    "low_confidence",
    "skipped",
    "fallback",
    "unavailable",
    "not_applicable",
]
QualityPageZone = Literal[
    "header",
    "footer",
    "left_margin",
    "right_margin",
    "body",
    "unknown",
]
_QUALITY_STATUS_VALUES = frozenset(get_args(QualityEvidenceStatus))
_QUALITY_TYPE_VALUES = frozenset(get_args(QualityEvidenceType))


class QualityOffsetRange(BaseModel):
    """A half-open offset range used only to *locate* evidence; it never carries the text itself."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_range(self) -> QualityOffsetRange:
        if self.end < self.start:
            raise ValueError("quality evidence range end must be at least its start")
        return self


class QualityEvidenceBounds(BaseModel):
    """Coarse page-local bounds for a geometry/zone evidence item. Geometry only, no text."""

    x0: float = Field(ge=0.0)
    y0: float = Field(ge=0.0)
    x1: float = Field(ge=0.0)
    y1: float = Field(ge=0.0)
    coordinate_unit: Literal["pdf_points", "image_pixels", "normalized"]

    @model_validator(mode="after")
    def _validate_bounds(self) -> QualityEvidenceBounds:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("quality evidence bounds must have x1>=x0 and y1>=y0")
        return self


class QualityEvidenceItem(BaseModel):
    """One additive quality-evidence signal about the OCR/Text chain.

    Every locator is structural: offsets, a page number, a page zone, coarse bounds, counts, flags,
    and a stable machine-readable ``reason_code``. ``details`` is intentionally ``dict[str, int]``
    so no raw document text, snippet, or PII value can ever be stored here by construction.
    """

    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,79}$")
    level: QualityEvidenceLevel
    type: QualityEvidenceType
    status: QualityEvidenceStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    page_number: int | None = Field(default=None, ge=1)
    source_range: QualityOffsetRange | None = None
    raw_text_range: QualityOffsetRange | None = None
    reading_text_range: QualityOffsetRange | None = None
    bbox: QualityEvidenceBounds | None = None
    page_zone: QualityPageZone | None = None
    related_artifact: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    flags: list[str] = Field(default_factory=list)
    details: dict[str, int] = Field(default_factory=dict)


class QualityLineageCoverage(BaseModel):
    """How well canonical reading text maps back to technical raw text and source geometry."""

    reading_text_length: int = Field(ge=0)
    mapped_reading_text_chars: int = Field(ge=0)
    unmapped_reading_text_chars: int = Field(ge=0)
    mapping_coverage_ratio: float = Field(ge=0.0, le=1.0)
    exact_span_count: int = Field(ge=0)
    partial_span_count: int = Field(ge=0)
    unmapped_span_count: int = Field(ge=0)
    source_geometry_coverage_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    structured_content_reference_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_coverage(self) -> QualityLineageCoverage:
        if (
            self.mapped_reading_text_chars + self.unmapped_reading_text_chars
            != self.reading_text_length
        ):
            raise ValueError("mapped and unmapped reading chars must sum to reading text length")
        return self


class QualityEvidenceSummary(BaseModel):
    """Document-level roll-up of the evidence items plus lineage coverage.

    ``overall_score`` is an advisory 0.0-1.0 confidence blend, never a gate. ``counts_by_status``
    and ``counts_by_type`` are derived from the items and validated for consistency by
    :class:`QualityEvidence`.
    """

    overall_status: QualityEvidenceStatus
    overall_score: float | None = Field(default=None, ge=0.0, le=1.0)
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    reconstruction_summary: dict[str, int] = Field(default_factory=dict)
    fallback_summary: dict[str, int] = Field(default_factory=dict)
    lineage_summary: QualityLineageCoverage

    @model_validator(mode="after")
    def _validate_count_keys(self) -> QualityEvidenceSummary:
        if any(status not in _QUALITY_STATUS_VALUES for status in self.counts_by_status):
            raise ValueError("counts_by_status has an unknown status key")
        if any(type_ not in _QUALITY_TYPE_VALUES for type_ in self.counts_by_type):
            raise ValueError("counts_by_type has an unknown type key")
        return self


class QualityEvidence(BaseModel):
    """Additive OCR/Text L14 quality evidence and lineage coverage beside canonical text."""

    items: list[QualityEvidenceItem] = Field(default_factory=list)
    summary: QualityEvidenceSummary

    @model_validator(mode="after")
    def _validate_items(self) -> QualityEvidence:
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("quality evidence items must have unique ids")
        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for item in self.items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
            type_counts[item.type] = type_counts.get(item.type, 0) + 1
        if self.summary.counts_by_status != dict(sorted(status_counts.items())):
            raise ValueError("quality evidence status counts do not match items")
        if self.summary.counts_by_type != dict(sorted(type_counts.items())):
            raise ValueError("quality evidence type counts do not match items")
        return self


class TextContent(BaseModel):
    """Versioned text output produced by the OCR workstation."""

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_audit_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source: Literal["pdf_mixed", "pdf_text_layer", "docx_text", "paddleocr"]
    ocr_version: Literal["1"] = "1"
    text: str
    text_char_count: int = Field(ge=0)
    pages: list[TextPageResult] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    # Additive, optional OCR L8 readable rendering. It normalizes whitespace, paragraph joins, and
    # simple line-break hyphenation for humans, but it is never the technical raw offset text or PII
    # input, and carries no offset/lineage guarantee. Legacy artifacts may omit it.
    readable_text: str | None = Field(default=None)
    # Additive OCR/Text L10.5 canonical reading text. This is the deterministic, block-aware main
    # text for human reading and a future PII/placeholder-input candidate. It deliberately carries
    # no offset/lineage guarantee yet: the legacy technical extraction in ``text`` remains the
    # byte-stable offset basis and active PII input. All fields are optional/defaulted so artifacts
    # written before L10.5 remain valid.
    reading_text_version: Literal["1"] | None = None
    reading_text: str | None = Field(default=None)
    reading_text_status: Literal["heuristic", "fallback"] | None = None
    reading_text_flags: list[str] = Field(default_factory=list)
    reading_text_map_version: Literal["1"] | None = None
    reading_text_map: list[ReadingTextMapSegment] = Field(default_factory=list)
    # Additive, optional human-readable layout reconstruction (OCR L9). It never feeds PII and is
    # not the raw offset text: ``text`` above stays the offset-stable coordinate source. ``None``
    # when no layout was reconstructed (e.g. DOCX, image, or all-OCR documents), so legacy artifacts
    # without this field remain valid. See docs/engine/ocr-layout-text-contract.md.
    layout_text_result: str | None = Field(default=None)
    # Additive, optional, INTERNAL semantic reading-order reconstruction (OCR L9 slice; PII-input
    # v1). Not yet the active PII detection input — PII continues to run on ``text`` above — and not
    # displayed in the UI. It groups two-column blocks and reconstructs table rows for PDF
    # text-layer pages only; ``None`` when not reconstructed (DOCX, image, all-OCR documents, or a
    # page geometry could not be established). See docs/engine/ocr-layout-text-contract.md.
    pii_input_text: str | None = Field(default=None)
    # OCR L9 additive review model. These are coarse page regions used only for ordering/typing;
    # they carry no canonical offsets and are not reusable L10 line/word geometry. Both fields are
    # optional/defaulted so pre-L9 artifacts remain valid.
    layout_blocks_version: Literal["1"] | None = None
    layout_blocks: list[LayoutBlock] = Field(default_factory=list)
    # OCR L10 additive span geometry. It maps canonical line spans to page-local line boxes for
    # source anchoring, review/debug, and traceability — a foundation for future placeholder mapping
    # in AI-ready pseudonymized document generation. It does NOT perform pseudonymization,
    # placeholder mapping, document export, or pixel-perfect visual redaction, and never changes
    # ``text``/``pages``/PII input. Both fields are optional/defaulted so pre-L10 artifacts remain
    # valid.
    text_geometry_version: Literal["1"] | None = None
    text_geometry: TextGeometry | None = None
    # OCR L11 additive semantic structure. Values and table contents are represented by spans into
    # immutable canonical/page text; only short labels/headings are repeated. It is not a PII input,
    # pseudonymization layer, placeholder map, redaction model, or export format.
    structured_content_version: Literal["1"] | None = None
    structured_content: StructuredContent | None = None
    # OCR L14 additive quality evidence and lineage coverage. Metrics-only: it records where the
    # text came from, how it was reconstructed, and how well the derived reading text maps back to
    # technical raw text — using offsets, counts, flags, page zones, and stable reason codes, never
    # raw text. It is not a PII input, does not change PII decisions, and reorders/deletes nothing.
    # Both fields are optional/defaulted so artifacts written before L14 remain valid.
    quality_evidence_version: Literal["1"] | None = None
    quality_evidence: QualityEvidence | None = None

    @model_validator(mode="after")
    def _validate_quality_evidence(self) -> TextContent:
        if (self.quality_evidence is not None) != (self.quality_evidence_version == "1"):
            raise ValueError("quality evidence and version must be present together")
        if self.quality_evidence is None:
            return self
        reading_length = len(self.reading_text or "")
        lineage = self.quality_evidence.summary.lineage_summary
        if lineage.reading_text_length != reading_length:
            raise ValueError("quality evidence reading length does not match reading text")
        raw_length = len(self.text)
        for item in self.quality_evidence.items:
            if item.raw_text_range is not None and item.raw_text_range.end > raw_length:
                raise ValueError("quality evidence raw range exceeds technical raw text length")
            if (
                item.reading_text_range is not None
                and item.reading_text_range.end > reading_length
            ):
                raise ValueError("quality evidence reading range exceeds reading text length")
        return self

    @model_validator(mode="after")
    def _validate_structured_content(self) -> TextContent:
        if (self.structured_content is not None) != (self.structured_content_version == "1"):
            raise ValueError("structured content and version must be present together")
        if self.structured_content is None:
            return self
        pages_by_number = {page.page_number: page for page in self.pages}
        canonical_bases: dict[int, int] = {}
        canonical_base = 0
        for text_page in self.pages:
            canonical_bases[text_page.page_number] = canonical_base
            canonical_base += len(text_page.text) + 2
        for structured_page in self.structured_content.pages:
            matching_page = pages_by_number.get(structured_page.page_number)
            if matching_page is None:
                if self.source != "docx_text" or structured_page.page_number != 1:
                    raise ValueError("structured content references a missing page")
                page_text = self.text
                canonical_base = 0
            else:
                page_text = matching_page.text
                canonical_base = canonical_bases[structured_page.page_number]
            _validate_structured_page_text(
                structured_page, self.text, page_text, canonical_base
            )
        return self

    @model_validator(mode="after")
    def _validate_reading_text(self) -> TextContent:
        has_reading_text = self.reading_text is not None
        if has_reading_text != (self.reading_text_version == "1"):
            raise ValueError("reading text and version must be present together")
        if has_reading_text != (self.reading_text_status is not None):
            raise ValueError("reading text and status must be present together")
        if not has_reading_text and self.reading_text_flags:
            raise ValueError("reading text flags require reading text")
        if self.reading_text is not None and not self.reading_text.strip():
            raise ValueError("reading text must contain non-whitespace content")
        return self

    @model_validator(mode="after")
    def _validate_reading_text_map(self) -> TextContent:
        if self.reading_text_map and self.reading_text_map_version != "1":
            raise ValueError("reading text map requires its version")
        if self.reading_text_map_version == "1" and self.reading_text is None:
            raise ValueError("reading text map requires reading text")
        previous_reading_end = 0
        raw_ranges: list[tuple[int, int]] = []
        for segment in self.reading_text_map:
            if segment.reading_start < previous_reading_end:
                raise ValueError("reading text map segments must be ordered and non-overlapping")
            if segment.reading_end > len(self.reading_text or ""):
                raise ValueError("reading text map offsets exceed reading text length")
            if segment.raw_end > len(self.text):
                raise ValueError("reading text map offsets exceed raw text length")
            if any(
                segment.raw_start < end and start < segment.raw_end
                for start, end in raw_ranges
            ):
                raise ValueError("reading text map raw ranges must not overlap")
            previous_reading_end = segment.reading_end
            raw_ranges.append((segment.raw_start, segment.raw_end))
        return self

    @model_validator(mode="after")
    def _validate_text_geometry(self) -> TextContent:
        if (self.text_geometry is not None) != (self.text_geometry_version == "1"):
            raise ValueError("text geometry and version must be present together")
        if self.text_geometry is None:
            return self
        pages_by_number = {page.page_number: page for page in self.pages}
        for geometry_page in self.text_geometry.pages:
            page = pages_by_number.get(geometry_page.page_number)
            if page is None:
                raise ValueError("geometry references a page with no canonical text")
            for line in geometry_page.lines:
                if line.canonical_end > self.text_char_count:
                    raise ValueError("canonical geometry offsets exceed canonical text length")
                if line.page_end > page.text_char_count:
                    raise ValueError("page geometry offsets exceed page text length")
        return self

    @model_validator(mode="after")
    def _validate_layout_blocks(self) -> TextContent:
        if bool(self.layout_blocks) != (self.layout_blocks_version == "1"):
            raise ValueError("layout blocks and version must be present together")
        block_keys = [(block.page_number, block.order) for block in self.layout_blocks]
        if block_keys != sorted(block_keys) or len(block_keys) != len(set(block_keys)):
            raise ValueError("layout blocks must have unique page/order keys in sorted order")
        for page_number in sorted({block.page_number for block in self.layout_blocks}):
            orders = [
                block.order for block in self.layout_blocks if block.page_number == page_number
            ]
            if orders != list(range(1, len(orders) + 1)):
                raise ValueError("layout block order must be contiguous and start at 1 per page")
        return self

    @model_validator(mode="after")
    def _validate_text_summary(self) -> TextContent:
        if self.text_char_count != len(self.text):
            raise ValueError("text character count does not match text")
        if self.source == "docx_text":
            if self.pages:
                raise ValueError("DOCX text must not contain synthetic pages")
            return self
        if [page.page_number for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("text page numbers must be contiguous and start at 1")
        if self.text != "\n\n".join(page.text for page in self.pages):
            raise ValueError("combined text does not match ordered page text")
        if self.pages:
            page_sources = {page.source for page in self.pages}
            expected_source = (
                "pdf_mixed"
                if len(page_sources) > 1
                else next(iter(page_sources))
            )
            if self.source != expected_source:
                raise ValueError("text source does not match page sources")
        return self


class TextArtifact(BaseModel):
    """Immutable JSON artifact emitted by the OCR workstation."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_type: Literal["text_result"] = "text_result"
    station: Literal["ocr"] = "ocr"
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_audit_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: Literal["application/json"] = "application/json"
    created_at: str
    content: TextContent

    @model_validator(mode="after")
    def _validate_content_identity(self) -> TextArtifact:
        if self.content.document_id != self.document_id:
            raise ValueError("text content belongs to a different document")
        if self.content.input_artifact_id != self.input_artifact_id:
            raise ValueError("text content references a different original artifact")
        if self.content.input_audit_artifact_id != self.input_audit_artifact_id:
            raise ValueError("text content references a different audit artifact")
        return self


class QualityReportContent(BaseModel):
    """Metrics-only OCR/Text quality summary linked to exact immutable inputs."""

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_audit_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    quality_report_version: Literal["1"] = "1"
    page_count: int = Field(ge=0)
    text_layer_pages: int = Field(ge=0)
    ocr_pages: int = Field(ge=0)
    mixed_source: bool
    text_source: Literal["pdf_mixed", "pdf_text_layer", "docx_text", "paddleocr"]
    good_text_layer_pages: int = Field(ge=0)
    low_confidence_text_layer_pages: int = Field(ge=0)
    broken_text_layer_pages: int = Field(ge=0)
    empty_text_layer_pages: int = Field(ge=0)
    pages_needing_ocr: int = Field(ge=0)
    ocr_pages_with_confidence: int = Field(ge=0)
    ocr_lines_with_confidence: int = Field(ge=0)
    ocr_page_confidence_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    ocr_page_confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    ocr_page_confidence_max: float | None = Field(default=None, ge=0.0, le=1.0)
    final_char_count: int = Field(ge=0)
    final_word_count: int = Field(ge=0)
    pages_without_text: int = Field(ge=0)
    flags: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_page_counts(self) -> QualityReportContent:
        if self.text_layer_pages + self.ocr_pages != self.page_count:
            raise ValueError("quality report source counts do not match page count")
        if self.mixed_source != (self.text_layer_pages > 0 and self.ocr_pages > 0):
            raise ValueError("quality report mixed-source flag does not match source counts")
        if self.pages_needing_ocr > self.page_count:
            raise ValueError("quality report OCR routing count exceeds page count")
        if self.pages_without_text > self.page_count:
            raise ValueError("quality report empty-output count exceeds page count")
        if self.ocr_pages_with_confidence > self.ocr_pages:
            raise ValueError("quality report confidence coverage exceeds OCR page count")
        audit_quality_pages = (
            self.good_text_layer_pages
            + self.low_confidence_text_layer_pages
            + self.broken_text_layer_pages
            + self.empty_text_layer_pages
        )
        if audit_quality_pages > self.page_count:
            raise ValueError("quality report audit quality counts exceed page count")
        return self

    @model_validator(mode="after")
    def _validate_confidence_summary(self) -> QualityReportContent:
        confidence_values = (
            self.ocr_page_confidence_mean,
            self.ocr_page_confidence_min,
            self.ocr_page_confidence_max,
        )
        if self.ocr_pages_with_confidence == 0:
            if any(value is not None for value in confidence_values):
                raise ValueError("quality report has confidence values without covered OCR pages")
        elif any(value is None for value in confidence_values):
            raise ValueError("quality report confidence summary is incomplete")
        else:
            confidence_mean = self.ocr_page_confidence_mean
            confidence_min = self.ocr_page_confidence_min
            confidence_max = self.ocr_page_confidence_max
            if confidence_mean is None or confidence_min is None or confidence_max is None:
                raise ValueError("quality report confidence summary is incomplete")
            if not confidence_min <= confidence_mean <= confidence_max:
                raise ValueError("quality report confidence range is inconsistent")
        return self

    @model_validator(mode="after")
    def _validate_source(self) -> QualityReportContent:
        if self.mixed_source != (self.text_source == "pdf_mixed"):
            raise ValueError("quality report text source does not match source mix")
        if self.text_source == "docx_text" and self.page_count != 0:
            raise ValueError("DOCX quality reports must not contain synthetic pages")
        if self.text_source == "pdf_text_layer" and self.ocr_pages:
            raise ValueError("text-layer quality report unexpectedly contains OCR pages")
        if self.text_source == "paddleocr" and self.text_layer_pages:
            raise ValueError("OCR quality report unexpectedly contains text-layer pages")
        return self


class QualityReportArtifact(BaseModel):
    """Immutable, metrics-only quality artifact emitted after OCR/Text extraction."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_type: Literal["quality_report"] = "quality_report"
    station: Literal["ocr_quality"] = "ocr_quality"
    input_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_audit_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: Literal["application/json"] = "application/json"
    created_at: str
    content: QualityReportContent

    @model_validator(mode="after")
    def _validate_content_identity(self) -> QualityReportArtifact:
        if self.content.document_id != self.document_id:
            raise ValueError("quality report content belongs to a different document")
        if self.content.input_artifact_id != self.input_artifact_id:
            raise ValueError("quality report references a different original artifact")
        if self.content.input_audit_artifact_id != self.input_audit_artifact_id:
            raise ValueError("quality report references a different audit artifact")
        if self.content.input_text_artifact_id != self.input_text_artifact_id:
            raise ValueError("quality report references a different text artifact")
        return self


# OCR Output Contract v1 / Document Text Package (ADR-0027). An additive, versioned,
# consumer-facing packaging of one OCR/Text artifact's already-produced layers (technical raw text,
# canonical reading text, layout text, structured content, and quality evidence) under explicit
# source roles and a trust status. It is a derived, read-only view built on demand from an existing
# immutable ``TextArtifact`` (see ``document_text_package.py``) — never persisted as its own
# artifact, never mutates its source, and adds no new raw document text beyond what ``TextArtifact``
# already carries. This is the stable boundary PII, Review, pseudonymization, document analysis,
# export, and future local AI are meant to depend on instead of ``TextContent`` internals or the
# OCR/PDF tools that produced them. PII does not consume this contract yet. See
# docs/adr/0027-ocr-output-contract-v1-strategy.md and docs/engine/ocr-layout-text-contract.md.
DocumentTextPackageStatus = Literal["valid", "degraded", "invalid"]
DocumentTextSourceName = Literal[
    "technical_raw_text",
    "canonical_reading_text",
    "layout_text",
    "structured_content",
    "quality_evidence",
]
DocumentTextSourceRole = Literal[
    "authoritative_source_text",
    "human_readable_derived_text",
    "visual_debug_text",
    "semantic_structure_hints",
    "trust_uncertainty_hints",
]
# Stable, machine-readable codes used in ``warnings``/``blockers``. New codes may be added over time
# as additive OCR evidence sources plug into the contract (dictionary/lexicon, multi-OCR, local-LLM
# hints); a code is never removed or repurposed once shipped.
DocumentTextPackageWarning = Literal[
    "missing_required_raw_text",
    "missing_document_id",
    "invalid_text_source",
    "unsupported_contract_version",
    "missing_canonical_reading_text",
    "missing_layout_text",
    "missing_structured_content",
    "missing_quality_evidence",
    "missing_noise_evidence",
    "partial_lineage",
    "missing_mapping",
    "legacy_artifact",
]


class DocumentTextPackageProcessingMetadata(BaseModel):
    """Metrics-only extraction summary copied from the source ``TextContent``. No raw text."""

    text_source: Literal["pdf_mixed", "pdf_text_layer", "docx_text", "paddleocr"]
    page_count: int = Field(ge=0)
    ocr_used: bool
    text_layer_used: bool
    tool_versions: dict[str, str] = Field(default_factory=dict)


class DocumentTextSourceV1(BaseModel):
    """One packaged layer with an explicit, consumer-facing role.

    Source role semantics (see ADR-0027): raw text is authoritative; canonical reading text is a
    derived, non-authoritative convenience view; layout text is visual/debug/review-oriented;
    structured content is semantic hints, not primary truth; quality evidence is trust/uncertainty
    metadata, never a correction. Consumers must not assume an optional layer exists, and must not
    treat canonical reading text as the sole authoritative source.

    ``text`` carries the actual layer content only for the three text-bearing roles
    (raw/canonical/layout) — allowed because the package *is* the text artifact for those roles.
    ``structured_content`` and ``quality_evidence`` are exposed as their own typed fields on
    :class:`DocumentTextPackageV1` instead of being duplicated here, so those two entries only index
    availability/role/flags.
    """

    name: DocumentTextSourceName
    role: DocumentTextSourceRole
    required: bool
    available: bool
    text: str | None = None
    text_char_count: int | None = Field(default=None, ge=0)
    status: str | None = None
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_text_char_count(self) -> DocumentTextSourceV1:
        if self.text is not None and self.text_char_count != len(self.text):
            raise ValueError("text source char count does not match its text")
        if self.text is None and self.text_char_count is not None:
            raise ValueError("text source char count requires text")
        return self


class DocumentTextPackageValidationSummary(BaseModel):
    """Compact, machine-checkable rollup of the contract validation outcome."""

    contract_status: DocumentTextPackageStatus
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    missing_capability_count: int = Field(ge=0)
    required_sources_satisfied: bool
    available_source_count: int = Field(ge=0)
    total_source_count: int = Field(ge=0)


class DocumentTextPackageV1(BaseModel):
    """OCR Output Contract v1 — the stable, versioned, consumer-facing package for one OCR/Text
    artifact (ADR-0027).

    A derived, read-only view over an existing immutable :class:`TextArtifact`: it packages
    already-produced layers under one contract with explicit source roles and a trust status, so
    consumers depend on this contract rather than on ``TextContent`` internals or the OCR/PDF tools
    that produced them. ``package_id``/``text_artifact_id``/``created_at`` mirror the source
    ``TextArtifact`` — the package is a deterministic 1:1 view over exactly one text artifact in v1
    — so building the same input twice yields an identical package. Building this package changes no
    OCR/Text behavior and mutates no source artifact; PII is not migrated onto it yet.
    """

    contract_version: Literal["1.0"] = "1.0"
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: str
    contract_status: DocumentTextPackageStatus
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    processing_metadata: DocumentTextPackageProcessingMetadata
    text_sources: list[DocumentTextSourceV1]
    structured_content: StructuredContent | None = None
    quality_evidence: QualityEvidence | None = None
    reading_text_map: list[ReadingTextMapSegment] = Field(default_factory=list)
    contract_validation_summary: DocumentTextPackageValidationSummary

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> DocumentTextPackageV1:
        if self.contract_status == "invalid" and not self.blockers:
            raise ValueError("invalid contract status requires at least one blocker")
        if self.contract_status != "invalid" and self.blockers:
            raise ValueError("blockers are only present when contract status is invalid")
        if self.contract_status == "degraded" and not self.warnings:
            raise ValueError("degraded contract status requires at least one warning")
        if self.contract_status == "valid" and self.warnings:
            raise ValueError("valid contract status must not carry warnings")
        return self

    @model_validator(mode="after")
    def _validate_sources_and_summary(self) -> DocumentTextPackageV1:
        names = [source.name for source in self.text_sources]
        if len(names) != len(set(names)):
            raise ValueError("text sources must have unique names")
        required_available = all(
            source.available for source in self.text_sources if source.required
        )
        available_count = sum(1 for source in self.text_sources if source.available)
        summary = self.contract_validation_summary
        if summary.contract_status != self.contract_status:
            raise ValueError("validation summary status does not match contract status")
        if summary.warning_count != len(self.warnings):
            raise ValueError("validation summary warning count does not match warnings")
        if summary.blocker_count != len(self.blockers):
            raise ValueError("validation summary blocker count does not match blockers")
        if summary.missing_capability_count != len(self.missing_capabilities):
            raise ValueError(
                "validation summary missing-capability count does not match missing capabilities"
            )
        if summary.required_sources_satisfied != required_available:
            raise ValueError("validation summary required-sources flag is inconsistent")
        if summary.total_source_count != len(self.text_sources):
            raise ValueError("validation summary total source count does not match text sources")
        if summary.available_source_count != available_count:
            raise ValueError("validation summary available source count is inconsistent")
        return self


# --- PII intake contract + entity provenance (ADR-0028) ------------------------------------------
# PII consumes the OCR Output Contract v1 Document Text Package (ADR-0027) through the ``pii_input``
# adapter and resolves overlapping candidates deterministically (``pii_overlap``). The additive,
# optional models below record, on the immutable ``pii_result``, which contract PII consumed and how
# overlaps were resolved — all structural (reason codes, counts, recognizer names, other entities'
# ids), never a copy of raw document or entity text. Legacy artifacts omit them and stay valid.
PiiInputSourceRole = Literal["primary", "contextual", "structured_hint", "quality_hint"]
PiiEntityDetectionSource = Literal[
    "raw_text",
    "canonical_reading_text",
    "structured_hint",
    "projected",
    "recognizer",
]
# Stable, machine-readable overlap-resolution reason codes. Deterministic engine-level precedence
# for duplicate/nested/overlapping candidates (PII L12). A code is never removed or repurposed.
PiiOverlapReason = Literal[
    "exact_duplicate",
    "same_type_overlap",
    "nested_entity",
    "conflicting_entity_type",
    "projected_same_source",
    "recognizer_duplicate",
    "stronger_confidence_selected",
    "longer_span_selected",
    "ambiguous_overlap_review_required",
    "dropped_lower_confidence_duplicate",
    "merged_provenance",
]


class PiiEntityProvenance(BaseModel):
    """Where one final PII entity came from and how deterministic overlap resolution treated it.

    Structural only: a detection source/role, contributing recognizer names, a merged-candidate
    count, overlap reason codes, and the ids of any competing candidates this entity superseded. It
    never stores raw document or entity text — the entity's own value stays in ``PiiEntity.text``
    and is not duplicated here.
    """

    detection_source: PiiEntityDetectionSource = "raw_text"
    source_role: PiiInputSourceRole = "primary"
    recognizers: list[str] = Field(default_factory=list)
    candidate_count: int = Field(default=1, ge=1)
    merge_reason: PiiOverlapReason | None = None
    overlap_decision: PiiOverlapReason | None = None
    review_required: bool = False
    superseded_candidate_ids: list[str] = Field(default_factory=list)


class PiiInputContractSummary(BaseModel):
    """Records that PII consumed a ``DocumentTextPackageV1`` and which layers/status it saw.

    Lets a ``pii_result`` say, from the artifact alone, that PII depended on the OCR Output Contract
    v1 boundary rather than OCR internals: the contract version/status, the primary detection source
    (always technical raw text today), which optional layers were present, and the contract's own
    warning/missing-capability codes. Metadata only, no raw text.
    """

    contract_version: str
    contract_status: DocumentTextPackageStatus
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    primary_source: Literal["technical_raw_text"] = "technical_raw_text"
    canonical_available: bool
    layout_available: bool
    structured_available: bool
    quality_evidence_available: bool
    warnings: list[str] = Field(default_factory=list)
    missing_optional_layers: list[str] = Field(default_factory=list)


class PiiOverlapResolutionSummary(BaseModel):
    """Deterministic overlap-resolution outcome. Reason codes and counts only, never entity text."""

    applied: bool
    input_candidate_count: int = Field(ge=0)
    output_entity_count: int = Field(ge=0)
    merged_count: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    by_reason: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_counts(self) -> PiiOverlapResolutionSummary:
        if self.input_candidate_count != self.output_entity_count + self.merged_count + (
            self.dropped_count
        ):
            raise ValueError("input candidates must equal output plus merged plus dropped")
        return self


class PiiEntity(BaseModel):
    """One labeled PII span referencing the source text exactly."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    text: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    page_number: int | None = Field(default=None, ge=1)
    page_start_offset: int | None = Field(default=None, ge=0)
    page_end_offset: int | None = Field(default=None, ge=1)
    score: float = Field(ge=0, le=1)
    recognizer: str
    original_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Detection score before Engine-5 candidate validation. None on artifacts written "
            "before candidate validation existed, or equal to score when validation kept the "
            "candidate unchanged."
        ),
    )
    validation_status: Literal["kept", "score_down"] | None = Field(
        default=None,
        description=(
            "Candidate validation verdict for this surviving entity. None on artifacts written "
            "before candidate validation existed. Dropped candidates never appear here."
        ),
    )
    validation_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Machine-readable validation reason codes; empty unless validation_status is "
            "score_down."
        ),
    )
    reading_start_offset: int | None = Field(default=None, ge=0)
    reading_end_offset: int | None = Field(default=None, ge=1)
    projection_status: Literal["exact", "partial", "unmapped"] | None = None
    projection_method: Literal["offset_map", "text_match"] | None = None
    provenance: PiiEntityProvenance | None = Field(
        default=None,
        description=(
            "Detection source/role and deterministic overlap-resolution outcome for this entity "
            "(ADR-0028). None on artifacts written before PII consumed the document text package."
        ),
    )

    @model_validator(mode="after")
    def _validate_offsets(self) -> PiiEntity:
        if self.end_offset <= self.start_offset:
            raise ValueError("entity end offset must be after start offset")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("entity offsets do not match entity text")
        page_fields = (
            self.page_number,
            self.page_start_offset,
            self.page_end_offset,
        )
        if any(value is None for value in page_fields) != all(
            value is None for value in page_fields
        ):
            raise ValueError("page mapping fields must be all set or all absent")
        if self.page_start_offset is not None and self.page_end_offset is not None:
            if self.page_end_offset <= self.page_start_offset:
                raise ValueError("page entity end offset must be after start offset")
            if self.page_end_offset - self.page_start_offset != len(self.text):
                raise ValueError("page entity offsets do not match entity text")
        has_projection_offsets = (
            self.reading_start_offset is not None or self.reading_end_offset is not None
        )
        if has_projection_offsets != (self.projection_status == "exact"):
            raise ValueError("only exact reading projections may carry offsets")
        if self.projection_status == "exact" and (
            self.reading_start_offset is None
            or self.reading_end_offset is None
            or self.reading_end_offset <= self.reading_start_offset
        ):
            raise ValueError("exact reading projection offsets must be non-empty and ordered")
        if self.projection_status != "exact" and self.projection_method is not None:
            raise ValueError("only exact reading projections may identify a projection method")
        return self


class PiiValidationSummary(BaseModel):
    """Aggregate Engine-5 candidate-validation counts. Counts and reason codes only — never a
    candidate's raw text, position, or context."""

    enabled: bool
    kept: int = Field(ge=0)
    dropped: int = Field(ge=0)
    score_down: int = Field(ge=0)
    dropped_by_reason: dict[str, int] = Field(default_factory=dict)
    score_down_by_reason: dict[str, int] = Field(default_factory=dict)


class PiiEngineSettings(BaseModel):
    """Effective non-sensitive settings used for one immutable PII run."""

    pii_profile: str
    candidate_validation_enabled: bool
    score_threshold: float = Field(ge=0, le=1)
    source: Literal["server-default", "dev-ui-override"]


class PiiContent(BaseModel):
    """Versioned detection-only output produced by the PII workstation."""

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    pii_version: Literal["1"] = "1"
    profile: str = "custom"
    language: str
    score_threshold: float = Field(ge=0, le=1)
    text_char_count: int = Field(ge=0)
    reading_text_char_count: int | None = Field(default=None, ge=0)
    configured_entity_types: list[str]
    entities: list[PiiEntity] = Field(default_factory=list)
    entity_counts: dict[str, int] = Field(default_factory=dict)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    validation: PiiValidationSummary | None = Field(
        default=None,
        description=(
            "Engine-5 candidate-validation summary. None on artifacts written before candidate "
            "validation existed."
        ),
    )
    engine_settings: PiiEngineSettings | None = Field(
        default=None,
        description=(
            "Effective, non-sensitive engine settings for this PII run. None on artifacts "
            "written before dev-mode run metadata existed."
        ),
    )
    input_contract: PiiInputContractSummary | None = Field(
        default=None,
        description=(
            "OCR Output Contract v1 package PII consumed for this run (ADR-0027/0028). None on "
            "artifacts written before PII consumed the document text package."
        ),
    )
    overlap_resolution: PiiOverlapResolutionSummary | None = Field(
        default=None,
        description=(
            "Deterministic overlap-resolution summary (PII L12). None on artifacts written before "
            "overlap resolution existed."
        ),
    )

    @model_validator(mode="after")
    def _validate_entity_summary(self) -> PiiContent:
        if len(self.configured_entity_types) != len(set(self.configured_entity_types)):
            raise ValueError("configured entity types must be unique")
        configured = set(self.configured_entity_types)
        if any(entity.entity_type not in configured for entity in self.entities):
            raise ValueError("entity type was not configured")
        if any(entity.end_offset > self.text_char_count for entity in self.entities):
            raise ValueError("entity offset exceeds source text")
        projected = [entity for entity in self.entities if entity.projection_status == "exact"]
        if projected and self.reading_text_char_count is None:
            raise ValueError("projected entities require a reading text character count")
        if self.reading_text_char_count is not None and any(
            entity.reading_end_offset is not None
            and entity.reading_end_offset > self.reading_text_char_count
            for entity in projected
        ):
            raise ValueError("projected entity offset exceeds reading text")
        sort_keys = [
            (
                entity.start_offset,
                entity.end_offset,
                entity.entity_type,
                entity.recognizer,
                entity.text,
                -entity.score,
            )
            for entity in self.entities
        ]
        if sort_keys != sorted(sort_keys):
            raise ValueError("entities must be deterministically sorted")
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
        if self.entity_counts != dict(sorted(counts.items())):
            raise ValueError("entity counts do not match entities")
        self._validate_engine_settings()
        return self

    def _validate_engine_settings(self) -> None:
        if self.engine_settings is None:
            return
        if self.engine_settings.pii_profile != self.profile:
            raise ValueError("engine settings profile does not match pii profile")
        if self.engine_settings.score_threshold != self.score_threshold:
            raise ValueError("engine settings threshold does not match score threshold")
        if (
            self.validation is not None
            and self.engine_settings.candidate_validation_enabled != self.validation.enabled
        ):
            raise ValueError("engine settings validation flag does not match validation")


class PiiArtifact(BaseModel):
    """Immutable JSON artifact emitted by the PII workstation."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_type: Literal["pii_result"] = "pii_result"
    station: Literal["pii"] = "pii"
    input_text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    media_type: Literal["application/json"] = "application/json"
    created_at: str
    content: PiiContent

    @model_validator(mode="after")
    def _validate_content_identity(self) -> PiiArtifact:
        if self.content.document_id != self.document_id:
            raise ValueError("PII content belongs to a different document")
        if self.content.input_text_artifact_id != self.input_text_artifact_id:
            raise ValueError("PII content references a different text artifact")
        return self


JobKindValue = Literal["ocr_text", "pii_detection"]
JobStatusValue = Literal["pending", "running", "succeeded", "failed", "canceled"]
JobExecutionModeValue = Literal["synchronous_inline", "future_worker"]


class JobStatusResponse(BaseModel):
    """Safe public status view for one OCR/PII job.

    The SQLite record stores metadata only: ids, lifecycle timestamps, sanitized error metadata, and
    a reference to the produced immutable artifact. It never returns raw document text, PII values,
    artifact payloads, or stack traces.
    """

    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: JobKindValue
    status: JobStatusValue
    execution_mode: JobExecutionModeValue
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
    attempt_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1000)
    result_artifact_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    result_artifact_type: str | None = Field(default=None, max_length=80)
    metadata: dict[str, str] = Field(default_factory=dict)


class PiiEntityGroupProjectionSummary(BaseModel):
    """Aggregate reading-text projection coverage across one entity group's occurrences."""

    exact_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    unmapped_count: int = Field(ge=0)


class PiiEntityGroup(BaseModel):
    """A conservative grouping of PII occurrences sharing one entity type and normalized value.

    Derived on demand from ``PiiContent.entities`` (see ``pii_grouping.py``) and never persisted
    inside the immutable ``pii_result`` artifact — detection is unchanged. ``entity_group_id`` is a
    deterministic hash of the entity type and normalized value, so it stays stable across repeated
    requests for the same PII artifact without ever storing the raw value itself.
    """

    entity_group_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    occurrence_ids: list[str] = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    normalized_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_summary: PiiEntityGroupProjectionSummary

    @model_validator(mode="after")
    def _validate_counts(self) -> PiiEntityGroup:
        if self.occurrence_count != len(self.occurrence_ids):
            raise ValueError("occurrence count does not match occurrence ids")
        if len(self.occurrence_ids) != len(set(self.occurrence_ids)):
            raise ValueError("occurrence ids must be unique")
        summary = self.projection_summary
        if (
            summary.exact_count + summary.partial_count + summary.unmapped_count
            != self.occurrence_count
        ):
            raise ValueError("projection summary does not cover every occurrence")
        return self


PiiReviewDecisionScope = Literal["entity_group", "occurrence"]
# A freshly detected entity is assumed "pseudonymize" by default — there is no separate "pending"
# state. A reviewer only has to act to opt an entity *out* of pseudonymization, either because it
# should be kept as-is ("keep") or because it is not PII at all ("false_positive").
PiiReviewDecisionValue = Literal["pseudonymize", "keep", "false_positive"]
PiiReviewDecisionSource = Literal["user", "default", "imported"]
PiiReviewStatus = Literal["accepted", "kept", "rejected"]


class PiiReviewDecisionRequest(BaseModel):
    """Request body to set a review decision for one entity group or occurrence."""

    target_type: PiiReviewDecisionScope
    target_id: str = Field(min_length=1, max_length=64)
    decision: PiiReviewDecisionValue
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def _normalize_note(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PiiReviewDecisionRecord(BaseModel):
    """One persisted review-decision line (append-only; the latest line per target wins on read).

    Mirrors the existing ``PiiFeedbackRecord`` append-only pattern, but this is the binding review
    overlay consumed by future pseudonymization — not the dev-only feedback side-channel. Bound to
    the PII artifact it was recorded against so a re-run (new artifact id) never silently reapplies
    a stale decision.
    """

    schema_version: Literal["1"] = "1"
    app_version: str
    recorded_at: str
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    target_type: PiiReviewDecisionScope
    target_id: str = Field(min_length=1, max_length=64)
    decision: PiiReviewDecisionValue
    note: str | None = Field(default=None, max_length=1000)
    source: PiiReviewDecisionSource = "user"


class PiiReviewDecisionAck(BaseModel):
    """Confirmation returned after a review decision is recorded."""

    recorded: bool
    target_type: PiiReviewDecisionScope
    target_id: str
    decision: PiiReviewDecisionValue
    review_status: PiiReviewStatus
    updated_at: str


class PiiReviewOccurrence(BaseModel):
    """One reviewable occurrence: the authoritative raw span plus its resolved review state.

    Derived at request time from ``PiiContent.entities`` and the persisted decision overlay; never
    mutates raw or projected offsets. ``occurrence_id`` is the referenced ``PiiEntity.id``.
    """

    occurrence_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    entity_group_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    raw_start: int = Field(ge=0)
    raw_end: int = Field(ge=1)
    score: float = Field(ge=0, le=1)
    recognizer: str
    projection_status: Literal["exact", "partial", "unmapped"] | None = None
    projection_method: Literal["offset_map", "text_match"] | None = None
    reading_start_offset: int | None = Field(default=None, ge=0)
    reading_end_offset: int | None = Field(default=None, ge=1)
    review_status: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    decision_scope: PiiReviewDecisionScope | None = Field(
        default=None,
        description=(
            "Which scope the effective decision came from; None while no explicit decision has "
            "been recorded yet (the implied default is 'pseudonymize')."
        ),
    )

    @model_validator(mode="after")
    def _validate_span(self) -> PiiReviewOccurrence:
        if self.raw_end <= self.raw_start:
            raise ValueError("occurrence end offset must be after start offset")
        return self


class PiiEntityGroupReview(PiiEntityGroup):
    """An entity group enriched with its resolved review decision."""

    review_status: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    updated_at: str | None = None


class PiiReviewResult(BaseModel):
    """The reviewable PII view for one document: groups and occurrences with resolved decisions.

    Computed on demand from the latest ``pii_result`` and the persisted decision overlay; the
    ``pii_result`` artifact and its entities/offsets are never mutated by review decisions.
    """

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    groups: list[PiiEntityGroupReview] = Field(default_factory=list)
    occurrences: list[PiiReviewOccurrence] = Field(default_factory=list)


# --- Review-ready PII entity contract v1 (ADR-0029) ----------------------------------------------
# A derived, additive, review-facing view over the immutable ``pii_result``. It connects every
# detected entity to the technical raw text and the canonical reading text with an explicit mapping
# status, a stable entity id, deterministic overlap provenance, and a text-free display model —
# without mutating the artifact or switching the active detection input. Raw text stays the primary
# detection source; canonical reading text is display/context/projection only. See
# docs/adr/0029-pii-review-ready-entity-contract.md.

# How well one entity's raw span connects to the canonical reading text. ``exact``/``projected`` are
# the two mapped states (offset map vs. value re-match); ``partial``/``missing``/``ambiguous`` keep
# the entity fully reviewable without a canonical span; ``not_applicable`` means the run had no
# canonical reading text at all (a degraded package), so no mapping was ever possible. A code is
# never removed or repurposed.
PiiEntityMappingStatus = Literal[
    "exact", "projected", "partial", "missing", "ambiguous", "not_applicable"
]
# Stable review reason codes surfaced on the review-ready entity. Mapping codes are derived here;
# overlap codes are lifted from the entity's overlap provenance (see ``pii_entity_contract.py``).
PiiEntityReviewReasonCode = Literal[
    "canonical_mapping_missing",
    "canonical_mapping_partial",
    "canonical_mapping_ambiguous",
    "conflicting_entity_type",
    "ambiguous_overlap_review_required",
    "exact_duplicate",
    "recognizer_duplicate",
    "same_type_overlap",
    "nested_entity",
    "merged_provenance",
    "stronger_candidate_selected",
]
PiiEntityPreferredTextSource = Literal["technical_raw_text", "canonical_reading_text"]


class PiiEntitySpan(BaseModel):
    """A half-open ``[start, end)`` character range into one text layer."""

    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_span(self) -> PiiEntitySpan:
        if self.end <= self.start:
            raise ValueError("span end offset must be after start offset")
        return self


class PiiEntitySourceSpan(PiiEntitySpan):
    """The entity's authoritative range in the technical raw text, with optional page anchoring."""

    page_number: int | None = Field(default=None, ge=1)
    page_start: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=1)


class PiiEntityDisplaySpan(PiiEntitySpan):
    """The entity's range in the canonical reading text, present only when a mapping exists."""

    projection_method: Literal["offset_map", "text_match"] | None = None


class PiiEntityDisplay(BaseModel):
    """Text-free display metadata so a reviewer can render one entity consistently.

    Ranges and codes only: no surrounding text snippet is ever copied here. The UI highlights the
    entity inside already-loaded raw/canonical text using these offsets, and ``display_label`` is
    the entity type (never the raw value).
    """

    preferred_text_source: PiiEntityPreferredTextSource
    raw_highlight_range: PiiEntitySpan
    canonical_highlight_range: PiiEntitySpan | None = None
    display_label: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    display_context_available: bool
    needs_review: bool
    review_reason_codes: list[PiiEntityReviewReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_review_flag(self) -> PiiEntityDisplay:
        if self.needs_review != bool(self.review_reason_codes):
            raise ValueError("needs_review must be set iff review reason codes are present")
        return self


class ReviewReadyPiiEntity(BaseModel):
    """One detected entity presented review-ready (ADR-0029).

    Carries a stable ``entity_id`` (same for the same document + raw span + type across re-runs),
    the authoritative raw span, the canonical reading span where a mapping exists, an explicit
    ``mapping_status``, deterministic overlap provenance, the resolved review state, and a text-free
    display model. Derived from ``pii_result`` and never persisted; the immutable artifact and its
    offsets are untouched. ``value`` mirrors ``PiiEntity.text`` (the same value already returned by
    ``GET …/pii``) and appears only here — never inside display metadata, warnings, or provenance.
    """

    entity_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_entity_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_group_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    value: str
    confidence: float = Field(ge=0, le=1)
    detection_source: PiiEntityDetectionSource = "raw_text"
    source_role: PiiInputSourceRole = "primary"
    page_number: int | None = Field(default=None, ge=1)
    raw_text_range: PiiEntitySourceSpan
    canonical_reading_text_range: PiiEntityDisplaySpan | None = None
    mapping_status: PiiEntityMappingStatus
    overlap_decision: PiiOverlapReason | None = None
    provenance: PiiEntityProvenance | None = None
    review_state: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    decision_scope: PiiReviewDecisionScope | None = None
    display: PiiEntityDisplay
    warnings: list[PiiEntityReviewReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_entity(self) -> ReviewReadyPiiEntity:
        if self.raw_text_range.end - self.raw_text_range.start != len(self.value):
            raise ValueError("raw text range length must match value length")
        has_canonical = self.canonical_reading_text_range is not None
        if has_canonical != (self.mapping_status in ("exact", "projected")):
            raise ValueError("canonical range present iff mapping status is exact or projected")
        if self.display.raw_highlight_range != PiiEntitySpan(
            start=self.raw_text_range.start, end=self.raw_text_range.end
        ):
            raise ValueError("display raw highlight range must match the raw text range")
        if self.display.display_label != self.entity_type:
            raise ValueError("display label must be the entity type")
        return self


class PiiEntityMappingSummary(BaseModel):
    """Per-run counts of entities by canonical mapping status. Counts only, never entity text."""

    exact: int = Field(default=0, ge=0)
    projected: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    ambiguous: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)


class PiiEntityContractV1(BaseModel):
    """Review-ready PII entity contract for one document's latest ``pii_result`` (ADR-0029).

    A pure, derived, additive view: it never mutates the artifact and adds no detection. Existing
    ``GET …/pii`` and ``GET …/pii/review`` responses are unchanged; this is a separate additive
    surface built entirely by the backend, so the frontend never has to call the text-package
    endpoint itself.
    """

    contract_version: Literal["1.0"] = "1.0"
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    pii_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    reading_text_available: bool
    input_contract: PiiInputContractSummary | None = None
    overlap_resolution: PiiOverlapResolutionSummary | None = None
    entities: list[ReviewReadyPiiEntity] = Field(default_factory=list)
    mapping_summary: PiiEntityMappingSummary
    needs_review_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_contract(self) -> PiiEntityContractV1:
        order_keys = [
            (entity.raw_text_range.start, entity.raw_text_range.end, entity.entity_type)
            for entity in self.entities
        ]
        if order_keys != sorted(order_keys):
            raise ValueError("entities must be deterministically ordered by raw span then type")
        entity_ids = [entity.entity_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity ids must be unique within a contract")
        expected = PiiEntityMappingSummary(
            exact=sum(e.mapping_status == "exact" for e in self.entities),
            projected=sum(e.mapping_status == "projected" for e in self.entities),
            partial=sum(e.mapping_status == "partial" for e in self.entities),
            missing=sum(e.mapping_status == "missing" for e in self.entities),
            ambiguous=sum(e.mapping_status == "ambiguous" for e in self.entities),
            not_applicable=sum(e.mapping_status == "not_applicable" for e in self.entities),
        )
        if self.mapping_summary != expected:
            raise ValueError("mapping summary does not match entities")
        if self.needs_review_count != sum(e.display.needs_review for e in self.entities):
            raise ValueError("needs_review_count does not match entities")
        return self


class UploadAccepted(BaseModel):
    """Returned when an upload passes validation and is stored."""

    id: str = Field(description="Server-generated identifier for the stored document.")
    filename: str = Field(description="Sanitized original filename (metadata only).")
    size: int = Field(description="Stored size in bytes.", ge=0)
    status: str = Field(default="received", description="Processing status.")
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Lowercase SHA-256 digest of the stored original.",
    )
    detected_mime_type: str = Field(description="MIME type verified from file content.")
    original_artifact: OriginalArtifact = Field(description="Stored original artifact.")


class PiiConfigResponse(BaseModel):
    """Read-only frontend view of the safe PII defaults and the selectable profile set."""

    default_profile: str
    available_profiles: list[str]
    candidate_validation_enabled: bool
    score_threshold: float = Field(ge=0, le=1)


class RuntimeCapabilitiesResponse(BaseModel):
    """Whether the optional OCR/PII runtimes are actually installed and usable on this server.

    A read-only signal only — it never gates a request. It lets the frontend distinguish "this
    station's runtime isn't installed on this deployment" from a real per-document station error.
    """

    ocr_available: bool = Field(
        description="PaddleOCR/PaddlePaddle are installed and the local models are provisioned."
    )
    pii_available: bool = Field(
        description="Presidio, spaCy, and the configured spaCy model package are installed."
    )
    ocr_memory_limit_low: bool = Field(
        description=(
            "OCR is installed but the container memory limit looks too low for PaddleOCR to run "
            "without being OOM-killed mid-request in sync fallback mode. Use default worker mode "
            "or set API_MEMORY_LIMIT=2g when OCR_EXECUTION_MODE=sync."
        )
    )


class ConfigResponse(BaseModel):
    """Public app configuration, so the frontend can mirror backend-owned defaults safely."""

    max_upload_bytes: int = Field(description="Maximum accepted upload size in bytes.", ge=0)
    allowed_extensions: list[str] = Field(description="Allowed file extensions (lowercase).")
    dev_engine_settings_enabled: bool = Field(
        description="Whether per-run dev-only engine setting overrides are enabled."
    )
    pii: PiiConfigResponse = Field(
        description="Effective backend defaults and available named PII profiles."
    )
    runtime: RuntimeCapabilitiesResponse = Field(
        description="Whether the optional OCR/PII runtimes are installed on this server."
    )


class PiiRunRequest(BaseModel):
    """Optional per-run dev overrides for the PII station."""

    pii_profile: PiiProfileName | None = None

    @field_validator("pii_profile", mode="before")
    @classmethod
    def _normalize_pii_profile(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def has_overrides(self) -> bool:
        """True when the request asked to override at least one backend default."""
        return self.pii_profile is not None


# Verdict is the coarse outcome; issue_type refines it. "correct" is the only issue_type allowed
# for a "positive" verdict; every other value marks a concrete problem class for later analysis.
PiiFeedbackVerdict = Literal["positive", "issue"]
PiiFeedbackIssueType = Literal[
    "correct",
    "false_positive",
    "wrong_type",
    "span_too_long_left",
    "span_too_long_right",
    "span_too_short_left",
    "span_too_short_right",
    "duplicate_or_should_merge",
    "overlap_conflict",
    "missing_related_entity",
    "other",
]


class PiiFeedbackEntityRef(BaseModel):
    """The minimal, non-sensitive fingerprint of the entity a reviewer commented on.

    Offsets + type + recognizer identify an entity in the referenced PII artifact. Raw entity text
    is never accepted or stored here; ``text_hash`` is optional and must be a lowercase SHA-256
    digest so it cannot be used as a free-text field.
    """

    type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    recognizer: str = Field(max_length=200)
    text_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_span(self) -> PiiFeedbackEntityRef:
        if self.end <= self.start:
            raise ValueError("end offset must be greater than start offset")
        return self


class PiiFeedbackDetail(BaseModel):
    """The reviewer's verdict on one entity.

    ``comment`` is an optional short review note. Reviewers must not paste document text, OCR text,
    or raw PII into it.
    """

    verdict: PiiFeedbackVerdict
    issue_type: PiiFeedbackIssueType
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment", mode="before")
    @classmethod
    def _normalize_comment(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _validate_verdict_issue_pairing(self) -> PiiFeedbackDetail:
        if self.verdict == "positive" and self.issue_type != "correct":
            raise ValueError("a positive verdict must use issue_type 'correct'")
        if self.verdict == "issue" and self.issue_type == "correct":
            raise ValueError("an issue verdict must not use issue_type 'correct'")
        return self


class PiiFeedbackRequest(BaseModel):
    """Dev-only review feedback for one detected PII entity (POST body)."""

    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity: PiiFeedbackEntityRef
    feedback: PiiFeedbackDetail


class PiiFeedbackRecord(BaseModel):
    """One append-only feedback line persisted without raw entity or document text."""

    schema_version: Literal["1"] = "1"
    app_version: str
    recorded_at: str
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity: PiiFeedbackEntityRef
    feedback: PiiFeedbackDetail
    # Authoritative settings copied from the referenced PII artifact; None on legacy artifacts
    # written before per-run engine settings existed. ``engine_settings_origin`` records which.
    engine_settings: PiiEngineSettings | None = None
    engine_settings_origin: Literal["artifact", "unknown"] = "unknown"


class PiiFeedbackAck(BaseModel):
    """Small confirmation returned after a feedback line is appended."""

    recorded: bool
    schema_version: str
    recorded_at: str


class PiiFeedbackSummaryItem(BaseModel):
    """The latest verdict for one entity fingerprint within one artifact.

    Carries only the non-sensitive key (type + offsets + recognizer) and the verdict — never the
    reviewer's free-text comment or any raw value — so the UI can restore per-entity state.
    """

    type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    recognizer: str
    verdict: PiiFeedbackVerdict
    issue_type: PiiFeedbackIssueType
    recorded_at: str


class PiiFeedbackSummary(BaseModel):
    """The last-known feedback per entity for one PII artifact (append-only history collapsed)."""

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    items: list[PiiFeedbackSummaryItem] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    """Public representation of an uploaded document, as returned by the documents API."""

    id: str = Field(description="Server-generated identifier for the stored document.")
    filename: str = Field(description="Sanitized original filename.")
    size: int = Field(description="Stored size in bytes.", ge=0)
    content_type: str | None = Field(default=None, description="MIME type, if known.")
    uploaded_at: str = Field(description="Upload timestamp, UTC ISO 8601.")
    status: str = Field(default="received", description="Processing status.")
    sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 digest of the stored original; absent on legacy records.",
    )
    detected_mime_type: str | None = Field(
        default=None,
        description="Server-verified MIME type; absent on legacy records.",
    )
    original_artifact: OriginalArtifact | None = Field(
        default=None,
        description="Stored original artifact; absent on legacy records.",
    )


class ErrorResponse(BaseModel):
    """Uniform error body. Never contains stack traces or internal details."""

    detail: str = Field(description="Human-readable, safe error message.")
    correlation_id: str | None = Field(
        default=None,
        description="Correlation id to quote in support requests.",
    )


class HealthStatus(BaseModel):
    """Health check response."""

    status: str = Field(description="'ok' when healthy.")
