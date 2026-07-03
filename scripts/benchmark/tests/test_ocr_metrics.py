from __future__ import annotations

import pytest

from artifact_loader import (
    AuditPageSummary,
    AuditSummary,
    DocumentArtifacts,
    LocalDocument,
    OcrLineConfidenceSummary,
    QualityReportSummary,
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


def _quality_report(**overrides: object) -> QualityReportSummary:
    values: dict[str, object] = {
        "artifact_id": "q1",
        "created_at": "2026-07-01T10:00:00Z",
        "input_artifact_id": "o1",
        "input_audit_artifact_id": "a1",
        "input_text_artifact_id": "t1",
        "page_count": 2,
        "text_layer_pages": 1,
        "ocr_pages": 1,
        "mixed_source": True,
        "text_source": "pdf_mixed",
        "good_text_layer_pages": 1,
        "low_confidence_text_layer_pages": 0,
        "broken_text_layer_pages": 0,
        "empty_text_layer_pages": 1,
        "pages_needing_ocr": 1,
        "ocr_pages_with_confidence": 1,
        "ocr_lines_with_confidence": 2,
        "ocr_page_confidence_mean": 0.75,
        "ocr_page_confidence_min": 0.75,
        "ocr_page_confidence_max": 0.75,
        "final_char_count": 150,
        "final_word_count": 15,
        "pages_without_text": 0,
        "flags": ("pdf_mixed", "ocr_used"),
        "tool_versions": {},
    }
    values.update(overrides)
    return QualityReportSummary(**values)


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
    assert metrics.artifact_availability.quality_report == "missing"
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
    assert metrics.pages_without_text == 0


def test_ocr_confidence_is_aggregated_from_text_summary() -> None:
    audit = _audit([_page("EMPTY_TEXT_LAYER", True), _page("EMPTY_TEXT_LAYER", True, 2)])
    text = _text(
        [
            TextPageSummary(
                1,
                "paddleocr",
                False,
                True,
                50,
                5,
                0.8,
                (OcrLineConfidenceSummary(1, 0.8, 50),),
            ),
            TextPageSummary(
                2,
                "paddleocr",
                False,
                True,
                50,
                5,
                0.6,
                (OcrLineConfidenceSummary(1, 0.6, 50),),
            ),
        ],
        source="paddleocr",
    )
    artifacts = DocumentArtifacts(document=_DOC, audit=audit, text=text, pii=None)

    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)

    assert metrics.ocr_pages_with_confidence == 2
    assert metrics.ocr_lines_with_confidence == 2
    assert metrics.ocr_page_confidence_mean == pytest.approx(0.7)
    assert metrics.ocr_page_confidence_min == 0.6
    assert metrics.ocr_page_confidence_max == 0.8
    aggregate = aggregate_ocr_metrics([metrics])
    assert aggregate.total_ocr_pages_with_confidence == 2
    assert aggregate.total_ocr_lines_with_confidence == 2
    assert aggregate.ocr_page_confidence_mean == pytest.approx(0.7)
    assert aggregate.total_pages_without_text == 0


def test_lineage_matching_quality_report_is_preferred() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False), _page("EMPTY_TEXT_LAYER", True, 2)])
    text = _text(
        [
            TextPageSummary(1, "pdf_text_layer", True, False, 100, 10),
            TextPageSummary(2, "paddleocr", False, True, 50, 5),
        ],
        source="pdf_mixed",
    )
    quality_report = _quality_report()
    artifacts = DocumentArtifacts(
        document=_DOC,
        audit=audit,
        text=text,
        pii=None,
        quality_report=quality_report,
    )

    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)

    assert metrics.quality_report_used is True
    assert metrics.artifact_availability.quality_report == "present"
    assert metrics.ocr_pages_count == 1
    assert metrics.ocr_lines_with_confidence == 2
    assert metrics.ocr_page_confidence_mean == 0.75
    assert metrics.final_word_count == 15
    assert metrics.pages_without_text == 0


def test_stale_quality_report_falls_back_to_legacy_summaries() -> None:
    audit = _audit([_page("GOOD_TEXT_LAYER", False)])
    text = _text([TextPageSummary(1, "pdf_text_layer", True, False, 100, 10)])
    artifacts = DocumentArtifacts(
        document=_DOC,
        audit=audit,
        text=text,
        pii=None,
        quality_report=_quality_report(input_text_artifact_id="stale"),
    )

    metrics = compute_document_ocr_metrics("doc-1", "Report.pdf", artifacts, None)

    assert metrics.quality_report_used is False
    assert metrics.page_count == 1
    assert metrics.text_layer_pages_count == 1
    assert metrics.ocr_pages_count == 0


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
