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


class TextPageResult(BaseModel):
    """Ordered text extracted from one PDF or image page."""

    page_number: int = Field(ge=1)
    source: Literal["pdf_text_layer", "paddleocr"]
    has_text_layer: bool
    ocr_used: bool
    text: str
    text_char_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_page_summary(self) -> TextPageResult:
        if self.text_char_count != len(self.text):
            raise ValueError("page text character count does not match text")
        expected = (self.source == "pdf_text_layer", self.source == "paddleocr")
        if (self.has_text_layer, self.ocr_used) != expected:
            raise ValueError("page source does not match text-layer and OCR flags")
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
