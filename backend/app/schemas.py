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


# --- Geometry-backed reading projection (post-render; NOT construction-time lineage) --------------
# Canonical Reading Text is already fully built by the time this layer runs. It re-derives
# canonical<->raw correspondence by projecting known raw geometry-line offsets onto the *finished*
# canonical string via exact, boundary-respecting line matching — it does not receive lineage from
# the reading-text builder itself (see ``reading_text_geometry_projection.py``). It is a stronger,
# more structured post-hoc mechanism than the pre-existing unique-token ``reading_text_map``
# (full-line granularity, geometry-anchored raw offsets) — but it is not authoritative construction
# identity. Genuine builder-emitted construction-time lineage exists as
# ``ReadingTextRowLineageMap`` below and is preferred over both post-hoc mechanisms; this
# projection remains an explicit fallback for exactly the spans construction declines.
#
# A full source line whose exact text is not globally unique among the collected source lines, or
# whose exact text does not occur exactly once (line-bounded) in the canonical text, can never be
# resolved by this mechanism: cursor/processing order alone is not proof of identity, so such a line
# is marked ``ambiguous`` and declines to claim any specific canonical occurrence, rather than
# picking one by encounter order. Like every lineage layer it is text-free: offsets, ids, roles,
# statuses, reason codes, and counts only — never copied source text.
CanonicalTextMappingStatus = Literal[
    "exact",
    "normalized",
    "projected",
    "split",
    "merged",
    "derived",
    "inserted",
    "omitted",
    "ambiguous",
    "missing",
]
CanonicalTextSegmentRole = Literal[
    "paragraph",
    "heading",
    "table_cell",
    "label",
    "value",
    "list_item",
    "footer",
    "header",
    "body",
    "derived",
]
CanonicalTextLineageSource = Literal[
    "row_construction", "geometry_projection", "fallback_text_match", "unavailable"
]


class CanonicalTextSourceRange(BaseModel):
    """A half-open technical-raw range a canonical segment was constructed from (offset-only)."""

    source_name: Literal["technical_raw_text"] = "technical_raw_text"
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    source_role: CanonicalTextSegmentRole = "body"

    @model_validator(mode="after")
    def _validate_range(self) -> CanonicalTextSourceRange:
        if self.end <= self.start:
            raise ValueError("canonical source range must be non-empty and ordered")
        return self


class CanonicalTextSegmentV1(BaseModel):
    """One canonical reading-text span with a raw correspondence claim (post-render projection).

    ``source_range`` is present for a segment the projector could attribute to a specific,
    unambiguous raw span (``exact``/``normalized``/``projected``/``split``/``merged``); it is
    ``None`` for a segment with no raw correspondence at all (``inserted``/``derived``) *or* for a
    genuinely ambiguous segment (``ambiguous``) where a raw correspondence exists but cannot be
    uniquely resolved — the projector never guesses which candidate raw line an ambiguous segment
    belongs to. The segment carries no text — the canonical/raw text stays exclusively in the
    text-bearing layers.
    """

    segment_id: str = Field(pattern=r"^[0-9a-f]{16,64}$")
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(ge=1)
    source_range: CanonicalTextSourceRange | None = None
    segment_role: CanonicalTextSegmentRole = "body"
    mapping_status: CanonicalTextMappingStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    page_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_segment(self) -> CanonicalTextSegmentV1:
        if self.canonical_end <= self.canonical_start:
            raise ValueError("canonical segment range must be non-empty and ordered")
        attributed = self.mapping_status in (
            "exact",
            "normalized",
            "projected",
            "split",
            "merged",
        )
        if attributed and self.source_range is None:
            raise ValueError("an attributed canonical segment requires a source range")
        if self.mapping_status in ("inserted", "derived") and self.source_range is not None:
            raise ValueError("an inserted/derived canonical segment must not carry a source range")
        return self


class ReadingTextGeometryProjectionSummary(BaseModel):
    """Text-free coverage summary for a :class:`ReadingTextGeometryProjectionMap`."""

    lineage_source: CanonicalTextLineageSource = "geometry_projection"
    total_segments: int = Field(default=0, ge=0)
    mapped_segments: int = Field(default=0, ge=0)
    ambiguous_segments: int = Field(default=0, ge=0)
    inserted_segments: int = Field(default=0, ge=0)
    canonical_char_count: int = Field(default=0, ge=0)
    mapped_canonical_char_count: int = Field(default=0, ge=0)
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)


class ReadingTextGeometryProjectionMap(BaseModel):
    """Geometry-backed, post-render canonical<->raw projection (NOT construction-time lineage).

    Built *after* Canonical Reading Text already exists, by projecting known raw geometry-line
    offsets onto the finished canonical string via exact, boundary-respecting line matching.
    Segments are ordered by canonical offset and never overlap in canonical text; a segment's raw
    source range (when present) may be reordered relative to canonical order (reading order differs
    from raw order) but raw ranges never overlap each other. A line whose exact text is not globally
    unique among the collected source lines, or that does not occur exactly once (line-bounded) in
    the canonical text, is marked ``ambiguous`` with no source range — this mechanism never picks an
    occurrence by processing/cursor order alone. Preferred over the post-hoc unique-token
    ``reading_text_map`` when it can resolve a line unambiguously; genuine builder-emitted
    construction-time lineage is a separate, unimplemented future step.
    """

    map_version: Literal["1"] = "1"
    lineage_source: Literal["geometry_projection"] = "geometry_projection"
    segments: list[CanonicalTextSegmentV1] = Field(default_factory=list)
    summary: ReadingTextGeometryProjectionSummary

    @model_validator(mode="after")
    def _validate_map(self) -> ReadingTextGeometryProjectionMap:
        previous_canonical_end = 0
        raw_ranges: list[tuple[int, int]] = []
        for segment in self.segments:
            if segment.canonical_start < previous_canonical_end:
                raise ValueError("projection segments must be ordered and non-overlapping")
            previous_canonical_end = segment.canonical_end
            if segment.source_range is not None:
                start, end = segment.source_range.start, segment.source_range.end
                if any(
                    start < other_end and other_start < end
                    for other_start, other_end in raw_ranges
                ):
                    raise ValueError("projection source ranges must not overlap")
                raw_ranges.append((start, end))
        return self


class ReadingTextRowLineageSummary(BaseModel):
    """Text-free coverage summary for a :class:`ReadingTextRowLineageMap`."""

    lineage_source: CanonicalTextLineageSource = "row_construction"
    total_segments: int = Field(default=0, ge=0)
    canonical_char_count: int = Field(default=0, ge=0)
    mapped_canonical_char_count: int = Field(default=0, ge=0)
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    # Additive per-status counts (map_version "2"); legacy "1" maps omit them and default to 0.
    exact_segment_count: int = Field(default=0, ge=0)
    normalized_segment_count: int = Field(default=0, ge=0)
    merged_segment_count: int = Field(default=0, ge=0)
    split_segment_count: int = Field(default=0, ge=0)
    inserted_segment_count: int = Field(default=0, ge=0)


