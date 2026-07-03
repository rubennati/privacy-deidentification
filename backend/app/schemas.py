"""Pydantic response models for the API (the trust-boundary contract)."""

from __future__ import annotations

from typing import Literal

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

    @model_validator(mode="after")
    def _validate_entity_summary(self) -> PiiContent:
        if len(self.configured_entity_types) != len(set(self.configured_entity_types)):
            raise ValueError("configured entity types must be unique")
        configured = set(self.configured_entity_types)
        if any(entity.entity_type not in configured for entity in self.entities):
            raise ValueError("entity type was not configured")
        if any(entity.end_offset > self.text_char_count for entity in self.entities):
            raise ValueError("entity offset exceeds source text")
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
