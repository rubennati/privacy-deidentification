"""Synchronous Audit v1 analysis of verified original artifacts."""

from __future__ import annotations

import hashlib
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

_PDF_MIME_TYPE = "application/pdf"
_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_IMAGE_FORMAT_BY_MIME_TYPE = {"image/png": "PNG", "image/jpeg": "JPEG"}
_HASH_CHUNK_SIZE = 1024 * 1024


class AuditConflictError(ApiError):
    """Raised when a document has no usable verified original artifact."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 409)


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
    original, original_path = _verified_original(settings, document_id)
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


def _verified_original(settings: Settings, document_id: str) -> tuple[OriginalArtifact, Path]:
    record = get_document_record(settings, document_id)
    if record is None:
        raise DocumentNotFoundError
    original = record.original_artifact
    if original is None:
        raise AuditConflictError("Document has no verified original artifact.")

    original_path = settings.upload_dir / original.storage_filename
    if not original_path.is_file():
        raise AuditConflictError("Original artifact file is unavailable.")
    if _sha256(original_path) != original.sha256:
        raise AuditConflictError("Original artifact integrity check failed.")
    return original, original_path


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
        pages.append(
            AuditPageResult(
                page_number=page_number,
                text_char_count=char_count,
                has_text_layer=bool(page_text.strip()),
            )
        )
    has_text_layer = any(page.has_text_layer for page in pages)
    return AuditContent(
        document_id=document_id,
        input_artifact_id=original.id,
        detected_mime_type=original.mime_type,
        document_kind="pdf",
        page_count=len(pages),
        has_text_layer=has_text_layer,
        text_char_count=total_chars,
        pages=pages,
        flags=["pdf_has_text_layer" if has_text_layer else "pdf_no_text_layer"],
        tool_versions={"pypdf": version("pypdf")},
    )


def _analyze_docx(
    document_id: str, original: OriginalArtifact, original_path: Path
) -> AuditContent:
    document = DocxDocument(str(original_path))
    paragraphs = list(document.paragraphs)
    return AuditContent(
        document_id=document_id,
        input_artifact_id=original.id,
        detected_mime_type=original.mime_type,
        document_kind="docx",
        paragraph_count=len(paragraphs),
        has_text_layer=True,
        text_char_count=sum(len(paragraph.text) for paragraph in paragraphs),
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as original_file:
        while chunk := original_file.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