class ReadingTextRowLineageMap(BaseModel):
    """Builder-emitted, construction-time lineage (not a post-render search).

    Unlike :class:`ReadingTextGeometryProjectionMap` and the legacy ``reading_text_map``, a segment
    here is never derived by scanning the finished canonical string for a match: its raw range was
    already known and attached to the contributing ``ReadingRow``/``ReadingCell`` at collection
    time, before its line was ever rendered, and its canonical range is computed purely by walking
    the same block/line join arithmetic the text was assembled with. This is the authoritative
    canonical<->raw identity layer; the geometry projection and ``reading_text_map`` are post-hoc
    fallbacks for the spans this map does not cover.

    A segment's ``mapping_status`` is one of ``"exact"`` (the rendered span is byte-identical to
    its raw span — verified by direct comparison at construction), ``"normalized"`` (one whole
    row, but rendering changed its bytes — e.g. a reformatted table row or whitespace collapsing),
    ``"split"`` (map_version "2": the span was constructed from a *subset* of one row's cells — an
    in-row label/value split, a party-column cell, a redistributed multi-column cell run — and is
    not byte-identical to that subset's raw span), ``"merged"`` (a wrap continuation or adjacent
    label/value pairing unioned *more than one* row's own ranges), or ``"inserted"`` (a synthetic
    heading this builder itself inserted — e.g. ``ANGEBOT``/``LEISTUNGEN``/``SUMMEN`` — carrying no
    source range because none exists). There is still no ``ambiguous`` state here: a rendering
    path that cannot attribute without guessing simply contributes no segment (a canonical gap)
    rather than a weaker claim.

    Coverage may still be partial: fused table headers, layout-block ordering, spans dropped by
    the document-level overlap sweep, and margin-filtered/whole-document-fallback renderings
    contribute no segment, and downstream consumers should keep falling back to
    :class:`ReadingTextGeometryProjectionMap`/``reading_text_map`` for exactly those spans.
    """

    map_version: Literal["1", "2"] = "2"
    lineage_source: Literal["row_construction"] = "row_construction"
    segments: list[CanonicalTextSegmentV1] = Field(default_factory=list)
    summary: ReadingTextRowLineageSummary

    @model_validator(mode="after")
    def _validate_map(self) -> ReadingTextRowLineageMap:
        previous_canonical_end = 0
        raw_ranges: list[tuple[int, int]] = []
        for segment in self.segments:
            if segment.mapping_status not in (
                "exact",
                "normalized",
                "merged",
                "split",
                "inserted",
            ):
                raise ValueError(
                    "row lineage segments must be exact, normalized, merged, split, or inserted"
                )
            if segment.mapping_status == "inserted":
                if segment.source_range is not None:
                    raise ValueError(
                        "an inserted row lineage segment must not carry a source range"
                    )
            elif segment.source_range is None:
                raise ValueError("an attributed row lineage segment requires a source range")
            if segment.canonical_start < previous_canonical_end:
                raise ValueError("row lineage segments must be ordered and non-overlapping")
            previous_canonical_end = segment.canonical_end
            if segment.source_range is not None:
                start, end = segment.source_range.start, segment.source_range.end
                if any(
                    start < other_end and other_start < end
                    for other_start, other_end in raw_ranges
                ):
                    raise ValueError("row lineage source ranges must not overlap")
                raw_ranges.append((start, end))
        return self


class DocumentTextPackageLineageSummary(BaseModel):
    """Compact, text-free summary of which mechanism connects raw↔canonical for a package.

    ``lineage_source`` names the preferred available mechanism, in preference order:
    ``row_construction`` (builder-emitted, construction-time lineage — the authoritative identity
    source), ``geometry_projection`` (a geometry-backed, post-render exact-line projection — an
    explicit post-hoc fallback, not construction identity), ``fallback_text_match`` (the post-hoc
    unique-token ``reading_text_map`` only — the weakest fallback), or ``unavailable`` (no
    canonical text / no lineage at all). ``row_construction`` being preferred does not guarantee it
    covers every span — a consumer that needs full coverage should still consult
    ``geometry_projection``/``reading_text_map`` for exactly the spans it leaves unattributed, and
    anything resolved that way is degraded, fallback identity, per-anchor flagged as such.
    """

    canonical_available: bool = False
    row_construction_available: bool = False
    geometry_projection_available: bool = False
    reading_text_map_available: bool = False
    lineage_source: CanonicalTextLineageSource = "unavailable"
    row_construction_segment_count: int = Field(default=0, ge=0)
    row_construction_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    geometry_projection_segment_count: int = Field(default=0, ge=0)
    geometry_projection_ambiguous_count: int = Field(default=0, ge=0)
    reading_text_map_segment_count: int = Field(default=0, ge=0)
    geometry_projection_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


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
    # Additive geometry-backed reading projection (post-render; NOT construction-time lineage).
    # Built after ``reading_text`` already exists, by projecting known raw geometry-line offsets
    # onto the finished canonical string via exact, boundary-respecting line matching; ambiguous
    # (non-unique) lines decline rather than guess. Preferred over the post-hoc unique-token
    # ``reading_text_map`` by downstream anchor projection when it can resolve a line unambiguously.
    # Genuine builder-emitted construction-time lineage (`anchor-first-text-package-v2`) remains
    # open.
    # Optional/defaulted so artifacts written before this layer remain valid.
    reading_text_geometry_projection_map_version: Literal["1"] | None = None
    reading_text_geometry_projection_map: ReadingTextGeometryProjectionMap | None = None
    # Additive, builder-emitted construction-time lineage. Unlike the geometry projection above,
    # segments here are never derived by searching the finished ``reading_text`` string: each one
    # traces back to a raw offset range already known on the contributing row/cell before its line
    # was rendered. Version "1" covered row granularity on a subset of rendering paths; version "2"
    # adds cell-level identity (in-row splits, party-column cells, multi-column cell runs), the
    # byte-verified ``split`` status, and raw-order fallback line coverage. This is the preferred
    # canonical<->raw identity source; the geometry projection/``reading_text_map`` remain explicit
    # post-hoc fallbacks for exactly the spans it leaves unattributed.
    # Optional/defaulted so artifacts written before this layer remain valid.
    reading_text_row_lineage_map_version: Literal["1", "2"] | None = None
    reading_text_row_lineage_map: ReadingTextRowLineageMap | None = None
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
    def _validate_reading_text_geometry_projection_map(self) -> TextContent:
        projection_map = self.reading_text_geometry_projection_map
        if (projection_map is not None) != (
            self.reading_text_geometry_projection_map_version == "1"
        ):
            raise ValueError(
                "reading text geometry projection map and version must be present together"
            )
        if projection_map is None:
            return self
        if self.reading_text is None:
            raise ValueError("reading text geometry projection map requires reading text")
        reading_length = len(self.reading_text)
        raw_length = len(self.text)
        for segment in projection_map.segments:
            if segment.canonical_end > reading_length:
                raise ValueError("projection map canonical offsets exceed reading text length")
            if segment.source_range is not None and segment.source_range.end > raw_length:
                raise ValueError("projection map source offsets exceed technical raw text length")
        return self

    @model_validator(mode="after")
    def _validate_reading_text_row_lineage_map(self) -> TextContent:
        row_lineage_map = self.reading_text_row_lineage_map
        if (row_lineage_map is not None) != (
            self.reading_text_row_lineage_map_version in ("1", "2")
        ):
            raise ValueError("reading text row lineage map and version must be present together")
        if row_lineage_map is not None and (
            row_lineage_map.map_version != self.reading_text_row_lineage_map_version
        ):
            raise ValueError("reading text row lineage map version fields must agree")
        if row_lineage_map is None:
            return self
        if self.reading_text is None:
            raise ValueError("reading text row lineage map requires reading text")
        reading_length = len(self.reading_text)
        raw_length = len(self.text)
        for segment in row_lineage_map.segments:
            if segment.canonical_end > reading_length:
                raise ValueError("row lineage canonical offsets exceed reading text length")
            if segment.source_range is not None and segment.source_range.end > raw_length:
                raise ValueError("row lineage source offsets exceed technical raw text length")
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
    # Geometry-backed reading projection (post-render; NOT construction-time lineage), preferred
    # over ``reading_text_map`` by the Text Anchor Graph when it can resolve a line unambiguously;
    # ``None`` for legacy/minimal artifacts.
    reading_text_geometry_projection_map: ReadingTextGeometryProjectionMap | None = None
    # Sparse, builder-emitted construction-time row lineage, preferred over the geometry projection
    # above by the Text Anchor Graph when it covers a token; ``None`` for legacy/minimal artifacts
    # or when no plain-paragraph row could be attributed.
    reading_text_row_lineage_map: ReadingTextRowLineageMap | None = None
    lineage_summary: DocumentTextPackageLineageSummary | None = None
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


