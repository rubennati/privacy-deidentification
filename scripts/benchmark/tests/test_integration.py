"""End-to-end tests using only synthetic, fabricated data (no real documents).

These specifically guard the privacy requirement: even though a real ``pii_result`` artifact
stores raw detected text (``PiiEntity.text`` in the backend schema) and a real ``text_result``
artifact stores full page text, neither the JSON nor the markdown report may ever contain that
content — only counts, types, and offsets.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from privacy_guard import assert_report_is_safe, assert_text_is_safe
from private_benchmark import _write_profile_csv, run
from report_builder import render_markdown

_SECRET_EMAIL = "secret.person@example.com"
_SECRET_MASKED_VALUE = "sec***om"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_synthetic_corpus(tmp_path: Path) -> SimpleNamespace:
    uploads_dir = tmp_path / "uploads"
    document_data_dir = tmp_path / "document-data"
    benched_id = "1" * 32
    missing_artifacts_id = "2" * 32

    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{benched_id}.pdf").write_bytes(b"synthetic-pdf-bytes")

    _write_json(
        document_data_dir / benched_id / "document.json",
        {
            "id": benched_id,
            "filename": "Synthetic_Report.pdf",
            "size": 20,
            "detected_mime_type": "application/pdf",
            "sha256": "a" * 64,
            "uploaded_at": "2026-07-01T10:00:00Z",
            "original_artifact": {"storage_filename": f"{benched_id}.pdf"},
        },
    )
    _write_json(
        document_data_dir / benched_id / "artifacts" / "audit.json",
        {
            "id": "aud1",
            "document_id": benched_id,
            "artifact_type": "audit_result",
            "created_at": "2026-07-01T10:01:00Z",
            "content": {
                "document_kind": "pdf",
                "page_count": 1,
                "has_text_layer": True,
                "text_char_count": 50,
                "flags": ["pdf_has_text_layer"],
                "pages": [
                    {
                        "page_number": 1,
                        "text_char_count": 50,
                        "has_text_layer": True,
                        "text_quality_status": "GOOD_TEXT_LAYER",
                        "text_quality_score": 90,
                        "text_quality_reasons": [],
                        "recommended_text_source": "text_layer",
                        "needs_ocr": False,
                    }
                ],
            },
        },
    )
    _write_json(
        document_data_dir / benched_id / "artifacts" / "text.json",
        {
            "id": "txt1",
            "document_id": benched_id,
            "artifact_type": "text_result",
            "created_at": "2026-07-01T10:02:00Z",
            "content": {
                "source": "pdf_text_layer",
                "readable_text": f"Readable contact: {_SECRET_EMAIL}",
                "text_char_count": 50,
                "flags": [],
                "pages": [
                    {
                        "page_number": 1,
                        "source": "pdf_text_layer",
                        "has_text_layer": True,
                        "ocr_used": False,
                        "text_char_count": 50,
                        # A real text_result artifact stores full page text. This must never
                        # reach a report.
                        "text": f"Kontakt: {_SECRET_EMAIL} IBAN AT611904300234573201",
                    }
                ],
                "tool_versions": {},
            },
        },
    )
    _write_json(
        document_data_dir / benched_id / "artifacts" / "quality.json",
        {
            "id": "quality1",
            "document_id": benched_id,
            "artifact_type": "quality_report",
            "created_at": "2026-07-01T10:02:30Z",
            "input_artifact_id": "original1",
            "input_audit_artifact_id": "aud1",
            "input_text_artifact_id": "txt1",
            "content": {
                "page_count": 1,
                "text_layer_pages": 1,
                "ocr_pages": 0,
                "mixed_source": False,
                "text_source": "pdf_text_layer",
                "good_text_layer_pages": 1,
                "low_confidence_text_layer_pages": 0,
                "broken_text_layer_pages": 0,
                "empty_text_layer_pages": 0,
                "pages_needing_ocr": 0,
                "ocr_pages_with_confidence": 0,
                "ocr_lines_with_confidence": 0,
                "ocr_page_confidence_mean": None,
                "ocr_page_confidence_min": None,
                "ocr_page_confidence_max": None,
                "final_char_count": 50,
                "final_word_count": 4,
                "pages_without_text": 0,
                "flags": [],
                "tool_versions": {},
            },
        },
    )
    _write_json(
        document_data_dir / benched_id / "artifacts" / "pii.json",
        {
            "id": "pii1",
            "document_id": benched_id,
            "artifact_type": "pii_result",
            "created_at": "2026-07-01T10:03:00Z",
            "content": {
                "profile": "structured-only",
                "engine_settings": {"pii_profile": "structured-only"},
                "language": "de",
                "score_threshold": 0.5,
                "text_char_count": 50,
                "configured_entity_types": ["EMAIL_ADDRESS"],
                "entities": [
                    {
                        "id": "e1",
                        "entity_type": "EMAIL_ADDRESS",
                        "page_number": 1,
                        "start_offset": 9,
                        "end_offset": 35,
                        "page_start_offset": 9,
                        "page_end_offset": 35,
                        "recognizer": "TestRecognizer",
                        "score": 0.9,
                        # Same leak risk as above: a real PiiEntity always has a raw `text` field.
                        "text": _SECRET_EMAIL,
                    }
                ],
                "entity_counts": {"EMAIL_ADDRESS": 1},
                "flags": [],
                "validation": {
                    "enabled": True,
                    "kept": 1,
                    "dropped": 1,
                    "score_down": 0,
                    "dropped_by_reason": {"STOPWORD_ONLY": 1},
                    "score_down_by_reason": {},
                },
            },
        },
    )

    # Second document has metadata but no artifacts/ directory at all -> missing-artifact report.
    _write_json(
        document_data_dir / missing_artifacts_id / "document.json",
        {
            "id": missing_artifacts_id,
            "filename": "No_Artifacts_Yet.pdf",
            "size": 5,
            "detected_mime_type": "application/pdf",
            "sha256": "b" * 64,
            "uploaded_at": "2026-07-01T10:00:00Z",
            "original_artifact": {"storage_filename": f"{missing_artifacts_id}.pdf"},
        },
    )

    metadata_path = tmp_path / "ocr_pii_benchmark_metadata.json"
    _write_json(
        metadata_path,
        {
            "documents": [
                {
                    "filename": "Synthetic_Report.pdf",
                    "file_type": "pdf",
                    "size_bytes": 20,
                    "pages": 1,
                    "text_quality_bucket": "usable_text_layer",
                    "recommended_pipeline": "DIRECT_TEXT_EXTRACTION",
                    "benchmark_role": "synthetic_baseline",
                    "page_quality": ["usable_text_layer"],
                }
            ]
        },
    )

    groundtruth_path = tmp_path / "ocr_pii_benchmark_pii_groundtruth.json"
    _write_json(
        groundtruth_path,
        {
            "documents": [
                {
                    "filename": "Synthetic_Report.pdf",
                    "pages_count": 1,
                    "file_size": 20,
                    "entities": [
                        {
                            "entity_type": "EMAIL",
                            "page": 1,
                            "start": 9,
                            "end": 35,
                            "masked_value": _SECRET_MASKED_VALUE,
                            "source": "regex",
                        }
                    ],
                    "totals": {"entity_count": 1, "by_type": {"EMAIL": 1}},
                }
            ]
        },
    )

    return SimpleNamespace(
        uploads_dir=uploads_dir,
        document_data_dir=document_data_dir,
        metadata=metadata_path,
        groundtruth=groundtruth_path,
        no_pii=False,
        no_ocr=False,
    )


def test_end_to_end_report_matches_and_scores(tmp_path: Path) -> None:
    args = _build_synthetic_corpus(tmp_path)
    report = run(args)

    assert report["document_count"] == 2
    assert len(report["corpus_coverage"]["matched_documents"]) == 1
    assert report["corpus_coverage"]["matched_documents"][0]["match_basis"] == "exact_filename"

    missing = report["missing_or_unsupported"]["documents_missing_artifacts"]
    assert len(missing) == 1
    assert missing[0]["missing"] == ["audit_result", "text_result", "pii_result"]

    pii_global = report["pii_benchmark"]["global"]
    assert pii_global["total_tp"] == 1
    assert pii_global["total_fp"] == 0
    assert pii_global["total_fn"] == 0

    validation = report["pii_benchmark"]["validation"]
    assert validation["documents_considered"] == 1
    assert validation["total_kept"] == 1
    assert validation["total_dropped"] == 1
    assert validation["dropped_by_reason"] == {"STOPWORD_ONLY": 1}
    profiles = report["pii_benchmark"]["by_profile"]
    assert list(profiles) == [
        "structured-only",
        "insurance-at-de",
        "broad-review",
        "review-heavy",
    ]
    assert profiles["structured-only"]["documents_with_artifact"] == 1
    assert profiles["structured-only"]["global"]["total_tp"] == 1
    assert profiles["insurance-at-de"]["documents_with_artifact"] == 0
    assert profiles["insurance-at-de"]["global"]["total_tp"] == 0
    assert report["documents"][0]["ocr_text_metrics"]["quality_report_used"] is True


def test_end_to_end_report_json_contains_no_raw_or_masked_values(tmp_path: Path) -> None:
    args = _build_synthetic_corpus(tmp_path)
    report = run(args)

    assert_report_is_safe(report)  # must not raise

    serialized = json.dumps(report)
    assert _SECRET_EMAIL not in serialized
    assert _SECRET_MASKED_VALUE not in serialized
    assert "Readable contact" not in serialized
    assert "readable_text" not in serialized
    assert "AT611904300234573201" not in serialized


def test_end_to_end_markdown_report_contains_no_raw_or_masked_values(tmp_path: Path) -> None:
    args = _build_synthetic_corpus(tmp_path)
    report = run(args)
    markdown = render_markdown(report)

    assert_text_is_safe(markdown)  # must not raise

    assert _SECRET_EMAIL not in markdown
    assert _SECRET_MASKED_VALUE not in markdown
    assert "Readable contact" not in markdown
    assert "AT611904300234573201" not in markdown
    assert "# Private OCR/PII Benchmark Report" in markdown
    assert "### Per-profile comparison (Benchmark L9)" in markdown
    assert "| structured-only | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 | 1.0 |" in markdown
    assert "| insurance-at-de | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 |" in markdown


def test_profile_csv_contains_all_profiles_without_private_values(tmp_path: Path) -> None:
    report = run(_build_synthetic_corpus(tmp_path))
    csv_path = tmp_path / "profiles.csv"
    _write_profile_csv(csv_path, report)

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "structured-only,1,1,1,1,1,0,0,1.0,1.0,1.0" in csv_text
    assert "insurance-at-de,0,0,0,0,0,0,0,0.0,0.0,0.0" in csv_text
    assert _SECRET_EMAIL not in csv_text
    assert _SECRET_MASKED_VALUE not in csv_text
