"""Synchronous Audit v1 analysis of verified original artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from docx import Document as DocxDocument
from PIL import Image
from pypdf import PdfReader

from app.config import Settings
from app.errors import ApiError
from app.schemas import AuditArtifact, AuditContent, AuditPageResult, OriginalArtifact
from app.services.artifact_service import get_latest_audit_artifact, save_audit_artifact
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.docx_extraction import extract_docx_text
from app.services.original_artifact_service import get_verified_original
from app.services.text_quality import BROKEN_TEXT_LAYER, assess_text_quality

_PDF_MIME_TYPE = "application/pdf"
_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_IMAGE_FORMAT_BY_MIME_TYPE = {"image/png": "PNG", "image/jpeg": "JPEG"}
class AuditProcessingError(ApiError):
    """Raised when a verified original cannot be analyzed by Audit v1."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 422)


class AuditNotFoundError(ApiError):
    """Raised when a document has no persisted audit result."""

    def __init__(self) -> None:
        super().__init__("Audit result not found.", 404)


def create_audit(settings: Settings, document_id: str) -> AuditArtifact:
    """Verify, analyze, and persist a new immutable audit artifact."""
    original, original_path = get_verified_original(settings, document_id)
    content = _analyze_original(document_id, original, original_path)
    artifact = AuditArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_artifact_id=original.id,
        created_at=_now_utc_iso(),
        content=content,
    )
    save_audit_artifact(settings, artifact)
    return artifact


def get_latest_audit(settings: Settings, document_id: str) -> AuditArtifact:
    """Return the newest audit artifact after confirming the document exists."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_latest_audit_artifact(settings, document_id)
    if artifact is None:
        raise AuditNotFoundError
    return artifact


def _analyze_original(
    document_id: str, original: OriginalArtifact, original_path: Path
) -> AuditContent:
    try:
        if original.mime_type == _PDF_MIME_TYPE:
            return _analyze_pdf(document_id, original, original_path)
        if original.mime_type == _DOCX_MIME_TYPE:
            return _analyze_docx(document_id, original, original_path)
        if original.mime_type in _IMAGE_FORMAT_BY_MIME_TYPE:
            return _analyze_image(document_id, original, original_path)
    except Exception as exc:
        raise AuditProcessingError("Original artifact could not be analyzed.") from exc
    raise AuditProcessingError("Original artifact MIME type is not supported by Audit v1.")


def _analyze_pdf(
    document_id: str, original: OriginalArtifact, original_path: Path
) -> AuditContent:
    reader = PdfReader(original_path)
    pages: list[AuditPageResult] = []
    total_chars = 0
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        char_count = len(page_text)
        total_chars += char_count
        # Assess character/token plausibility so a formally-present but broken/encoded text layer
        # is not silently accepted. Only aggregate metrics are stored — never the page text.
        quality = assess_text_quality(page_text)
        pages.append(
            AuditPageResult(
                page_number=page_number,
                text_char_count=char_count,
                has_text_layer=bool(page_text.strip()),
                text_quality_status=quality.status,
                text_quality_score=quality.score,
                text_quality_reasons=quality.reasons,
                recommended_text_source=quality.recommended_text_source,
                needs_ocr=quality.needs_ocr,
            )
        )
    has_text_layer = any(page.has_text_layer for page in pages)
    flags = ["pdf_has_text_layer" if has_text_layer else "pdf_no_text_layer"]
    if any(page.needs_ocr for page in pages):
        flags.append("pdf_pages_need_ocr")
    if any(page.text_quality_status == BROKEN_TEXT_LAYER for page in pages):
        flags.append("pdf_broken_text_layer")
    return AuditContent(
        document_id=document_id,
        input_artifact_id=original.id,
        detected_mime_type=original.mime_type,
        document_kind="pdf",
        page_count=len(pages),
        has_text_layer=has_text_layer,
        text_char_count=total_chars,
        pages=pages,
        flags=flags,
        tool_versions={"pypdf": version("pypdf")},
    )


def _analyze_docx(
    document_id: str, original: OriginalArtifact, original_path: Path
) -> AuditContent:
    document = DocxDocument(str(original_path))
    # Share OCR/Text's extraction so both stations count the same content, including tables and
    # headers/footers. paragraph_count stays a body-level structural metric.
    text = extract_docx_text(document)
    return AuditContent(
        document_id=document_id,
        input_artifact_id=original.id,
        detected_mime_type=original.mime_type,
        document_kind="docx",
        paragraph_count=len(document.paragraphs),
        has_text_layer=True,
        text_char_count=len(text),
        flags=["docx_opened"],
        tool_versions={"python-docx": version("python-docx")},
    )


def _analyze_image(
    document_id: str, original: OriginalArtifact, original_path: Path
) -> AuditContent:
    with Image.open(original_path) as image:
        image.load()
        image_format = image.format
        width, height = image.size
    if image_format != _IMAGE_FORMAT_BY_MIME_TYPE[original.mime_type]:
        raise ValueError("image format does not match verified MIME type")
    return AuditContent(
        document_id=document_id,
        input_artifact_id=original.id,
        detected_mime_type=original.mime_type,
        document_kind="image",
        image_format=image_format,
        width=width,
        height=height,
        has_text_layer=False,
        text_char_count=0,
        flags=["image_opened"],
        tool_versions={"Pillow": version("Pillow")},
    )


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
