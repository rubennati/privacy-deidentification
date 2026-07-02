from __future__ import annotations

import json
from pathlib import Path

from artifact_loader import (
    DetectedEntity,
    OcrLineConfidenceSummary,
    QualityReportSummary,
    load_local_corpus,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _document_json(document_id: str, filename: str, storage_filename: str, size: int) -> dict:
    return {
        "id": document_id,
        "filename": filename,
        "size": size,
        "detected_mime_type": "application/pdf",
        "sha256": "a" * 64,
        "uploaded_at": "2026-07-01T10:00:00Z",
        "original_artifact": {"storage_filename": storage_filename},
    }


def _audit_artifact(artifact_id: str, document_id: str, created_at: str) -> dict:
    return {
        "id": artifact_id,
        "document_id": document_id,
        "artifact_type": "audit_result",
        "created_at": created_at,
        "content": {
            "document_kind": "pdf",
            "page_count": 1,
            "has_text_layer": True,
            "text_char_count": 100,
            "flags": ["pdf_has_text_layer"],
            "pages": [
                {
                    "page_number": 1,
                    "text_char_count": 100,
                    "has_text_layer": True,
                    "text_quality_status": "GOOD_TEXT_LAYER",
                    "text_quality_score": 90,
                    "text_quality_reasons": [],
                    "recommended_text_source": "text_layer",
                    "needs_ocr": False,
                }
            ],
        },
    }


def _quality_report_artifact(
    artifact_id: str, document_id: str, created_at: str
) -> dict:
    return {
        "id": artifact_id,
        "document_id": document_id,
        "artifact_type": "quality_report",
        "created_at": created_at,
        "input_artifact_id": "o1",
        "input_audit_artifact_id": "a1",
        "input_text_artifact_id": "t1",
        "content": {
            "page_count": 1,
            "text_layer_pages": 0,
            "ocr_pages": 1,
            "mixed_source": False,
            "text_source": "paddleocr",
            "good_text_layer_pages": 0,
            "low_confidence_text_layer_pages": 0,
            "broken_text_layer_pages": 0,
            "empty_text_layer_pages": 1,
            "pages_needing_ocr": 1,
            "ocr_pages_with_confidence": 1,
            "ocr_lines_with_confidence": 1,
            "ocr_page_confidence_mean": 0.85,
            "ocr_page_confidence_min": 0.85,
            "ocr_page_confidence_max": 0.85,
            "final_char_count": 20,
            "final_word_count": 3,
            "pages_without_text": 0,
            "flags": ["ocr_used"],
            "tool_versions": {"paddleocr": "test"},
        },
    }


def test_load_local_corpus_reads_document_and_artifacts(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    document_data_dir = tmp_path / "document-data"
    document_id = "d" * 32

    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Report.pdf", f"{document_id}.pdf", 12345),
    )
    (uploads_dir).mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{document_id}.pdf").write_bytes(b"synthetic-original-bytes")

    _write_json(
        document_data_dir / document_id / "artifacts" / "a1.json",
        _audit_artifact("a1", document_id, "2026-07-01T10:05:00Z"),
    )

    corpus = load_local_corpus(uploads_dir, document_data_dir)
    assert len(corpus) == 1
    entry = corpus[0]
    assert entry.document.document_id == document_id
    assert entry.document.display_filename == "Report.pdf"
    assert entry.document.upload_exists is True
    assert entry.audit is not None
    assert entry.audit.page_count == 1
    assert entry.text is None
    assert entry.pii is None
    assert entry.load_errors == ()


def test_load_local_corpus_picks_the_latest_artifact_by_created_at(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    document_id = "e" * 32
    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Report.pdf", f"{document_id}.pdf", 100),
    )
    older = _audit_artifact("old", document_id, "2026-07-01T10:00:00Z")
    older["content"]["page_count"] = 1
    newer = _audit_artifact("new", document_id, "2026-07-01T12:00:00Z")
    newer["content"]["page_count"] = 7
    _write_json(document_data_dir / document_id / "artifacts" / "old.json", older)
    _write_json(document_data_dir / document_id / "artifacts" / "new.json", newer)

    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)
    assert corpus[0].audit is not None
    assert corpus[0].audit.page_count == 7
    assert corpus[0].audit.artifact_id == "new"


def test_malformed_artifact_json_is_recorded_not_raised(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    document_id = "f" * 32
    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Report.pdf", f"{document_id}.pdf", 100),
    )
    artifacts_dir = document_data_dir / document_id / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "broken.json").write_text("{not valid json", encoding="utf-8")

    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)
    assert corpus[0].audit is None
    assert any("unreadable_or_invalid_json" in err for err in corpus[0].load_errors)


