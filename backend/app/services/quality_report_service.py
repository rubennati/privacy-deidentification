"""Build the metrics-only OCR/Text L7 quality report from immutable inputs."""

from __future__ import annotations

from collections import Counter
from uuid import uuid4

from app.schemas import (
    AuditArtifact,
    OriginalArtifact,
    QualityReportArtifact,
    QualityReportContent,
    TextArtifact,
)


def build_quality_report(
    original: OriginalArtifact,
    audit: AuditArtifact,
    text: TextArtifact,
    created_at: str,
) -> QualityReportArtifact:
    """Aggregate counts and confidence without copying page text or entity values."""
    pages = text.content.pages
    text_layer_pages = sum(page.has_text_layer for page in pages)
    ocr_pages = sum(page.ocr_used for page in pages)
    quality_counts = Counter(
        page.text_quality_status
        for page in audit.content.pages
        if page.text_quality_status is not None
    )
    page_confidences = [
        page.ocr_confidence
        for page in pages
        if page.ocr_used and page.ocr_confidence is not None
    ]
    pages_without_text = sum(page.text_char_count == 0 for page in pages)
    flags = list(text.content.flags)
    if pages_without_text:
        flags.append("pages_without_text")

    content = QualityReportContent(
        document_id=text.document_id,
        input_artifact_id=original.id,
        input_audit_artifact_id=audit.id,
        input_text_artifact_id=text.id,
        page_count=len(pages),
        text_layer_pages=text_layer_pages,
        ocr_pages=ocr_pages,
        mixed_source=text_layer_pages > 0 and ocr_pages > 0,
        text_source=text.content.source,
        good_text_layer_pages=quality_counts["GOOD_TEXT_LAYER"],
        low_confidence_text_layer_pages=quality_counts["LOW_CONFIDENCE_TEXT_LAYER"],
        broken_text_layer_pages=quality_counts["BROKEN_TEXT_LAYER"],
        empty_text_layer_pages=quality_counts["EMPTY_TEXT_LAYER"],
        pages_needing_ocr=sum(page.needs_ocr is True for page in audit.content.pages),
        ocr_pages_with_confidence=len(page_confidences),
        ocr_lines_with_confidence=sum(
            len(page.ocr_line_confidences) for page in pages if page.ocr_used
        ),
        ocr_page_confidence_mean=(
            sum(page_confidences) / len(page_confidences) if page_confidences else None
        ),
        ocr_page_confidence_min=min(page_confidences) if page_confidences else None,
        ocr_page_confidence_max=max(page_confidences) if page_confidences else None,
        final_char_count=text.content.text_char_count,
        final_word_count=len(text.content.text.split()),
        pages_without_text=pages_without_text,
        flags=flags,
        tool_versions=dict(text.content.tool_versions),
    )
    return QualityReportArtifact(
        id=uuid4().hex,
        document_id=text.document_id,
        input_artifact_id=original.id,
        input_audit_artifact_id=audit.id,
        input_text_artifact_id=text.id,
        created_at=created_at,
        content=content,
    )
