"""Tests for the GT proposal exporter. Synthetic artifacts only; asserts the proposal is
benchmark-schema compatible (round-trips through load_groundtruth) and strictly text-free.
"""

from __future__ import annotations

import json
from pathlib import Path

from artifact_loader import (
    DetectedEntity,
    DocumentArtifacts,
    LocalDocument,
    PiiSummary,
    TextPageSummary,
    TextSummary,
)
from build_groundtruth_proposal import build_proposal, main
from document_matching import load_groundtruth


def _ent(entity_type: str, page: int | None, start: int, end: int, score: float = 0.9) -> DetectedEntity:
    return DetectedEntity(
        entity_type=entity_type,
        page_number=page,
        start_offset=start,
        end_offset=end,
        page_start_offset=start if page is not None else None,
        page_end_offset=end if page is not None else None,
        recognizer="Rec",
        score=score,
    )


def _doc(
    filename: str | None,
    entities: list[DetectedEntity],
    *,
    document_id: str = "a" * 32,
    pages: int = 2,
    profile: str = "review-heavy",
    has_pii: bool = True,
) -> DocumentArtifacts:
    document = LocalDocument(
        document_id=document_id,
        display_filename=filename,
        storage_filename=filename,
        mime_type="application/pdf",
        sha256=None,
        size_bytes=None,
        created_at=None,
        upload_exists=True,
        upload_size_bytes=None,
    )
    text = TextSummary(
        artifact_id="t",
        created_at="",
        source="pdf_text_layer",
        text_char_count=0,
        word_count=0,
        flags=(),
        pages=tuple(
            TextPageSummary(
                page_number=i + 1,
                source="pdf_text_layer",
                has_text_layer=True,
                ocr_used=False,
                text_char_count=0,
                word_count=0,
            )
            for i in range(pages)
        ),
        tool_versions={},
    )
    pii = (
        PiiSummary(
            artifact_id="p",
            created_at="",
            language="de",
            score_threshold=0.5,
            text_char_count=0,
            configured_entity_types=("ADDRESS", "PERSON"),
            entities=tuple(entities),
            entity_counts={},
            flags=(),
            profile=profile,
        )
        if has_pii
        else None
    )
    return DocumentArtifacts(document=document, audit=None, text=text, pii=pii)


def test_proposal_uses_page_local_offsets_and_review_metadata() -> None:
    corpus = [_doc("A.pdf", [_ent("ADDRESS", 1, 100, 130)])]
    proposal = build_proposal(corpus)
    (doc,) = proposal["documents"]
    assert doc["filename"] == "A.pdf"
    assert doc["needs_review"] is True
    (entity,) = doc["entities"]
    assert entity["entity_type"] == "ADDRESS"
    assert (entity["page"], entity["start"], entity["end"]) == (1, 100, 130)
    assert entity["review_status"] == "proposed"
    assert doc["totals"] == {"entity_count": 1, "by_type": {"ADDRESS": 1}}


def test_non_paged_entity_uses_global_offsets_and_null_page() -> None:
    corpus = [_doc("D.docx", [_ent("PERSON", None, 5, 20)])]
    (doc,) = build_proposal(corpus)["documents"]
    (entity,) = doc["entities"]
    assert entity["page"] is None
    assert (entity["start"], entity["end"]) == (5, 20)


def test_min_score_filters_low_confidence_detections() -> None:
    corpus = [_doc("A.pdf", [_ent("ADDRESS", 1, 0, 10, score=0.9), _ent("PERSON", 1, 20, 30, score=0.4)])]
    (doc,) = build_proposal(corpus, min_score=0.5)["documents"]
    assert [e["entity_type"] for e in doc["entities"]] == ["ADDRESS"]


def test_filenames_filter_and_skips_docs_without_pii_or_name() -> None:
    corpus = [
        _doc("A.pdf", [_ent("ADDRESS", 1, 0, 10)]),
        _doc("B.pdf", [_ent("PERSON", 1, 0, 10)]),
        _doc("C.pdf", [], has_pii=False),
        _doc(None, [_ent("ADDRESS", 1, 0, 10)]),
    ]
    proposal = build_proposal(corpus, filenames=["A.pdf", "C.pdf"])
    assert [d["filename"] for d in proposal["documents"]] == ["A.pdf"]


def test_proposal_round_trips_through_load_groundtruth(tmp_path: Path) -> None:
    corpus = [_doc("A.pdf", [_ent("ADDRESS", 1, 100, 130), _ent("PERSON", 2, 5, 25)])]
    out = tmp_path / "proposal.json"
    rc = main(
        [
            "--document-data-dir", str(tmp_path),  # unused: we assert build_proposal output directly
            "--out", str(out),
        ]
    )
    # main() loads from an (empty) dir, so write the real proposal ourselves for the round-trip.
    out.write_text(json.dumps(build_proposal(corpus)), encoding="utf-8")
    assert rc == 0

    loaded = load_groundtruth(out)
    (gt_doc,) = loaded
    assert gt_doc.filename == "A.pdf"
    anchors = sorted((e.entity_type, e.page, e.start, e.end) for e in gt_doc.entities)
    assert anchors == [("ADDRESS", 1, 100, 130), ("PERSON", 2, 5, 25)]
    assert gt_doc.total_entity_count == 2


def test_proposal_is_text_free() -> None:
    # The loader carries no text, so the proposal cannot contain any; guard it explicitly.
    marker = "Max Mustermann"
    corpus = [_doc("A.pdf", [_ent("PERSON", 1, 0, len(marker))])]
    serialized = json.dumps(build_proposal(corpus))
    assert marker not in serialized
    allowed_entity_keys = {
        "entity_type", "page", "start", "end", "review_status", "detection_source", "score",
    }
    for doc in build_proposal(corpus)["documents"]:
        for entity in doc["entities"]:
            assert set(entity) <= allowed_entity_keys