def test_document_without_document_json_is_skipped(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    (document_data_dir / "no-sidecar-dir").mkdir(parents=True, exist_ok=True)
    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)
    assert corpus == []


def test_detected_entity_has_no_raw_text_field() -> None:
    field_names = {f for f in DetectedEntity.__dataclass_fields__}
    assert "text" not in field_names
    assert "entity_text" not in field_names


def test_load_text_confidence_without_copying_raw_ocr_text(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    document_id = "7" * 32
    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Scan.pdf", f"{document_id}.pdf", 100),
    )
    _write_json(
        document_data_dir / document_id / "artifacts" / "text.json",
        {
            "id": "text1",
            "document_id": document_id,
            "artifact_type": "text_result",
            "created_at": "2026-07-01T10:02:00Z",
            "content": {
                "source": "paddleocr",
                "text": "raw recognized value",
                "readable_text": "raw recognized value",
                "text_char_count": 20,
                "pages": [
                    {
                        "page_number": 1,
                        "source": "paddleocr",
                        "has_text_layer": False,
                        "ocr_used": True,
                        "text": "raw recognized value",
                        "text_char_count": 20,
                        "ocr_confidence": 0.85,
                        "ocr_line_confidences": [
                            {"line_index": 1, "confidence": 0.85, "text_char_count": 20}
                        ],
                    }
                ],
            },
        },
    )
    _write_json(
        document_data_dir / document_id / "artifacts" / "quality.json",
        _quality_report_artifact("q1", document_id, "2026-07-01T10:03:00Z"),
    )

    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)

    assert corpus[0].text is not None
    page = corpus[0].text.pages[0]
    assert page.ocr_confidence == 0.85
    assert page.ocr_line_confidences == (OcrLineConfidenceSummary(1, 0.85, 20),)
    assert "text" not in page.__dataclass_fields__
    assert "text" not in OcrLineConfidenceSummary.__dataclass_fields__
    assert "readable_text" not in corpus[0].text.__dataclass_fields__
    quality_report = corpus[0].quality_report
    assert quality_report is not None
    assert quality_report.input_text_artifact_id == "t1"
    assert quality_report.ocr_page_confidence_mean == 0.85
    assert quality_report.final_word_count == 3
    forbidden_fields = {"text", "readable_text", "page_text", "ocr_text", "entity_text"}
    assert forbidden_fields.isdisjoint(QualityReportSummary.__dataclass_fields__)


def _pii_artifact_with_validation(artifact_id: str, document_id: str, created_at: str) -> dict:
    return {
        "id": artifact_id,
        "document_id": document_id,
        "artifact_type": "pii_result",
        "created_at": created_at,
        "content": {
            "language": "de",
            "score_threshold": 0.5,
            "text_char_count": 10,
            "configured_entity_types": ["EMAIL_ADDRESS"],
            "entities": [],
            "entity_counts": {},
            "flags": [],
            "validation": {
                "enabled": True,
                "kept": 2,
                "dropped": 1,
                "score_down": 1,
                "dropped_by_reason": {"STOPWORD_ONLY": 1},
                "score_down_by_reason": {"MISSING_REQUIRED_CONTEXT": 1},
            },
        },
    }


def test_load_local_corpus_parses_the_validation_summary(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    document_id = "9" * 32
    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Report.pdf", f"{document_id}.pdf", 100),
    )
    _write_json(
        document_data_dir / document_id / "artifacts" / "pii.json",
        _pii_artifact_with_validation("pii1", document_id, "2026-07-01T10:03:00Z"),
    )

    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)

    assert corpus[0].pii is not None
    validation = corpus[0].pii.validation
    assert validation is not None
    assert validation.enabled is True
    assert validation.kept == 2
    assert validation.dropped == 1
    assert validation.score_down == 1
    assert validation.dropped_by_reason == {"STOPWORD_ONLY": 1}
    assert validation.score_down_by_reason == {"MISSING_REQUIRED_CONTEXT": 1}


def test_pii_artifact_without_validation_block_parses_as_none(tmp_path: Path) -> None:
    document_data_dir = tmp_path / "document-data"
    document_id = "8" * 32
    _write_json(
        document_data_dir / document_id / "document.json",
        _document_json(document_id, "Report.pdf", f"{document_id}.pdf", 100),
    )
    legacy_artifact = _pii_artifact_with_validation("pii1", document_id, "2026-07-01T10:03:00Z")
    del legacy_artifact["content"]["validation"]
    _write_json(document_data_dir / document_id / "artifacts" / "pii.json", legacy_artifact)

    corpus = load_local_corpus(tmp_path / "uploads", document_data_dir)

    assert corpus[0].pii is not None
    assert corpus[0].pii.validation is None
