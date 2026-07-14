"""Tests for the gold-GT harvester. Synthetic snapshots only; asserts status filtering, global->
page-local offset mapping, manual-addition handling, benchmark-schema round-trip, and text-freeness.
"""

from __future__ import annotations

import json
from pathlib import Path

from document_matching import load_groundtruth
from harvest_groundtruth import (
    _page_bases,
    _to_page_local,
    build_groundtruth,
    harvest_document,
    harvest_feedback_anchors,
)


def _occ(entity_type: str, raw_start: int, raw_end: int, status: str = "accepted") -> dict:
    return {
        "occurrence_id": "c" * 32,
        "entity_type": entity_type,
        "raw_start": raw_start,
        "raw_end": raw_end,
        "review_status": status,
        "review_decision": None,
    }


def _snapshot(occurrences: list[dict], *, manual: list[dict] | None = None, text_id: str = "b" * 32) -> dict:
    return {
        "id": "a" * 32,
        "artifact_type": "pii_review_result",
        "created_at": "2026-07-13T10:00:00Z",
        "input_text_artifact_id": text_id,
        "content": {"occurrences": occurrences, "manual_additions": manual or []},
    }


def _text(page_char_counts: list[int], *, artifact_id: str = "b" * 32) -> dict:
    return {
        "id": artifact_id,
        "artifact_type": "text_result",
        "content": {
            "pages": [
                {"page_number": i + 1, "text_char_count": c} for i, c in enumerate(page_char_counts)
            ]
        },
    }


# --- Offset mapping ------------------------------------------------------------------------------


def test_page_bases_use_two_char_separator() -> None:
    assert _page_bases([30, 40]) == [(1, 0, 30), (2, 32, 40)]


def test_to_page_local_maps_and_rejects_out_of_range_or_cross_page() -> None:
    bases = _page_bases([30, 40])
    assert _to_page_local(5, 20, bases) == (1, 5, 20)  # page 1
    assert _to_page_local(35, 45, bases) == (2, 3, 13)  # page 2 (base 32)
    assert _to_page_local(28, 35, bases) is None  # crosses the page boundary
    assert _to_page_local(200, 210, bases) is None  # out of range


# --- Status filtering ----------------------------------------------------------------------------


def test_accepted_and_kept_are_harvested_rejected_is_excluded() -> None:
    snapshot = _snapshot(
        [
            _occ("ADDRESS", 0, 10, "accepted"),
            _occ("PERSON", 12, 20, "kept"),
            _occ("URL", 22, 30, "rejected"),  # a false positive the reviewer removed
        ]
    )
    anchors, stats = harvest_document(snapshot, _text([40]))
    types = sorted(a["entity_type"] for a in anchors)
    assert types == ["ADDRESS", "PERSON"]
    assert stats["confirmed"] == 2
    assert stats["rejected"] == 1
    assert all(a["origin"] == "detected" for a in anchors)


def test_occurrence_offsets_out_of_text_are_counted_unmapped() -> None:
    snapshot = _snapshot([_occ("ADDRESS", 500, 520, "accepted")])
    anchors, stats = harvest_document(snapshot, _text([40]))
    assert anchors == []
    assert stats["unmapped"] == 1


# --- Manual additions ----------------------------------------------------------------------------


def test_manual_addition_accepted_and_mapped_is_included() -> None:
    manual = [
        {
            "entity_type": "BIRTH_DATE",
            "raw_start": 5,
            "raw_end": 15,
            "raw_projection_status": "exact",
            "review_status": "accepted",
            "artifact_currency": "current",
        }
    ]
    anchors, stats = harvest_document(_snapshot([], manual=manual), _text([40]))
    (anchor,) = anchors
    assert anchor["entity_type"] == "BIRTH_DATE"
    assert anchor["origin"] == "manual"
    assert (anchor["page"], anchor["start"], anchor["end"]) == (1, 5, 15)
    assert stats["manual_confirmed"] == 1


def test_manual_addition_stale_unmapped_or_rejected_is_skipped() -> None:
    manual = [
        {"entity_type": "PERSON", "raw_start": 5, "raw_end": 15, "raw_projection_status": "exact",
         "review_status": "accepted", "artifact_currency": "stale"},
        {"entity_type": "PERSON", "raw_start": None, "raw_end": None,
         "raw_projection_status": "unmapped", "review_status": "accepted"},
        {"entity_type": "PERSON", "raw_start": 5, "raw_end": 15, "raw_projection_status": "exact",
         "review_status": "rejected"},
    ]
    anchors, stats = harvest_document(_snapshot([], manual=manual), _text([40]))
    assert anchors == []
    assert stats["manual_skipped"] == 3


# --- build_groundtruth over an on-disk store -----------------------------------------------------


def _write_document(store: Path, document_id: str, filename: str, snapshot: dict, text: dict) -> None:
    doc_dir = store / document_id
    (doc_dir / "artifacts").mkdir(parents=True)
    (doc_dir / "document.json").write_text(json.dumps({"id": document_id, "filename": filename}))
    (doc_dir / "artifacts" / f"{snapshot['id']}.json").write_text(json.dumps(snapshot))
    (doc_dir / "artifacts" / f"{text['id']}.json").write_text(json.dumps(text))


