"""Pydantic response models for the API (the trust-boundary contract)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    """Text-layer statistics for one PDF page."""

    page_number: int = Field(ge=1)
    text_char_count: int = Field(ge=0)
    has_text_layer: bool


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


class ConfigResponse(BaseModel):
    """Public upload constraints, so the frontend can mirror the backend's source of truth."""

    max_upload_bytes: int = Field(description="Maximum accepted upload size in bytes.", ge=0)
    allowed_extensions: list[str] = Field(description="Allowed file extensions (lowercase).")


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
