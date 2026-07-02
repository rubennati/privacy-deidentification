"""OCR/text-layer quality metrics, computed only from local audit/text artifact summaries.

Never touches extracted text — everything here is counts, statuses, and flags already present
on ``AuditSummary``/``TextSummary`` (see ``artifact_loader.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from artifact_loader import AuditSummary, DocumentArtifacts, TextSummary
from document_matching import BenchmarkMetadataEntry

# The benchmark corpus distinguishes two "mixed" expected categories (one for a genuinely
# mixed text/no-text PDF, one for a text-layer-quality-gate-triggered fallback). The current
# implementation routes every PDF page independently on the audit's per-page `needs_ocr` verdict
# and does not otherwise distinguish *why* a page needs OCR, so both map to one actual category.
_MIXED_EXPECTED_CATEGORIES = frozenset(
    {"PAGEWISE_TEXT_LAYER_OR_OCR_FALLBACK", "TEXT_LAYER_QUALITY_GATE_THEN_OCR_FALLBACK"}
)
_ACTUAL_MIXED_CATEGORY = "MIXED_TEXT_LAYER_AND_OCR"
_ACTUAL_DIRECT_CATEGORY = "DIRECT_TEXT_EXTRACTION"
_ACTUAL_OCR_ALL_CATEGORY = "OCR_REQUIRED_ALL_PAGES"
_DIRECT_EXPECTED_CATEGORIES = frozenset({"DIRECT_TEXT_EXTRACTION", "DIRECT_TEXT_INPUT"})


@dataclass(frozen=True)
class ArtifactAvailability:
    """Presence status per artifact type, named after the backend's own ``artifact_type`` values
    (``audit_result``/``text_result``/``pii_result``) — deliberately not ``text``, which collides
    with the privacy guard's forbidden-field check even though this value is just a status
    string."""

    audit_result: str
    text_result: str
    pii_result: str


@dataclass(frozen=True)
class DocumentOcrMetrics:
    document_id: str
    display_filename: str
    artifact_availability: ArtifactAvailability
    page_count: int | None
    pages_good_text_layer: int
    pages_low_confidence_text_layer: int
    pages_broken_text_layer: int
    pages_empty_text_layer: int
    pages_needing_ocr: int
    pdf_broken_text_layer_flag: bool
    pdf_pages_need_ocr_flag: bool
    text_source: str | None
    final_char_count: int | None
    final_word_count: int | None
    ocr_pages_count: int | None
    text_layer_pages_count: int | None
    ocr_pages_with_confidence: int | None
    ocr_lines_with_confidence: int | None
    ocr_page_confidence_mean: float | None
    ocr_page_confidence_min: float | None
    ocr_page_confidence_max: float | None
    expected_pipeline_category: str | None
    actual_pipeline_category: str | None
    routing_matches_expectation: bool | str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class OcrAggregateMetrics:
    documents: tuple[DocumentOcrMetrics, ...]
    total_good_text_layer_pages: int
    total_low_confidence_text_layer_pages: int
    total_broken_text_layer_pages: int
    total_empty_text_layer_pages: int
    total_needs_ocr_pages: int
    total_ocr_pages_with_confidence: int
    total_ocr_lines_with_confidence: int
    ocr_page_confidence_mean: float | None
    ocr_page_confidence_min: float | None
    ocr_page_confidence_max: float | None
    routing_mismatches: tuple[str, ...]


def _artifact_status(present: bool, malformed_hint: bool) -> str:
    if malformed_hint:
        return "malformed"
    return "present" if present else "missing"


def compute_document_ocr_metrics(
    document_id: str,
    display_filename: str,
    artifacts: DocumentArtifacts,
    benchmark_entry: BenchmarkMetadataEntry | None,
) -> DocumentOcrMetrics:
    audit = artifacts.audit
    text = artifacts.text
    errors = artifacts.load_errors

    availability = ArtifactAvailability(
        audit_result=_artifact_status(audit is not None, any("audit" in err for err in errors)),
        text_result=_artifact_status(text is not None, any("text_result" in err for err in errors)),
        pii_result=_artifact_status(
            artifacts.pii is not None, any("pii_result" in err for err in errors)
        ),
    )

    good = low = broken = empty = needs_ocr = 0
    if audit is not None:
        for page in audit.pages:
            status = page.text_quality_status
            if status == "GOOD_TEXT_LAYER":
                good += 1
            elif status == "LOW_CONFIDENCE_TEXT_LAYER":
                low += 1
            elif status == "BROKEN_TEXT_LAYER":
                broken += 1
            elif status == "EMPTY_TEXT_LAYER":
                empty += 1
            if page.needs_ocr:
                needs_ocr += 1

    ocr_pages_count = text_layer_pages_count = None
    ocr_pages_with_confidence = ocr_lines_with_confidence = None
    page_confidences: list[float] = []
    if text is not None and text.pages:
        ocr_pages_count = sum(1 for page in text.pages if page.ocr_used)
        text_layer_pages_count = sum(1 for page in text.pages if not page.ocr_used)
        page_confidences = [
            page.ocr_confidence
            for page in text.pages
            if page.ocr_used and page.ocr_confidence is not None
        ]
        ocr_pages_with_confidence = len(page_confidences)
        ocr_lines_with_confidence = sum(
            len(page.ocr_line_confidences) for page in text.pages if page.ocr_used
        )

    actual_category, notes = _actual_pipeline_category(audit, text)
    expected_category = benchmark_entry.recommended_pipeline if benchmark_entry else None
    routing_match = _routing_matches(expected_category, actual_category)

    if audit is not None and audit.page_count is not None:
        page_count = audit.page_count
    elif text is not None and text.pages:
        page_count = len(text.pages)
    else:
        page_count = None

    return DocumentOcrMetrics(
        document_id=document_id,
        display_filename=display_filename,
        artifact_availability=availability,
        page_count=page_count,
        pages_good_text_layer=good,
        pages_low_confidence_text_layer=low,
        pages_broken_text_layer=broken,
        pages_empty_text_layer=empty,
        pages_needing_ocr=needs_ocr,
        pdf_broken_text_layer_flag=bool(audit and "pdf_broken_text_layer" in audit.flags),
        pdf_pages_need_ocr_flag=bool(audit and "pdf_pages_need_ocr" in audit.flags),
        text_source=text.source if text else None,
        final_char_count=text.text_char_count if text else None,
        final_word_count=text.word_count if text else None,
        ocr_pages_count=ocr_pages_count,
        text_layer_pages_count=text_layer_pages_count,
        ocr_pages_with_confidence=ocr_pages_with_confidence,
        ocr_lines_with_confidence=ocr_lines_with_confidence,
        ocr_page_confidence_mean=(
            sum(page_confidences) / len(page_confidences) if page_confidences else None
        ),
        ocr_page_confidence_min=min(page_confidences) if page_confidences else None,
        ocr_page_confidence_max=max(page_confidences) if page_confidences else None,
        expected_pipeline_category=expected_category,
        actual_pipeline_category=actual_category,
        routing_matches_expectation=routing_match,
        notes=tuple(notes),
    )


def _actual_pipeline_category(
    audit: AuditSummary | None, text: TextSummary | None
) -> tuple[str | None, list[str]]:
    if audit is None:
        return None, ["no audit artifact available to derive routing"]

    if audit.document_kind not in (None, "pdf"):
        return _ACTUAL_DIRECT_CATEGORY, []

    if not audit.pages:
        return None, ["audit has no per-page verdicts (pre-quality-gate audit or non-PDF)"]

    needs_ocr_flags = [bool(page.needs_ocr) for page in audit.pages]
    if not any(needs_ocr_flags):
        return _ACTUAL_DIRECT_CATEGORY, []
    if all(needs_ocr_flags):
        return _ACTUAL_OCR_ALL_CATEGORY, []
    notes = [
        "benchmark distinguishes PAGEWISE_TEXT_LAYER_OR_OCR_FALLBACK vs "
        "TEXT_LAYER_QUALITY_GATE_THEN_OCR_FALLBACK; current per-page needs_ocr routing "
        "unifies both as " + _ACTUAL_MIXED_CATEGORY
    ]
    return _ACTUAL_MIXED_CATEGORY, notes


def _routing_matches(expected: str | None, actual: str | None) -> bool | str:
    if expected is None or actual is None:
        return "unknown"
    if expected == actual:
        return True
    if actual == _ACTUAL_MIXED_CATEGORY and expected in _MIXED_EXPECTED_CATEGORIES:
        return True
    if actual == _ACTUAL_DIRECT_CATEGORY and expected in _DIRECT_EXPECTED_CATEGORIES:
        return True
    return False


def aggregate_ocr_metrics(per_document: list[DocumentOcrMetrics]) -> OcrAggregateMetrics:
    mismatches = tuple(
        doc.display_filename for doc in per_document if doc.routing_matches_expectation is False
    )
    page_confidence_weight = sum(doc.ocr_pages_with_confidence or 0 for doc in per_document)
    page_confidence_sum = sum(
        (doc.ocr_page_confidence_mean or 0.0) * (doc.ocr_pages_with_confidence or 0)
        for doc in per_document
    )
    page_confidence_mins = [
        doc.ocr_page_confidence_min
        for doc in per_document
        if doc.ocr_page_confidence_min is not None
    ]
    page_confidence_maxes = [
        doc.ocr_page_confidence_max
        for doc in per_document
        if doc.ocr_page_confidence_max is not None
    ]
    return OcrAggregateMetrics(
        documents=tuple(per_document),
        total_good_text_layer_pages=sum(doc.pages_good_text_layer for doc in per_document),
        total_low_confidence_text_layer_pages=sum(
            doc.pages_low_confidence_text_layer for doc in per_document
        ),
        total_broken_text_layer_pages=sum(doc.pages_broken_text_layer for doc in per_document),
        total_empty_text_layer_pages=sum(doc.pages_empty_text_layer for doc in per_document),
        total_needs_ocr_pages=sum(doc.pages_needing_ocr for doc in per_document),
        total_ocr_pages_with_confidence=page_confidence_weight,
        total_ocr_lines_with_confidence=sum(
            doc.ocr_lines_with_confidence or 0 for doc in per_document
        ),
        ocr_page_confidence_mean=(
            page_confidence_sum / page_confidence_weight if page_confidence_weight else None
        ),
        ocr_page_confidence_min=(min(page_confidence_mins) if page_confidence_mins else None),
        ocr_page_confidence_max=(max(page_confidence_maxes) if page_confidence_maxes else None),
        routing_mismatches=mismatches,
    )