# Text Anchor Graph v1 (ADR-0031 Phase B). This is an OCR/Text-owned, derived identity layer built
# from DocumentTextPackageV1. It connects the existing text views by ids, offsets, statuses, and
# reason codes only; it never duplicates private source text outside the text-bearing package
# layers.
DocumentTextAnchorSourceName = Literal[
    "technical_raw_text",
    "canonical_reading_text",
    "layout_text",
]
DocumentTextAnchorStatus = Literal[
    "exact",
    "projected",
    "normalized",
    "split",
    "merged",
    "partial",
    "missing",
    "ambiguous",
    "derived",
    "omitted",
    "inserted",
    "single_source",
]
DocumentTextAnchorKind = Literal[
    "word",
    "number",
    "email",
    "phone",
    "identifier",
    "symbol",
]
DocumentTextAnchorRangeRole = Literal[
    "primary",
    "projected",
    "derived",
    "approximate",
]
DocumentTextAnchorValidationStatus = Literal["valid", "degraded", "invalid"]
DocumentTextAnchorWarning = Literal[
    "missing_raw_text",
    "missing_canonical_reading_text",
    "missing_layout_text",
    "missing_reading_text_map",
    "partial_lineage",
    "ambiguous_repeated_token",
    "unmapped_raw_tokens",
    "unmapped_canonical_tokens",
    "invalid_range",
    "overlapping_anchor_ranges",
    "unsupported_source",
]


class DocumentTextAnchorSource(BaseModel):
    """A text view participating in the anchor graph, without carrying the view text itself."""

    source_name: DocumentTextAnchorSourceName
    available: bool
    text_char_count: int | None = Field(default=None, ge=0)
    range_count: int = Field(default=0, ge=0)
    mapped_anchor_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_source(self) -> DocumentTextAnchorSource:
        if self.available and self.text_char_count is None:
            raise ValueError("available anchor sources require a text char count")
        return self


class DocumentTextAnchorRange(BaseModel):
    """One half-open range for an anchor in a named text view.

    Ranges are offsets only. The source text remains exclusively in the text source layer/package.
    """

    source_name: DocumentTextAnchorSourceName
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    range_role: DocumentTextAnchorRangeRole
    mapping_status: DocumentTextAnchorStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_range(self) -> DocumentTextAnchorRange:
        if self.end <= self.start:
            raise ValueError("anchor ranges must be non-empty and ordered")
        return self


