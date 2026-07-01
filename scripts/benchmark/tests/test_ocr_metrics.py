from __future__ import annotations

from artifact_loader import (
    AuditPageSummary,
    AuditSummary,
    DocumentArtifacts,
    LocalDocument,
    TextPageSummary,
    TextSummary,
)
from document_matching import BenchmarkMetadataEntry
from ocr_metrics import aggregate_ocr_metrics, compute_document_ocr_metrics

_DOC = LocalDocument(
    document_id="doc-1",
    display_filename="Report.pdf",
    storage_filename="doc-1.pdf",
    mime_type="application/pdf",
    sha256="a" * 64,
    size_bytes=1000,
    created_at="2026-07-01T10:00:00Z",
    upload_exists=True,
    upload_size_bytes=1000,
)


def _page(status: str, needs_ocr: bool, page_number: int = 1) -> AuditPageSummary:
    return AuditPageSummary(
        page_number=page_number,
        text_char_count=100,
        has_text_layer=status != "EMPTY_TEXT_LAYER",
        text_quality_status=status,
        text_quality_score=90 if status == "GOOD_TEXT_LAYER" else 0,
        text_quality_reasons=(),
        recommended_text_source="ocr" if needs_ocr else "text_layer",
        needs_ocr=needs_ocr,
    )


def _audit(pages: list[AuditPageSummary], flags: tuple[str, ...] = ()) -> AuditSummary:
    return AuditSummary(
        artifact_id="a1",
        created_at="2026-07-01T10:00:00Z",
        document_kind="pdf",
        page_count=len(pages),
        has_text_layer=True,
        text_char_count=sum(p.text_char_count for p in pages),
        flags=flags,
        pages=tuple(pages),
    )


def _text(pages: list[TextPageSummary], source: str = "pdf_text_layer") -> TextSummary:
    return TextSummary(
        artifact_id="t1",
        created_at="2026-07-01T10:00:00Z",
        source=source,
        text_char_count=sum(p.text_char_count for p in pages),
        word_count=sum(p.word_count for p in pages),
        flags=(),
        pages=tuple(pages),
        tool_versions={},
    )


def test_direct_extraction_when_no_pages_need_ocr() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False)])
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=None, pii=None)
    benchmark_entry = BenchmarkMetadataEntry(
        filename="Report.pdf",
        file_type="pdf",
        size_bytes=1000,
        pages=1,
        text_quality_bucket="usable_text_layer",
        recommended_pipeline="DIRECT_TEXT_EXTRACTION",
        benchmark_role="baseline",
        page_quality=("usable",),
    )
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, benchmark_entry)
    assert metrics.actual_pipeline_category == "DIRECT_TEXT_EXTRACTION"
    assert metrics.routing_matches_expectation is True
    assert metrics.pages_good_text_layer == 1
    assert metrics.pages_needing_ocr == 0


def test_ocr_required_all_pages_when_every_page_needs_ocr() -> None:
    audit = _audit([_page("EMPTY_TEXT_LAYER", True), _page("BROKEN_TEXT_LAYER", True, 2)])
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=None, pii=None)
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)
    assert metrics.actual_pipeline_category == "OCR_REQUIRED_ALL_PAGES"
    assert metrics.pages_broken_text_layer == 1
    assert metrics.pages_empty_text_layer == 1
    assert metrics.pages_needing_ocr == 2
    assert metrics.routing_matches_expectation == "unknown"  # no benchmark entry


def test_mixed_when_some_but_not_all_pages_need_ocr() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False), _page("EMPTY_TEXT_LAYER", True, 2)])
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=None, pii=None)
    benchmark_entry = BenchmarkMetadataEntry(
        filename="Report.pdf",
        file_type="pdf",
        size_bytes=1000,
        pages=2,
        text_quality_bucket="usable_text_layer",
        recommended_pipeline="PAGEWISE_TEXT_LAYER_OR_OCR_FALLBACK",
        benchmark_role="mixed",
        page_quality=("usable", "none"),
    )
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, benchmark_entry)
    assert metrics.actual_pipeline_category == "MIXED_TEXT_LAYER_AND_OCR"
    assert metrics.routing_matches_expectation is True
    assert metrics.notes


def test_routing_mismatch_reported_as_false() -> None:
    audit = _audit([_page("BROKEN_TEXT_LAYER", True)])
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=None, pii=None)
    benchmark_entry = BenchmarkMetadataEntry(
        filename="Report.pdf",
        file_type="pdf",
        size_bytes=1000,
        pages=1,
        text_quality_bucket="broken_or_encoded_text_layer",
        recommended_pipeline="DIRECT_TEXT_EXTRACTION",
        benchmark_role="broken",
        page_quality=("broken",),
    )
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, benchmark_entry)
    assert metrics.routing_matches_expectation is False


def test_artifact_availability_reports_missing_text_and_pii() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False)])
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=None, pii=None)
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)
    assert metrics.artifact_availability.audit_result == "present"
    assert metrics.artifact_availability.text_result == "missing"
    assert metrics.artifact_availability.pii_result == "missing"


def test_ocr_and_text_layer_page_counts_from_text_summary() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False), _page("EMPTY_TEXT_LAYER", True, 2)])
    text = _text(
        [
            TextPageSummary(1, "pdf_text_layer", True, False, 100, 10),
            TextPageSummary(2, "paddleocr", False, True, 50, 5),
        ],
        source="pdf_mixed",
    )
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=text, pii=None)
    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)
    assert metrics.ocr_pages_count == 1
    assert metrics.text_layer_pages_count == 1
    assert metrics.final_char_count == 150
    assert metrics.final_word_count == 15


def test_aggregate_ocr_metrics_sums_page_counts_and_collects_mismatches() -> None:
    good = compute_document_ocr_metrics(
        "doc-1", "Good.pdf", DocumentArtifacts(document=_DOC, audit=_audit([_page("GOOD_TEXT_LAYER", False)]), text=None, pii=None), None
    )
    broken = compute_document_ocr_metrics(
        "doc-2",
        "Broken.pdf",
        DocumentArtifacts(document=_DOC, audit=_audit([_page("BROKEN_TEXT_LAYER", True)]), text=None, pii=None),
        BenchmarkMetadataEntry(
            filename="Broken.pdf",
            file_type="pdf",
            size_bytes=1,
            pages=1,
            text_quality_bucket="broken",
            recommended_pipeline="DIRECT_TEXT_EXTRACTION",
            benchmark_role="broken",
            page_quality=("broken",),
        ),
    )
    aggregate = aggregate_ocr_metrics([good, broken])
    assert aggregate.total_good_text_layer_pages == 1
    assert aggregate.total_broken_text_layer_pages == 1
    assert aggregate.total_needs_ocr_pages == 1
    assert aggregate.routing_mismatches == ("Broken.pdf",)