def test_build_groundtruth_round_trips_through_load_groundtruth(tmp_path: Path) -> None:
    store = tmp_path / "document-store"
    _write_document(
        store, "a" * 32, "A.pdf",
        _snapshot([_occ("ADDRESS", 0, 10, "accepted"), _occ("URL", 12, 20, "rejected")]),
        _text([40]),
    )
    gold = build_groundtruth(store)
    out = tmp_path / "gold.json"
    out.write_text(json.dumps(gold))

    (gt_doc,) = load_groundtruth(out)
    assert gt_doc.filename == "A.pdf"
    anchors = [(e.entity_type, e.page, e.start, e.end) for e in gt_doc.entities]
    assert anchors == [("ADDRESS", 1, 0, 10)]  # URL false positive excluded
    assert gt_doc.total_entity_count == 1


def test_build_groundtruth_filters_and_reports_docs_without_review(tmp_path: Path) -> None:
    store = tmp_path / "document-store"
    _write_document(store, "a" * 32, "A.pdf", _snapshot([_occ("ADDRESS", 0, 10)]), _text([40]))
    # A document with no review snapshot at all.
    unreviewed = store / ("d" * 32)
    (unreviewed / "artifacts").mkdir(parents=True)
    (unreviewed / "document.json").write_text(json.dumps({"id": "d" * 32, "filename": "B.pdf"}))

    gold = build_groundtruth(store)
    assert [d["filename"] for d in gold["documents"]] == ["A.pdf"]
    assert gold["skipped_without_review"] == ["B.pdf"]

    filtered = build_groundtruth(store, filenames=["B.pdf"])
    assert filtered["documents"] == []


# --- Dev-feedback fold-in: rescue "correct" verdicts as confirmed anchors ------------------------


def _fb(entity_type: str, start: int, end: int, verdict: str, issue: str, at: str = "t1") -> dict:
    return {
        "recorded_at": at,
        "entity": {"type": entity_type, "start": start, "end": end, "recognizer": "Rec"},
        "feedback": {"verdict": verdict, "issue_type": issue},
    }


def test_feedback_correct_becomes_a_confirmed_anchor() -> None:
    records = [
        _fb("PERSON", 0, 10, "positive", "correct"),
        _fb("ADDRESS", 12, 20, "issue", "span_too_long_right"),  # a problem, not a truth -> skip
    ]
    anchors, stats = harvest_feedback_anchors(records, _text([40]), covered=set())
    assert [a["entity_type"] for a in anchors] == ["PERSON"]
    assert anchors[0]["origin"] == "feedback"
    assert (anchors[0]["page"], anchors[0]["start"], anchors[0]["end"]) == (1, 0, 10)
    assert stats["feedback_confirmed"] == 1


def test_feedback_latest_verdict_wins_and_binding_covers() -> None:
    # Same entity: first correct, later revised to an issue -> not harvested (latest wins).
    revised = [
        _fb("PERSON", 0, 10, "positive", "correct", at="t1"),
        _fb("PERSON", 0, 10, "issue", "wrong_type", at="t2"),
    ]
    anchors, _ = harvest_feedback_anchors(revised, _text([40]), covered=set())
    assert anchors == []
    # And an entity already taken by the binding channel is not double-added.
    covered = {("PERSON", 0, 10)}
    anchors2, stats2 = harvest_feedback_anchors(
        [_fb("PERSON", 0, 10, "positive", "correct")], _text([40]), covered=covered
    )
    assert anchors2 == [] and stats2["feedback_duplicate"] == 1


def test_build_groundtruth_harvests_a_feedback_only_document(tmp_path: Path) -> None:
    store = tmp_path / "document-store"
    doc_dir = store / ("a" * 32)
    (doc_dir / "artifacts").mkdir(parents=True)
    (doc_dir / "feedback").mkdir(parents=True)
    (doc_dir / "document.json").write_text(json.dumps({"id": "a" * 32, "filename": "A.pdf"}))
    # A text_result artifact (no review snapshot at all) + a dev-feedback log.
    text = _text([40])
    text["artifact_type"] = "text_result"
    text["created_at"] = "2026-07-13T10:00:00Z"
    (doc_dir / "artifacts" / f"{text['id']}.json").write_text(json.dumps(text))
    (doc_dir / "feedback" / "pii_feedback.jsonl").write_text(
        json.dumps(_fb("PERSON", 0, 14, "positive", "correct")) + "\n"
    )

    gold = build_groundtruth(store)
    (doc,) = gold["documents"]
    assert doc["filename"] == "A.pdf"
    assert doc["review_snapshot_id"] is None
    assert doc["harvest_stats"]["feedback_confirmed"] == 1
    assert doc["totals"]["entity_count"] == 1


def test_harvested_gold_is_text_free() -> None:
    marker = "Max Mustermann"
    snapshot = _snapshot([_occ("PERSON", 0, len(marker), "kept")])
    anchors, _ = harvest_document(snapshot, _text([40]))
    assert marker not in json.dumps(anchors)
    allowed = {"entity_type", "page", "start", "end", "origin", "review_status"}
    assert all(set(a) <= allowed for a in anchors)