class DocumentTextAnchorV1(BaseModel):
    """Stable identity for one document information unit across available text views.

    ``anchor_id`` is deterministic and range-based; token text is intentionally absent. Repeated
    identical values remain distinct anchors unless a later derived grouping layer explicitly links
    them.
    """

    anchor_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    anchor_kind: DocumentTextAnchorKind
    anchor_status: DocumentTextAnchorStatus
    source_ranges: list[DocumentTextAnchorRange] = Field(default_factory=list)
    page_number: int | None = Field(default=None, ge=1)
    block_id: str | None = None
    line_id: str | None = None
    cell_id: str | None = None
    normalized_shape: str | None = None
    token_class: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)
    warnings: list[DocumentTextAnchorWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_anchor(self) -> DocumentTextAnchorV1:
        if not self.source_ranges:
            raise ValueError("text anchors require at least one source range")
        range_keys = [
            (source_range.source_name, source_range.start, source_range.end)
            for source_range in self.source_ranges
        ]
        if len(range_keys) != len(set(range_keys)):
            raise ValueError("anchor source ranges must be unique")
        if self.anchor_status == "single_source" and len(
            {source_range.source_name for source_range in self.source_ranges}
        ) != 1:
            raise ValueError("single_source anchors must reference exactly one source")
        return self


class DocumentTextAnchorGraphSummary(BaseModel):
    """Counts and coverage ratios for the anchor graph. Counts only, never source text."""

    total_anchors: int = Field(ge=0)
    anchors_with_raw_range: int = Field(ge=0)
    anchors_with_canonical_range: int = Field(ge=0)
    anchors_with_layout_range: int = Field(ge=0)
    raw_anchor_count: int = Field(default=0, ge=0)
    canonical_anchor_count: int = Field(default=0, ge=0)
    layout_anchor_count: int = Field(default=0, ge=0)
    anchors_with_raw_and_canonical: int = Field(default=0, ge=0)
    anchors_with_raw_only: int = Field(default=0, ge=0)
    anchors_with_canonical_only: int = Field(default=0, ge=0)
    anchors_with_layout: int = Field(default=0, ge=0)
    exact_count: int = Field(ge=0)
    projected_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    single_source_count: int = Field(ge=0)
    ambiguous_anchor_count: int = Field(default=0, ge=0)
    single_source_anchor_count: int = Field(default=0, ge=0)
    unmapped_raw_token_count: int = Field(ge=0)
    unmapped_canonical_token_count: int = Field(ge=0)
    canonical_unmapped_count: int = Field(default=0, ge=0)
    layout_unmapped_count: int = Field(default=0, ge=0)
    repeated_token_ambiguity_count: int = Field(ge=0)
    evidence_only_possible_count: int = Field(default=0, ge=0)
    # Which mechanism attached each raw anchor's canonical range, in preference order:
    # builder-emitted row construction lineage (real construction-time identity, but sparse), the
    # geometry-backed post-render exact-line projection (fuller coverage but not
    # construction-time/builder-emitted), or the post-hoc unique-token reading_text_map fallback.
    canonical_row_construction_count: int = Field(default=0, ge=0)
    canonical_geometry_projection_count: int = Field(default=0, ge=0)
    canonical_fallback_count: int = Field(default=0, ge=0)
    raw_to_canonical_coverage_ratio: float = Field(ge=0.0, le=1.0)
    raw_to_layout_coverage_ratio: float = Field(ge=0.0, le=1.0)


class DocumentTextAnchorGraphValidation(BaseModel):
    """Validation rollup for Text Anchor Graph v1."""

    status: DocumentTextAnchorValidationStatus
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    invalid_range_count: int = Field(ge=0)
    overlapping_anchor_range_count: int = Field(ge=0)
    warnings: list[DocumentTextAnchorWarning] = Field(default_factory=list)
    blockers: list[DocumentTextAnchorWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_status(self) -> DocumentTextAnchorGraphValidation:
        if self.warning_count != len(self.warnings):
            raise ValueError("anchor validation warning count does not match warnings")
        if self.blocker_count != len(self.blockers):
            raise ValueError("anchor validation blocker count does not match blockers")
        if self.status == "invalid" and not self.blockers:
            raise ValueError("invalid anchor graph status requires at least one blocker")
        if self.status != "invalid" and self.blockers:
            raise ValueError("anchor graph blockers are only present when invalid")
        if self.status == "degraded" and not self.warnings:
            raise ValueError("degraded anchor graph status requires at least one warning")
        if self.status == "valid" and self.warnings:
            raise ValueError("valid anchor graph status must not carry warnings")
        return self


class DocumentTextAnchorGraphV1(BaseModel):
    """OCR/Text-owned Text Anchor Graph v1 (ADR-0031 Phase B).

    Derived from one :class:`DocumentTextPackageV1` and exposed as a read-only API view. The graph
    carries source ids, offsets, counts, token classes/shapes, statuses, and warning codes only. It
    intentionally does not embed source text, PII values, snippets, filenames, or OCR line text.
    """

    graph_version: Literal["1.0"] = "1.0"
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_contract_version: str
    created_at: str
    sources: list[DocumentTextAnchorSource]
    anchors: list[DocumentTextAnchorV1] = Field(default_factory=list)
    summary: DocumentTextAnchorGraphSummary
    validation: DocumentTextAnchorGraphValidation
    # Which raw↔canonical lineage mechanism this graph consumed (construction vs. fallback map vs.
    # unavailable); mirrors the source package's lineage summary. ``None`` for legacy graphs.
    lineage_summary: DocumentTextPackageLineageSummary | None = None
    warnings: list[DocumentTextAnchorWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> DocumentTextAnchorGraphV1:
        source_names = [source.source_name for source in self.sources]
        expected_sources = ["technical_raw_text", "canonical_reading_text", "layout_text"]
        if source_names != expected_sources:
            raise ValueError("anchor graph sources must be emitted in the v1 source order")
        source_lengths = {
            source.source_name: source.text_char_count
            for source in self.sources
            if source.text_char_count is not None
        }
        for anchor in self.anchors:
            for source_range in anchor.source_ranges:
                length = source_lengths.get(source_range.source_name)
                if length is not None and source_range.end > length:
                    raise ValueError("anchor range exceeds source length")
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("anchor ids must be unique within a graph")
        if self.warnings != self.validation.warnings:
            raise ValueError("graph warnings must mirror validation warnings")
        raw_count = sum(
            _anchor_has_source(anchor, "technical_raw_text") for anchor in self.anchors
        )
        canonical_count = sum(
            _anchor_has_source(anchor, "canonical_reading_text") for anchor in self.anchors
        )
        layout_count = sum(_anchor_has_source(anchor, "layout_text") for anchor in self.anchors)
        raw_and_canonical = sum(
            _anchor_has_source(anchor, "technical_raw_text")
            and _anchor_has_source(anchor, "canonical_reading_text")
            for anchor in self.anchors
        )
        raw_only = sum(
            _anchor_has_source(anchor, "technical_raw_text")
            and not _anchor_has_source(anchor, "canonical_reading_text")
            and not _anchor_has_source(anchor, "layout_text")
            for anchor in self.anchors
        )
        canonical_only = sum(
            _anchor_has_source(anchor, "canonical_reading_text")
            and not _anchor_has_source(anchor, "technical_raw_text")
            for anchor in self.anchors
        )
        anchors_without_raw = sum(
            not _anchor_has_source(anchor, "technical_raw_text") for anchor in self.anchors
        )
        expected = DocumentTextAnchorGraphSummary(
            total_anchors=len(self.anchors),
            anchors_with_raw_range=raw_count,
            anchors_with_canonical_range=canonical_count,
            anchors_with_layout_range=layout_count,
            raw_anchor_count=raw_count,
            canonical_anchor_count=canonical_count,
            layout_anchor_count=layout_count,
            anchors_with_raw_and_canonical=raw_and_canonical,
            anchors_with_raw_only=raw_only,
            anchors_with_canonical_only=canonical_only,
            anchors_with_layout=layout_count,
            exact_count=sum(anchor.anchor_status == "exact" for anchor in self.anchors),
            projected_count=sum(anchor.anchor_status == "projected" for anchor in self.anchors),
            partial_count=sum(anchor.anchor_status == "partial" for anchor in self.anchors),
            missing_count=sum(anchor.anchor_status == "missing" for anchor in self.anchors),
            ambiguous_count=sum(anchor.anchor_status == "ambiguous" for anchor in self.anchors),
            single_source_count=sum(
                anchor.anchor_status == "single_source" for anchor in self.anchors
            ),
            ambiguous_anchor_count=sum(
                anchor.anchor_status == "ambiguous" for anchor in self.anchors
            ),
            single_source_anchor_count=sum(
                anchor.anchor_status == "single_source" for anchor in self.anchors
            ),
            unmapped_raw_token_count=self.summary.unmapped_raw_token_count,
            unmapped_canonical_token_count=self.summary.unmapped_canonical_token_count,
            canonical_unmapped_count=self.summary.unmapped_canonical_token_count,
            layout_unmapped_count=raw_count
            - sum(
                _anchor_has_source(anchor, "technical_raw_text")
                and _anchor_has_source(anchor, "layout_text")
                for anchor in self.anchors
            ),
            repeated_token_ambiguity_count=self.summary.repeated_token_ambiguity_count,
            evidence_only_possible_count=anchors_without_raw,
            canonical_row_construction_count=sum(
                "canonical_row_construction" in anchor.flags for anchor in self.anchors
            ),
            canonical_geometry_projection_count=sum(
                "canonical_geometry_projection" in anchor.flags for anchor in self.anchors
            ),
            canonical_fallback_count=sum(
                "canonical_map_lineage" in anchor.flags for anchor in self.anchors
            ),
            raw_to_canonical_coverage_ratio=self.summary.raw_to_canonical_coverage_ratio,
            raw_to_layout_coverage_ratio=self.summary.raw_to_layout_coverage_ratio,
        )
        if self.summary != expected:
            raise ValueError("anchor graph summary does not match anchors")
        return self


def _anchor_has_source(anchor: DocumentTextAnchorV1, source_name: str) -> bool:
    return any(source_range.source_name == source_name for source_range in anchor.source_ranges)


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
    # Cross-type precedence: a higher-precedence type suppresses a fully-contained lower-precedence
    # one (e.g. EMAIL_ADDRESS over a URL matched on the email's domain). Deterministic and
    # table-driven.
    "cross_type_precedence",
    "dropped_cross_type_subordinate",
]
# Structural-context validation reason codes (subtractive; see ADR-0043). A code is never removed
# or repurposed. ``structural_heading_rejected`` marks a dropped candidate and so is recorded only
# in the run summary, not on a surviving entity's provenance.
PiiStructuralReason = Literal[
    "structural_cell_clip",
    "structural_label_value_trimmed",
    "structural_heading_rejected",
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
    # Structural-context validation outcomes applied to this surviving entity (span clipped/trimmed
    # to a structural boundary). Empty unless the stage ran and modified this entity. Text-free.
    structural_reasons: list[PiiStructuralReason] = Field(default_factory=list)


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


class PiiStructuralValidationSummary(BaseModel):
    """Structural-context validation outcome (ADR-0043). Reason codes and counts only, never text.

    A strictly subtractive stage: ``clipped``/``trimmed`` narrow a surviving span to a structural
    boundary; ``dropped`` rejects a heading false positive. ``applied`` is false when the stage is
    disabled, in which case the counts are all zero and no entity was touched.
    """

    applied: bool
    input_candidate_count: int = Field(ge=0)
    output_entity_count: int = Field(ge=0)
    clipped_count: int = Field(ge=0)
    trimmed_count: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    by_reason: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_counts(self) -> PiiStructuralValidationSummary:
        # Clipping/trimming keep the entity (only drops remove one), so input == output + dropped.
        if self.input_candidate_count != self.output_entity_count + self.dropped_count:
            raise ValueError("input candidates must equal output plus dropped")
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
    structural_validation: PiiStructuralValidationSummary | None = Field(
        default=None,
        description=(
            "Structural-context validation summary (ADR-0043). None on artifacts written before "
            "the stage existed, or when it was disabled for this run."
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
    # Additive (Runtime Job UX v1): true once a job reached a terminal state
    # (succeeded/failed/canceled), so a client can stop polling without hardcoding the status set.
    is_terminal: bool = False


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


PiiReviewDecisionScope = Literal["entity_group", "occurrence", "manual_addition"]
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

    record_type: Literal["decision"] = "decision"
    schema_version: Literal["1"] = "1"
    app_version: str
    recorded_at: str
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description=(
            "Exact text_result consumed by the referenced PII artifact. Optional only for "
            "legacy decision lines written before direct Review L9 text lineage."
        ),
    )
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


class PiiManualAdditionRequest(BaseModel):
    """Request body to add a span the engine missed (PII L14 / Review L10, ADR-0035).

    Offsets are canonical-text offsets (into the latest ``reading_text``), not raw offsets — the
    reviewer selects in the canonical reading-text view, which is the human-facing default (L10.5).
    """

    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def _normalize_note(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _validate_span(self) -> PiiManualAdditionRequest:
        if self.canonical_end <= self.canonical_start:
            raise ValueError("canonical_end must be after canonical_start")
        return self


class PiiManualAdditionRecord(BaseModel):
    """One persisted manual-addition line, appended to the same decision JSONL log (ADR-0035).

    Distinguished from :class:`PiiReviewDecisionRecord` by ``record_type``. Unlike a decision, a
    manual addition has no originating ``pii_result`` entity, so it cannot be scoped to a
    ``pii_result`` artifact id the way decisions are — it is instead scoped to the ``text_result``
    its canonical offsets were captured against. ``pii_artifact_id`` is informational lineage only
    (the PII run active at add time); it is never used for staleness or target-existence checks.
    """

    record_type: Literal["manual_addition"] = "manual_addition"
    schema_version: Literal["1"] = "1"
    app_version: str
    recorded_at: str
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    addition_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    pii_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    raw_start: int | None = Field(default=None, ge=0)
    raw_end: int | None = Field(default=None, ge=1)
    raw_projection_status: Literal["exact", "partial", "unmapped"]
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _validate_spans(self) -> PiiManualAdditionRecord:
        if self.canonical_end <= self.canonical_start:
            raise ValueError("canonical_end must be after canonical_start")
        if (self.raw_start is None) != (self.raw_end is None):
            raise ValueError("raw_start and raw_end must both be set or both be None")
        if (
            self.raw_start is not None
            and self.raw_end is not None
            and self.raw_end <= self.raw_start
        ):
            raise ValueError("raw_end must be after raw_start")
        if self.raw_projection_status == "unmapped" and self.raw_start is not None:
            raise ValueError("unmapped raw_projection_status must not carry a raw span")
        if self.raw_projection_status != "unmapped" and self.raw_start is None:
            raise ValueError("exact/partial raw_projection_status requires a raw span")
        return self


class PiiManualAdditionAck(BaseModel):
    """Confirmation returned after a manual addition is recorded."""

    recorded: bool
    addition_id: str
    entity_type: str
    canonical_start: int
    canonical_end: int
    raw_projection_status: Literal["exact", "partial", "unmapped"]
    created_at: str


class PiiManualAddition(BaseModel):
    """One reviewable manual addition: a human-added span, distinct from any machine detection.

    Never merged into ``occurrences``/``groups`` (both detector-origin only) and never surfaced
    through ``pii_result`` or the anchor-bound entity contract — see ADR-0035. Defaults to
    ``accepted`` (pseudonymize-bound), mirroring how every detected entity already defaults, so
    there is no separate "pending" state.
    """

    addition_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    raw_start: int | None = Field(default=None, ge=0)
    raw_end: int | None = Field(default=None, ge=1)
    raw_projection_status: Literal["exact", "partial", "unmapped"]
    origin: Literal["human"] = "human"
    note: str | None = Field(default=None, max_length=1000)
    created_at: str
    review_status: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    # Whether this addition's canonical offsets still refer to the document's current text
    # artifact. A "stale" addition stays listed for audit/history, but its offsets belong to a
    # superseded ``reading_text`` — it must never be rendered as a highlight into, or an active
    # decision against, the current text. Defaults to "current" for legacy persisted snapshots.
    artifact_currency: Literal["current", "stale"] = "current"


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
    updated_at: str | None = Field(
        default=None,
        description=(
            "Timestamp of the effective decision record (occurrence-level if present, else the "
            "covering group's); None while no explicit decision has been recorded yet."
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
    # Entity-group ids are deterministic per (type, normalized value), so a decision recorded
    # against a superseded PII artifact can name the same group id this run detects again. It is
    # never reapplied (``review_decision`` above stays None until re-decided) — these two additive
    # fields surface that superseded previous decision explicitly, so the UI can say "a previous
    # decision exists but no longer applies" instead of looking identical to "never reviewed".
    stale_decision: PiiReviewDecisionValue | None = None
    stale_decision_recorded_at: str | None = None


# --- Review Result v1: unified stable entity entries (this branch) -------------------------------
# A Review Result entry is a stable, durable domain artifact for one reviewed PII entity — detected
# or manually added — separate from OCR/text artifacts, detection evidence, the Text Anchor Graph,
# and the original ``pii_result``. Review decides the disposition of a stable *entity identity*; it
# never mutates OCR/Text/anchor artifacts or ``pii_result``. ``entry_id`` is always the existing
# occurrence/addition uuid the decision log already keys on (ADR-0033/ADR-0034's occurrence-id-
# primary guardrail — anchor ids are only stable per text-artifact-bytes x graph-builder version, so
# they are never a persisted lookup key). ``anchor_entity_id`` is an additive, freshly-recomputed
# secondary reference into the anchor-bound entity contract (ADR-0031 Phase C), rebuilt from the
# *exact* pii/text artifact pair an entry actually originated from — never "today's" pair for a
# stale entry — so a re-run, tokenizer change, or newer anchor-graph builder version can never
# silently reattach a decision to a different entity.
PiiReviewEntryOrigin = Literal["detected", "manual"]
# Whether the entry's own originating artifact (its ``pii_artifact_id`` for a detected entry, its
# ``text_artifact_id`` for a manual addition) still matches the document's current one. "stale"
# never causes silent reapplication elsewhere — it only makes visible what was already true.
PiiReviewArtifactCurrency = Literal["current", "stale"]
# Whether stable identity beyond the primary occurrence/addition id could be established for this
# entry. "resolved" -- anchor-bound (detected) or a resolved raw/canonical projection (manual).
# "unresolved" -- identity could be attempted but came back missing/ambiguous/not-applicable; the
# entry is still fully reviewable, just without a secondary anchor/raw reference. "incompatible" --
# a genuine structural break (the entry's own stored offsets no longer fit inside its own
# referenced text, or that referenced artifact fails to load) rather than an ordinary binding gap.
# Never guessed.
PiiReviewIdentityStatus = Literal["resolved", "unresolved", "incompatible"]


class PiiReviewResultEntry(BaseModel):
    """One stable, reviewed PII entity — detected or manually added — in the unified Review Result.

    Unifies detector-origin occurrences and reviewer-added manual additions behind one shape so a
    downstream consumer (e.g. a future Replacement Plan) can read decisions without distinguishing
    origin-specific record types or interpreting the review overlay's own JSONL/decision internals.
    No copied source text: every field here is an id, code, offset-free status, or count.
    """

    entry_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    origin: PiiReviewEntryOrigin
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    entity_group_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    pii_artifact_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="The originating pii_result artifact; None for manual additions (no detector "
        "origin to key on).",
    )
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_currency: PiiReviewArtifactCurrency
    identity_status: PiiReviewIdentityStatus
    identity_reason_codes: list[PiiEntityReviewReasonCode] = Field(default_factory=list)
    anchor_entity_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    mapping_status: PiiEntityMappingStatus
    review_status: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    decision_scope: PiiReviewDecisionScope | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def _validate_entry(self) -> PiiReviewResultEntry:
        if self.origin == "manual" and self.pii_artifact_id is not None:
            raise ValueError("manual additions have no originating pii_result artifact")
        if self.origin == "detected" and self.pii_artifact_id is None:
            raise ValueError("detected entries require their originating pii_result artifact")
        if self.anchor_entity_id is not None and (
            self.origin != "detected" or self.identity_status != "resolved"
        ):
            raise ValueError("anchor_entity_id is only set for resolved, detected entries")
        if self.identity_status == "resolved":
            if self.identity_reason_codes:
                raise ValueError("resolved identity must not carry reason codes")
        elif not self.identity_reason_codes:
            raise ValueError("unresolved/incompatible identity requires at least one reason code")
        return self


class PiiStaleReviewDecision(BaseModel):
    """One recorded review item that no longer applies to the current result (audit/history only).

    Itemizes what ``stale_decision_count`` previously only aggregated, so the warning, the review
    cards, and the effective state can describe the same set. For an ``entity_group``/``occurrence``
    item this is the latest decision line recorded against a superseded ``pii_result``
    (``artifact_id`` names that superseded run); for a ``manual_addition`` item it is an addition
    whose ``text_artifact_id`` no longer matches the current text result. No raw document text is
    ever carried — only ids, codes, and timestamps.
    """

    target_type: PiiReviewDecisionScope
    target_id: str = Field(min_length=1, max_length=64)
    # The recorded decision; None for a stale manual addition that was never explicitly decided
    # (its implied default was "pseudonymize", but a stale item has no active decision at all).
    decision: PiiReviewDecisionValue | None = None
    # Known for manual additions (stored on the addition record); decision lines do not carry one.
    entity_type: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    recorded_at: str
    # The superseded pii_result the decision was recorded against; None for manual additions.
    artifact_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    # The superseded text_result a manual addition was captured against; None for decisions.
    text_artifact_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class PiiReviewResult(BaseModel):
    """The reviewable PII view for one document: groups and occurrences with resolved decisions.

    Computed on demand from the latest ``pii_result`` and the persisted decision overlay; the
    ``pii_result`` artifact and its entities/offsets are never mutated by review decisions.
    """

    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_text_artifact_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Exact text_result consumed by this reviewable PII run; None on legacy views.",
    )
    groups: list[PiiEntityGroupReview] = Field(default_factory=list)
    occurrences: list[PiiReviewOccurrence] = Field(default_factory=list)
    # PII L14 / Review L10 (ADR-0035): human-added spans, parallel to but never merged into
    # ``groups``/``occurrences`` (both detector-origin only, keyed off ``PiiEntity.id``).
    manual_additions: list[PiiManualAddition] = Field(default_factory=list)
    # Review Result v1 (this branch): one coherent, stable entry per occurrence/manual addition --
    # see the type-level docstrings above. Additive; never a second source of truth for the decision
    # itself (still resolved from the same JSONL overlay `groups`/`occurrences`/`manual_additions`
    # already reflect).
    entries: list[PiiReviewResultEntry] = Field(default_factory=list)
    # Review L8 (ADR-0034): a decision is only ever matched against the exact ``pii_result``
    # artifact it was recorded for, so a re-run (new artifact id) already never silently reapplies
    # an old decision -- but previously that fell back to "no decision recorded" indistinguishably
    # from a genuinely fresh entity. These two additive fields make that explicit: how many
    # previously-recorded decisions exist for this document but target an artifact id other than
    # ``artifact_id`` above (superseded by a later PII run), never counted more than once per
    # (target_type, target_id).
    stale_decision_count: int = Field(default=0, ge=0)
    has_stale_decisions: bool = False
    # Itemization of exactly the set `stale_decision_count` counts (audit/history, never applied).
    # Newly computed results always fill this consistently; legacy persisted snapshots may carry a
    # count without items, so the model deliberately does not cross-validate count == len(items).
    stale_decisions: list[PiiStaleReviewDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_staleness(self) -> PiiReviewResult:
        if self.has_stale_decisions != (self.stale_decision_count > 0):
            raise ValueError("has_stale_decisions must match stale_decision_count > 0")
        return self

    @model_validator(mode="after")
    def _validate_entries(self) -> PiiReviewResult:
        expected_ids = {occurrence.occurrence_id for occurrence in self.occurrences} | {
            addition.addition_id for addition in self.manual_additions
        }
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("entries must have unique entry ids")
        if set(entry_ids) != expected_ids:
            raise ValueError("entries must exactly cover occurrences and manual additions")
        return self


class PiiReviewResultArtifact(BaseModel):
    """Immutable, versioned per-run snapshot of the review overlay (Review L8, ADR-0034).

    Wraps the same :class:`PiiReviewResult` shape ``GET …/pii/review`` already computes on demand,
    but persisted through the same file-based artifact model as every other station (``original``/
    ``audit``/``text``/``pii``): one immutable JSON file per snapshot, newest-wins on read. A fresh
    snapshot is saved every time a review decision is recorded, so the durable review state is a
    proper artifact-history entry rather than only reconstructible by replaying the JSONL decision
    log. The JSONL log (``pii_review_decisions.jsonl``) remains the append-only write-time source of
    truth this snapshot is built from; this artifact is the durable *read* model. Keys primarily on
    occurrence ids (``PiiReviewOccurrence.occurrence_id``); any anchor-derived identity from the
    entity contract (ADR-0031 Phase C) is deliberately not used as a key here, per the
    occurrence-id-primary rule (anchor ids are only stable per text-artifact-bytes x graph-builder
    version, not yet suitable as a persisted primary key).
    """

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    artifact_type: Literal["pii_review_result"] = "pii_review_result"
    station: Literal["pii_review"] = "pii_review"
    input_pii_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    input_text_artifact_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Exact text_result consumed by the review snapshot's PII artifact.",
    )
    media_type: Literal["application/json"] = "application/json"
    created_at: str
    content: PiiReviewResult

    @model_validator(mode="after")
    def _validate_content_identity(self) -> PiiReviewResultArtifact:
        if self.content.document_id != self.document_id:
            raise ValueError("review result content belongs to a different document")
        if self.content.artifact_id != self.input_pii_artifact_id:
            raise ValueError("review result content references a different PII artifact")
        if self.content.input_text_artifact_id != self.input_text_artifact_id:
            raise ValueError("review result content references a different text artifact")
        return self


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
# Stable review reason codes surfaced on the review-ready entity. Anchor-binding codes are derived
# by the anchor-binding service (see ``pii_anchor_binding.py``); canonical-mapping codes are derived
# here; overlap codes are lifted from the entity's overlap provenance (see
# ``pii_entity_contract.py``). A code is never removed or repurposed.
PiiEntityReviewReasonCode = Literal[
    "anchor_binding_partial",
    "anchor_binding_missing",
    "anchor_binding_ambiguous",
    "anchor_missing",
    "anchor_partial_overlap",
    "anchor_ambiguous",
    "canonical_mapping_missing",
    "canonical_mapping_partial",
    "canonical_mapping_ambiguous",
    "canonical_range_missing",
    "layout_range_missing",
    "evidence_only_identity",
    "source_range_missing",
    "text_anchor_graph_missing",
    "text_anchor_graph_degraded",
    "repeated_token_ambiguity",
    "reading_text_mapping_missing",
    "layout_mapping_unavailable",
    "source_not_available",
    "invalid_entity_range",
    "detection_evidence_only",
    "binding_not_required",
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


# --- Anchor-bound PII entity model v1 (ADR-0031 Phase C) -----------------------------------------
# The review-ready PII entity is an *anchor-bound domain object*, not an offset-first detector hit.
# Detection evidence (a recognizer observing a span on a text view) is normalized against the
# OCR/Text-owned Text Anchor Graph v1 (ADR-0031 Phase B) into a stable entity whose identity derives
# from anchor identity + entity type where an exact binding exists. Raw offsets, canonical ranges,
# and the entity value remain as evidence/display fields — they are no longer the source of truth.
# Missing/partial/ambiguous binding is explicit and never drops a detection; when no anchor graph is
# available for the run, identity degrades to an explicit evidence-only fallback. All binding
# metadata is text-free: ids, offsets, statuses, roles, counts, and reason codes only.

# How one detection span binds to the raw text-anchor identity layer. ``exact``/``partial`` are the
# two anchor-bound states (aligned to whole anchors vs. cutting across them); ``missing`` (no anchor
# overlaps), ``ambiguous`` (incompatible candidate anchor sets), and ``not_applicable`` (no anchor
# graph for the run) keep the detection fully reviewable as evidence-only. Never removed/repurposed.
PiiAnchorBindingStatus = Literal["exact", "partial", "missing", "ambiguous", "not_applicable"]
# The part an anchor plays for one entity: the entity span itself, a supporting/overlapping span, a
# view-specific display projection, or an inferred (unconfirmed) span.
PiiAnchorBindingRole = Literal["entity_span", "supporting_span", "display_span", "inferred_span"]
# Stable machine-readable reason codes explaining a binding outcome. Text-free.
PiiAnchorBindingReason = Literal[
    "anchor_exact_match",
    "anchor_partial_overlap",
    "anchor_missing",
    "anchor_ambiguous",
    "canonical_range_missing",
    "layout_range_missing",
    "evidence_only_identity",
    "source_range_missing",
    "text_anchor_graph_missing",
    "text_anchor_graph_degraded",
    "repeated_token_ambiguity",
    "reading_text_mapping_missing",
    "layout_mapping_unavailable",
    "source_not_available",
    "invalid_entity_range",
    "detection_evidence_only",
    "binding_not_required",
]
# Whether entity identity is anchor-derived (preferred) or evidence-only. ``anchor_exact`` derives
# the id from the ordered anchor ids + type; ``anchor_partial`` additionally pins the raw span;
# ``evidence_only`` falls back to document + type + raw span (no reliable anchor identity).
PiiEntityIdentityBasis = Literal["anchor_exact", "anchor_partial", "evidence_only"]
# Which detection input a source observation came from. Raw is the only active input today.
PiiDetectionRole = Literal["primary", "supporting"]


class PiiEntityAnchorRef(BaseModel):
    """One anchor an entity references, in a named text view. Offsets/ids/codes only — no text.

    ``mapping_status`` carries the referenced anchor's own view-range honesty for a
    ``display_span`` ref (``exact`` for a byte-identical row, ``normalized``/``merged`` for a
    reformatted/unioned one — see :class:`ReadingTextRowLineageMap`) so a bridged display range
    can be told apart from a byte-exact one; it is ``None`` for ``entity_span``/``supporting_span``/
    ``inferred_span`` roles, which describe raw-anchor overlap rather than a view projection.
    """

    anchor_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_name: DocumentTextAnchorSourceName
    source_range: PiiEntitySpan | None = None
    binding_status: PiiAnchorBindingStatus
    binding_role: PiiAnchorBindingRole
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_codes: list[PiiAnchorBindingReason] = Field(default_factory=list)
    mapping_status: DocumentTextAnchorStatus | None = None


class PiiEntityAnchorSet(BaseModel):
    """The ordered anchor identity an entity binds to.

    Empty for an evidence-only fallback entity.
    """

    anchor_ids: list[str] = Field(default_factory=list)
    binding_status: PiiAnchorBindingStatus
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate(self) -> PiiEntityAnchorSet:
        if self.count != len(self.anchor_ids):
            raise ValueError("anchor set count does not match anchor ids")
        if len(self.anchor_ids) != len(set(self.anchor_ids)):
            raise ValueError("anchor set ids must be unique")
        return self


class PiiSourceObservation(BaseModel):
    """One detector observation on a text view, before it became a stable domain entity.

    This is the detection *evidence*: which recognizer saw a span in which view, with what
    confidence, and how that observation bound to the anchor identity layer. It is text-free — the
    observed value lives on :class:`AnchorBoundPiiEntityV1.value` (already exposed by
    ``GET …/pii``), never here.
    """

    detection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    recognizer: str
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    source_name: DocumentTextAnchorSourceName = "technical_raw_text"
    detection_source: PiiEntityDetectionSource = "raw_text"
    detection_role: PiiDetectionRole = "primary"
    source_range: PiiEntitySourceSpan
    confidence: float = Field(ge=0, le=1)
    binding_status: PiiAnchorBindingStatus
    binding_reasons: list[PiiAnchorBindingReason] = Field(default_factory=list)
    provenance: PiiEntityProvenance | None = None


class PiiAnchorBindingSummary(BaseModel):
    """Per-run counts of entities by anchor-binding outcome. Counts only, never entity text."""

    total: int = Field(ge=0)
    anchor_bound: int = Field(ge=0)
    evidence_only: int = Field(ge=0)
    exact: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    ambiguous: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)
    total_entities: int = Field(default=0, ge=0)
    anchor_bound_entities: int = Field(default=0, ge=0)
    evidence_only_entities: int = Field(default=0, ge=0)
    exact_bound_entities: int = Field(default=0, ge=0)
    partial_bound_entities: int = Field(default=0, ge=0)
    ambiguous_bound_entities: int = Field(default=0, ge=0)
    entities_with_raw_range: int = Field(default=0, ge=0)
    entities_with_canonical_range: int = Field(default=0, ge=0)
    entities_with_layout_range: int = Field(default=0, ge=0)
    missing_canonical_range_count: int = Field(default=0, ge=0)
    missing_layout_range_count: int = Field(default=0, ge=0)
    binding_reason_counts: dict[str, int] = Field(default_factory=dict)
    warning_codes: list[str] = Field(default_factory=list)
    # Metrics-only coverage ratios for the pii-binding-quality-suite gate (ADR-0033): the fraction
    # of entities that received *any* anchor binding (exact or partial) vs. purely `exact`. `0.0`
    # when there are no entities (vacuous, never a false claim of full coverage). Derived from the
    # counts above; never an independent source of truth.
    anchor_bound_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    exact_bound_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate(self) -> PiiAnchorBindingSummary:
        _validate_binding_status_counts(self)
        _validate_binding_alias_counts(self)
        _validate_binding_range_counts(self)
        _validate_binding_ratios(self)
        return self


def _validate_binding_status_counts(summary: PiiAnchorBindingSummary) -> None:
    by_status = (
        summary.exact
        + summary.partial
        + summary.missing
        + summary.ambiguous
        + summary.not_applicable
    )
    if summary.total != by_status:
        raise ValueError("binding summary total does not match per-status counts")
    if summary.anchor_bound != summary.exact + summary.partial:
        raise ValueError("anchor_bound must equal exact plus partial")
    if summary.evidence_only != summary.missing + summary.ambiguous + summary.not_applicable:
        raise ValueError("evidence_only must equal missing plus ambiguous plus not_applicable")


def _validate_binding_alias_counts(summary: PiiAnchorBindingSummary) -> None:
    if summary.total_entities != summary.total:
        raise ValueError("total_entities must mirror total")
    if summary.anchor_bound_entities != summary.anchor_bound:
        raise ValueError("anchor_bound_entities must mirror anchor_bound")
    if summary.evidence_only_entities != summary.evidence_only:
        raise ValueError("evidence_only_entities must mirror evidence_only")
    if summary.exact_bound_entities != summary.exact:
        raise ValueError("exact_bound_entities must mirror exact")
    if summary.partial_bound_entities != summary.partial:
        raise ValueError("partial_bound_entities must mirror partial")
    if summary.ambiguous_bound_entities != summary.ambiguous:
        raise ValueError("ambiguous_bound_entities must mirror ambiguous")


def _validate_binding_range_counts(summary: PiiAnchorBindingSummary) -> None:
    if (
        summary.entities_with_canonical_range + summary.missing_canonical_range_count
        != summary.total
    ):
        raise ValueError("canonical range counts must cover every entity")
    if summary.entities_with_layout_range + summary.missing_layout_range_count != summary.total:
        raise ValueError("layout range counts must cover every entity")


def _validate_binding_ratios(summary: PiiAnchorBindingSummary) -> None:
    if summary.anchor_bound_ratio != _pii_binding_ratio(summary.anchor_bound, summary.total):
        raise ValueError("anchor_bound_ratio must match anchor_bound / total")
    if summary.exact_bound_ratio != _pii_binding_ratio(summary.exact, summary.total):
        raise ValueError("exact_bound_ratio must match exact / total")


class AnchorBoundPiiEntityV1(BaseModel):
    """A stable, review-ready PII entity built from text anchors + detection evidence (ADR-0031).

    Identity is anchor-derived where an exact binding exists (``entity_id`` from the ordered anchor
    ids + type). Detection evidence (``source_observations``), overlap provenance, the raw span, and
    the entity ``value`` are retained as evidence/display — they are not the identity. Binding
    metadata carries no raw token text; ``value`` mirrors ``PiiEntity.text`` (already on
    ``GET …/pii``) and appears only here, never in binding refs, reasons, or observations.
    """

    entity_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    identity_basis: PiiEntityIdentityBasis
    binding_status: PiiAnchorBindingStatus
    binding_reasons: list[PiiAnchorBindingReason] = Field(default_factory=list)
    anchor_set: PiiEntityAnchorSet
    anchor_refs: list[PiiEntityAnchorRef] = Field(default_factory=list)
    source_observations: list[PiiSourceObservation] = Field(min_length=1)
    provenance: PiiEntityProvenance | None = None
    confidence: float = Field(ge=0, le=1)
    value: str
    raw_text_range: PiiEntitySourceSpan

    @model_validator(mode="after")
    def _validate_entity(self) -> AnchorBoundPiiEntityV1:
        if self.raw_text_range.end - self.raw_text_range.start != len(self.value):
            raise ValueError("raw text range length must match value length")
        if self.anchor_set.binding_status != self.binding_status:
            raise ValueError("anchor set binding status must match the entity binding status")
        anchor_bound = self.identity_basis in ("anchor_exact", "anchor_partial")
        if anchor_bound and not self.anchor_set.anchor_ids:
            raise ValueError("anchor-bound entities require at least one anchor id")
        if not anchor_bound and self.anchor_set.anchor_ids:
            raise ValueError("evidence-only entities must not carry an entity-span anchor set")
        expected_status = {"anchor_exact": "exact", "anchor_partial": "partial"}
        if anchor_bound and self.binding_status != expected_status[self.identity_basis]:
            raise ValueError("anchor-bound identity basis must match binding status")
        if not anchor_bound and self.binding_status not in (
            "missing",
            "ambiguous",
            "not_applicable",
        ):
            raise ValueError("evidence-only identity requires a missing/ambiguous/na binding")
        return self


class ReviewReadyAnchorBoundPiiEntity(AnchorBoundPiiEntityV1):
    """An anchor-bound entity enriched with its canonical display view and resolved review state.

    Review decisions attach to the stable entity via its source occurrence ids
    (``source_entity_ids`` → the existing decision overlay), so review state stays consistent even
    though ``entity_id`` is now anchor-derived. Canonical reading ranges are a view-specific display
    projection, not identity.
    """

    entity_group_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_entity_ids: list[str] = Field(min_length=1)
    mapping_status: PiiEntityMappingStatus
    canonical_reading_text_range: PiiEntityDisplaySpan | None = None
    review_state: PiiReviewStatus = "accepted"
    review_decision: PiiReviewDecisionValue | None = None
    decision_scope: PiiReviewDecisionScope | None = None
    display: PiiEntityDisplay
    warnings: list[PiiEntityReviewReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_review(self) -> ReviewReadyAnchorBoundPiiEntity:
        has_canonical = self.canonical_reading_text_range is not None
        if has_canonical != (self.mapping_status in ("exact", "projected")):
            raise ValueError("canonical range present iff mapping status is exact or projected")
        if self.display.raw_highlight_range != PiiEntitySpan(
            start=self.raw_text_range.start, end=self.raw_text_range.end
        ):
            raise ValueError("display raw highlight range must match the raw text range")
        if self.display.display_label != self.entity_type:
            raise ValueError("display label must be the entity type")
        observation_ids = sorted(obs.detection_id for obs in self.source_observations)
        if sorted(self.source_entity_ids) != observation_ids:
            raise ValueError("source entity ids must match source observation detection ids")
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
    """Anchor-bound review-ready PII entity contract for a document's latest ``pii_result``.

    A pure, derived, additive view (ADR-0031 Phase C, building on ADR-0029): it never mutates the
    artifact and adds no detection. Each entity is an anchor-bound domain object — offsets and
    canonical ranges are evidence/display, anchor identity is the source of truth.
    ``binding_summary`` counts anchor-binding outcomes; ``mapping_summary`` counts canonical
    display coverage. Existing
    ``GET …/pii`` and ``GET …/pii/review`` responses are unchanged; ``anchor_graph_available`` is
    false when no matching Text Anchor Graph could be built for the run (evidence-only degrade).
    """

    contract_version: Literal["1.0"] = "1.0"
    document_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    pii_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    text_artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    reading_text_available: bool
    anchor_graph_available: bool
    anchor_graph_status: DocumentTextAnchorValidationStatus | None = None
    input_contract: PiiInputContractSummary | None = None
    overlap_resolution: PiiOverlapResolutionSummary | None = None
    entities: list[ReviewReadyAnchorBoundPiiEntity] = Field(default_factory=list)
    binding_summary: PiiAnchorBindingSummary
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
        expected_binding = PiiAnchorBindingSummary(
            total=len(self.entities),
            anchor_bound=sum(
                e.identity_basis in ("anchor_exact", "anchor_partial") for e in self.entities
            ),
            evidence_only=sum(e.identity_basis == "evidence_only" for e in self.entities),
            exact=sum(e.binding_status == "exact" for e in self.entities),
            partial=sum(e.binding_status == "partial" for e in self.entities),
            missing=sum(e.binding_status == "missing" for e in self.entities),
            ambiguous=sum(e.binding_status == "ambiguous" for e in self.entities),
            not_applicable=sum(e.binding_status == "not_applicable" for e in self.entities),
            total_entities=len(self.entities),
            anchor_bound_entities=sum(
                e.identity_basis in ("anchor_exact", "anchor_partial") for e in self.entities
            ),
            evidence_only_entities=sum(e.identity_basis == "evidence_only" for e in self.entities),
            exact_bound_entities=sum(e.binding_status == "exact" for e in self.entities),
            partial_bound_entities=sum(e.binding_status == "partial" for e in self.entities),
            ambiguous_bound_entities=sum(e.binding_status == "ambiguous" for e in self.entities),
            entities_with_raw_range=len(self.entities),
            entities_with_canonical_range=sum(
                e.display.canonical_highlight_range is not None for e in self.entities
            ),
            entities_with_layout_range=sum(
                _entity_has_anchor_ref_source(e, "layout_text") for e in self.entities
            ),
            missing_canonical_range_count=sum(
                e.display.canonical_highlight_range is None for e in self.entities
            ),
            missing_layout_range_count=sum(
                not _entity_has_anchor_ref_source(e, "layout_text") for e in self.entities
            ),
            binding_reason_counts=_pii_binding_reason_counts(self.entities),
            warning_codes=_pii_binding_warning_codes(self.entities),
            anchor_bound_ratio=_pii_binding_ratio(
                sum(e.identity_basis in ("anchor_exact", "anchor_partial") for e in self.entities),
                len(self.entities),
            ),
            exact_bound_ratio=_pii_binding_ratio(
                sum(e.binding_status == "exact" for e in self.entities), len(self.entities)
            ),
        )
        if self.binding_summary != expected_binding:
            raise ValueError("binding summary does not match entities")
        expected_mapping = PiiEntityMappingSummary(
            exact=sum(e.mapping_status == "exact" for e in self.entities),
            projected=sum(e.mapping_status == "projected" for e in self.entities),
            partial=sum(e.mapping_status == "partial" for e in self.entities),
            missing=sum(e.mapping_status == "missing" for e in self.entities),
            ambiguous=sum(e.mapping_status == "ambiguous" for e in self.entities),
            not_applicable=sum(e.mapping_status == "not_applicable" for e in self.entities),
        )
        if self.mapping_summary != expected_mapping:
            raise ValueError("mapping summary does not match entities")
        if self.needs_review_count != sum(e.display.needs_review for e in self.entities):
            raise ValueError("needs_review_count does not match entities")
        return self


def _entity_has_anchor_ref_source(
    entity: ReviewReadyAnchorBoundPiiEntity, source_name: str
) -> bool:
    return any(
        ref.source_name == source_name and ref.source_range is not None
        for ref in entity.anchor_refs
    )


def _pii_binding_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _pii_binding_reason_counts(
    entities: list[ReviewReadyAnchorBoundPiiEntity],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        for reason in entity.binding_reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _pii_binding_warning_codes(
    entities: list[ReviewReadyAnchorBoundPiiEntity],
) -> list[str]:
    warning_codes: set[str] = set()
    for entity in entities:
        warning_codes.update(
            reason for reason in entity.binding_reasons if reason != "anchor_exact_match"
        )
        warning_codes.update(entity.warnings)
    return sorted(warning_codes)


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
