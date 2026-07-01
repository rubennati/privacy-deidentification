from __future__ import annotations

import json
from pathlib import Path

from artifact_loader import DetectedEntity, load_local_corpus


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
