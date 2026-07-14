"""Tests for the dev-feedback analyzer. Synthetic records only; asserts aggregation, latest-wins
revision handling (tolerant of reviewer mistakes), and text-freeness.
"""

from __future__ import annotations

import json

from analyze_feedback import build_feedback_report


def _fb(
    entity_type: str,
    start: int,
    verdict: str,
    issue: str,
    *,
    recognizer: str = "Rec",
    recorded_at: str = "2026-07-13T10:00:00Z",
    comment: str = "",
    document_id: str = "d1",
) -> dict:
    return {
        "document_id": document_id,
        "recorded_at": recorded_at,
        "entity": {"type": entity_type, "start": start, "end": start + 5, "recognizer": recognizer},
        "feedback": {"verdict": verdict, "issue_type": issue, "comment": comment},
    }


def test_aggregates_verdicts_and_sorts_issue_types() -> None:
    records = [
        _fb("ADDRESS", 0, "positive", "correct"),
        _fb("PERSON", 10, "positive", "correct"),
        _fb("ADDRESS", 20, "issue", "span_too_long_right"),
        _fb("EMAIL_ADDRESS", 30, "issue", "span_too_long_right"),
        _fb("URL", 40, "issue", "overlap_conflict"),
    ]
    report = build_feedback_report(records)
    assert report["entities_with_feedback"] == 5
    assert report["verdicts"] == {"positive": 2, "issue": 3}
    # Most frequent problem first.
    assert report["issue_types_sorted"][0] == {"issue_type": "span_too_long_right", "count": 2}
    assert {"issue_type": "overlap_conflict", "count": 1} in report["issue_types_sorted"]
    assert "correct" not in [i["issue_type"] for i in report["issue_types_sorted"]]


def test_latest_verdict_per_entity_wins_and_flags_revision() -> None:
    # Same entity reviewed twice: first an issue, then corrected to positive. Latest wins; the
    # change is surfaced as a revision to re-check (a reviewer slip is expected, not punished).
    records = [
        _fb("ADDRESS", 0, "issue", "span_too_long_right", recorded_at="2026-07-13T10:00:00Z"),
        _fb("ADDRESS", 0, "positive", "correct", recorded_at="2026-07-13T11:00:00Z"),
    ]
    report = build_feedback_report(records)
    assert report["entities_with_feedback"] == 1  # collapsed to one
    assert report["verdicts"] == {"positive": 1}  # the later verdict
    assert report["issue_types_sorted"] == []  # the issue was revised away
    assert report["revised_entities"] == 1


def test_recognizer_issue_rate_ranks_fix_candidates() -> None:
    records = [
        _fb("URL", 0, "issue", "overlap_conflict", recognizer="UrlRecognizer"),
        _fb("URL", 10, "issue", "overlap_conflict", recognizer="UrlRecognizer"),
        _fb("URL", 20, "positive", "correct", recognizer="UrlRecognizer"),
        _fb("PERSON", 30, "positive", "correct", recognizer="GlinerNerDetector"),
    ]
    report = build_feedback_report(records)
    top = report["recognizer_issue_rate"][0]
    assert top["recognizer"] == "UrlRecognizer"
    assert top["issues"] == 2 and top["total"] == 3
    assert top["issue_rate"] == round(2 / 3, 3)


def test_report_is_text_free_and_only_counts_comments() -> None:
    marker = "Max Mustermann lives at Musterstrasse 12"
    records = [_fb("PERSON", 0, "issue", "wrong_type", comment=marker)]
    report = build_feedback_report(records)
    assert marker not in json.dumps(report, ensure_ascii=False)
    assert report["comments_present"] == 1
