"""Synchronous OCR/Text Workstation v1 routing and artifact creation."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.config import Settings
from app.errors import ApiError
from app.schemas import (
    AuditArtifact,
    AuditPageResult,
    OriginalArtifact,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.artifact_service import (
    get_latest_audit_artifact,
    get_latest_text_artifact,
    save_text_artifact,
)
from app.services.document_service import DocumentNotFoundError, get_document_record
from app.services.docx_extraction import extract_docx_text
from app.services.ocr_adapters import OcrAdapter
from app.services.original_artifact_service import get_verified_original
from app.services.pdf_renderer import PdfRenderer
from app.services.pii_input_text import build_page_pii_input_text

_OCR_WORKSPACE_ROOT = Path("/tmp")


class OcrConflictError(ApiError):
    """Raised when station inputs are absent or do not describe the current original."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 409)


class OcrProcessingError(ApiError):
    """Raised when a valid station input cannot be processed."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 422)


class TextArtifactNotFoundError(ApiError):
    """Raised when a document has no persisted text result."""

    def __init__(self) -> None:
        super().__init__("Text result not found.", 404)


def create_text_artifact(
    settings: Settings,
    document_id: str,
    ocr_adapter: OcrAdapter,
    pdf_renderer: PdfRenderer,
) -> TextArtifact:
    """Verify station inputs, route extraction, and persist an immutable result."""
    original, original_path = get_verified_original(settings, document_id)
    audit = get_latest_audit_artifact(settings, document_id)
    if audit is None:
        raise OcrConflictError("Document has no valid audit result.")
    if audit.input_artifact_id != original.id:
        raise OcrConflictError("Audit result does not reference the current original artifact.")
    if audit.content.detected_mime_type != original.mime_type:
        raise OcrConflictError("Audit result MIME type does not match the current original.")

    content = _extract_text(document_id, original, original_path, audit, ocr_adapter, pdf_renderer)
    artifact = TextArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_artifact_id=original.id,
        input_audit_artifact_id=audit.id,
        created_at=_now_utc_iso(),
        content=content,
    )
    save_text_artifact(settings, artifact)
    return artifact


def get_latest_text(settings: Settings, document_id: str) -> TextArtifact:
    """Return the newest text artifact after confirming the document exists."""
    if get_document_record(settings, document_id) is None:
        raise DocumentNotFoundError
    artifact = get_latest_text_artifact(settings, document_id)
    if artifact is None:
        raise TextArtifactNotFoundError
    return artifact


def _extract_text(
    document_id: str,
    original: OriginalArtifact,
    original_path: Path,
    audit: AuditArtifact,
    ocr_adapter: OcrAdapter,
    pdf_renderer: PdfRenderer,
) -> TextContent:
    try:
        if audit.content.document_kind == "pdf":
            return _extract_pdf(
                document_id,
                original,
                original_path,
                audit,
                ocr_adapter,
                pdf_renderer,
            )
        if audit.content.document_kind == "docx":
            return _extract_docx(document_id, original, original_path, audit)
        if audit.content.document_kind == "image":
            return _extract_image(document_id, original, original_path, audit, ocr_adapter)
    except ApiError:
        raise
    except Exception as exc:
        raise OcrProcessingError("Original artifact could not be processed.") from exc
    raise OcrProcessingError("Audit document kind is not supported by OCR v1.")


def _extract_pdf(
    document_id: str,
    original: OriginalArtifact,
    original_path: Path,
    audit: AuditArtifact,
    ocr_adapter: OcrAdapter,
    pdf_renderer: PdfRenderer,
) -> TextContent:
    reader = PdfReader(original_path)
    audit_pages = audit.content.pages
    if audit.content.page_count != len(reader.pages) or len(audit_pages) != len(reader.pages):
        raise OcrConflictError("PDF audit page list is inconsistent with the original.")

    pages: list[TextPageResult] = []
    # Per-page (page_number, layout rendering | None, canonical page text). ``None`` marks a page
    # whose layout was not reconstructed (OCR pages, or a text layer that failed layout mode).
    layout_entries: list[tuple[int, str | None, str]] = []
    # Per-page (page_number, semantic reading-order text | None, canonical page text). ``None``
    # marks a page whose pii_input_text could not be reconstructed (OCR pages, or a text layer
    # where fragment/column detection was not confident).
    pii_input_entries: list[tuple[int, str | None, str]] = []
    with TemporaryDirectory(prefix="ocr-", dir=_OCR_WORKSPACE_ROOT) as temporary_directory:
        output_dir = Path(temporary_directory)
        for page_number, (page, audit_page) in enumerate(
            zip(reader.pages, audit_pages, strict=True), start=1
        ):
            if audit_page.page_number != page_number:
                raise OcrConflictError("PDF audit page list is inconsistent.")
            if _page_needs_ocr(audit_page):
                # Empty and broken/encoded text layers are routed to OCR. When OCR is required but
                # its runtime is unavailable the adapter raises 503 — we never silently fall back
                # to a broken text layer.
                try:
                    image_path = pdf_renderer.render_page(
                        original_path, page_number, output_dir
                    )
                except Exception as exc:
                    raise OcrProcessingError("PDF page could not be rendered.") from exc
                text = ocr_adapter.extract_text(image_path)
                source = "paddleocr"
                layout_segment: str | None = None
                pii_input_segment: str | None = None
            else:
                # Canonical text is the unchanged default extraction — the offset-stable PII input.
                text = page.extract_text() or ""
                source = "pdf_text_layer"
                # Additive layout rendering via pypdf's layout mode (no new dependency). It never
                # feeds PII and never affects ``text``; on any failure the page degrades to "not
                # reconstructed" rather than breaking extraction.
                try:
                    layout_segment = page.extract_text(extraction_mode="layout") or None
                except Exception:
                    layout_segment = None
                # Additive, internal semantic reading-order reconstruction (PII-input v1). Never
                # feeds PII detection and never affects ``text``; returns None rather than raising
                # when fragment/column detection is not confident for this page.
                pii_input_segment = build_page_pii_input_text(page)
            pages.append(
                TextPageResult(
                    page_number=page_number,
                    source=source,
                    has_text_layer=source == "pdf_text_layer",
                    ocr_used=source == "paddleocr",
                    text=text,
                    text_char_count=len(text),
                )
            )
            layout_entries.append((page_number, layout_segment, text))
            pii_input_entries.append((page_number, pii_input_segment, text))

    used_text_layer = any(page.has_text_layer for page in pages)
    used_ocr = any(page.ocr_used for page in pages)
    source = "pdf_mixed" if used_text_layer and used_ocr else (
        "paddleocr" if used_ocr else "pdf_text_layer"
    )
    tool_versions = {"pypdf": version("pypdf")}
    if used_ocr:
        tool_versions["pdf2image"] = version("pdf2image")
        tool_versions.update(ocr_adapter.tool_versions())
    text = "\n\n".join(page.text for page in pages)
    layout_text_result = _combine_layout_segments(layout_entries)
    pii_input_text = _combine_pii_input_segments(pii_input_entries)
    flags = [
        flag
        for flag, used in (("pdf_mixed", source == "pdf_mixed"), ("ocr_used", used_ocr))
        if used
    ]
    return _text_content(
        document_id,
        original,
        audit,
        source,
        text,
        pages,
        tool_versions,
        flags,
        layout_text_result=layout_text_result,
        pii_input_text=pii_input_text,
    )


_PAGE_MARKER = "----- page {page_number} -----"


def _combine_layout_segments(entries: list[tuple[int, str | None, str]]) -> str | None:
    """Join per-page layout renderings into one review-oriented plain-text block.

    Text-layer pages contribute their layout-mode rendering; a page without one (OCR, or a failed
    layout extraction) is marked and falls back to its linear text. Pages are separated by a visible
    page marker. Returns ``None`` when no page produced a layout rendering (e.g. an all-OCR or image
    PDF), so the field stays absent rather than duplicating the canonical text.
    """
    if all(layout is None for _, layout, _ in entries):
        return None
    blocks: list[str] = []
    for page_number, layout, page_text in entries:
        if layout is not None:
            blocks.append(layout.rstrip("\n"))
        else:
            marker = f"[page {page_number}: layout not reconstructed]"
            blocks.append(f"{marker}\n{page_text}".rstrip("\n"))
    combined = blocks[0]
    for (page_number, _, _), block in zip(entries[1:], blocks[1:], strict=True):
        combined += f"\n\n{_PAGE_MARKER.format(page_number=page_number)}\n\n{block}"
    return combined or None


_PII_INPUT_PAGE_MARKER = "[PAGE {page_number}]"


def _combine_pii_input_segments(entries: list[tuple[int, str | None, str]]) -> str | None:
    """Join per-page semantic reading-order reconstructions into one internal text block.

    Text-layer pages contribute their block/table reconstruction; a page without one (OCR, or
    uncertain fragment/column detection) is marked and falls back to its linear text. Returns
    ``None`` when no page produced a reconstruction, so the field stays absent rather than
    duplicating the canonical text. Mirrors ``_combine_layout_segments`` with a distinct page
    marker and fallback wording so the two additive fields are never confused.
    """
    if all(segment is None for _, segment, _ in entries):
        return None
    blocks: list[str] = []
    for page_number, segment, page_text in entries:
        if segment is not None:
            blocks.append(segment.rstrip("\n"))
        else:
            marker = f"[page {page_number}: pii_input_text not reconstructed]"
            blocks.append(f"{marker}\n{page_text}".rstrip("\n"))
    combined = blocks[0]
    for (page_number, _, _), block in zip(entries[1:], blocks[1:], strict=True):
        combined += f"\n\n{_PII_INPUT_PAGE_MARKER.format(page_number=page_number)}\n\n{block}"
    return combined or None


def _page_needs_ocr(audit_page: AuditPageResult) -> bool:
    """Decide whether a PDF page must be OCR'd instead of using its text layer.

    Prefer the audit's per-page quality routing (``needs_ocr``): GOOD/LOW_CONFIDENCE keep the text
    layer, BROKEN/EMPTY go to OCR. Audit artifacts written before the quality gate have no decision
    recorded, so fall back to the original behavior: OCR only pages without any text layer.
    """
    if audit_page.needs_ocr is not None:
        return audit_page.needs_ocr
    return not audit_page.has_text_layer


def _extract_docx(
    document_id: str,
    original: OriginalArtifact,
    original_path: Path,
    audit: AuditArtifact,
) -> TextContent:
    document = DocxDocument(str(original_path))
    text = extract_docx_text(document)
    return _text_content(
        document_id,
        original,
        audit,
        "docx_text",
        text,
        [],
        {"python-docx": version("python-docx")},
        [],
    )


def _extract_image(
    document_id: str,
    original: OriginalArtifact,
    original_path: Path,
    audit: AuditArtifact,
    ocr_adapter: OcrAdapter,
) -> TextContent:
    text = ocr_adapter.extract_text(original_path)
    page = TextPageResult(
        page_number=1,
        source="paddleocr",
        has_text_layer=False,
        ocr_used=True,
        text=text,
        text_char_count=len(text),
    )
    return _text_content(
        document_id,
        original,
        audit,
        "paddleocr",
        text,
        [page],
        ocr_adapter.tool_versions(),
        ["ocr_used"],
    )


def _text_content(
    document_id: str,
    original: OriginalArtifact,
    audit: AuditArtifact,
    source: str,
    text: str,
    pages: list[TextPageResult],
    tool_versions: dict[str, str],
    flags: list[str],
    layout_text_result: str | None = None,
    pii_input_text: str | None = None,
) -> TextContent:
    return TextContent(
        document_id=document_id,
        input_artifact_id=original.id,
        input_audit_artifact_id=audit.id,
        source=source,
        text=text,
        text_char_count=len(text),
        pages=pages,
        tool_versions=tool_versions,
        flags=flags,
        layout_text_result=layout_text_result,
        pii_input_text=pii_input_text,
    )


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
