"""Pydantic-level schema tests for the PII review-entity decision models.

These are fast, HTTP-free checks that the new additive models validate correctly on their own and
that nothing about the existing immutable `PiiArtifact`/`PiiContent`/`PiiEntity` contract changed —
review decisions are a separate overlay, never a field on the detection artifact itself.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    PiiArtifact,
    PiiEntity,
    PiiEntityGroup,
    PiiEntityGroupProjectionSummary,
    PiiEntityGroupReview,
    PiiReviewDecisionRecord,
    PiiReviewDecisionRequest,
    PiiReviewOccurrence,
)


def test_legacy_pii_entity_without_review_fields_still_validates() -> None:
    entity = PiiEntity(
        id=uuid4().hex,
        entity_type="LOCATION",
        text="Wien",
        start_offset=0,
        end_offset=4,
        score=0.9,
        recognizer="FakeRecognizer",
    )
    assert not hasattr(entity, "review_status")
    assert not hasattr(entity, "review_decision")
    assert not hasattr(entity, "entity_group_id")


def test_legacy_pii_artifact_json_without_review_data_still_validates() -> None:
    # A byte-for-byte legacy shape written before this task existed; the review layer must never
    # require new fields on the persisted, immutable pii_result artifact.
    legacy_json = f"""
    {{
        "id": "{"a" * 32}",
        "document_id": "{"b" * 32}",
        "artifact_type": "pii_result",
        "station": "pii",
        "input_text_artifact_id": "{"c" * 32}",
        "media_type": "application/json",
        "created_at": "2026-01-01T00:00:00.000001Z",
        "content": {{
            "document_id": "{"b" * 32}",
            "input_text_artifact_id": "{"c" * 32}",
            "pii_version": "1",
            "profile": "custom",
            "language": "de",
            "score_threshold": 0.5,
            "text_char_count": 4,
            "configured_entity_types": ["LOCATION"],
            "entities": [
                {{
                    "id": "{"d" * 32}",
                    "entity_type": "LOCATION",
                    "text": "Wien",
                    "start_offset": 0,
                    "end_offset": 4,
                    "score": 0.9,
                    "recognizer": "FakeRecognizer"
                }}
            ],
            "entity_counts": {{"LOCATION": 1}},
            "tool_versions": {{}},
            "flags": []
        }}
    }}
    """
    artifact = PiiArtifact.model_validate_json(legacy_json)
    assert artifact.content.entities[0].entity_type == "LOCATION"


def test_entity_group_requires_summary_to_cover_every_occurrence() -> None:
    with pytest.raises(ValidationError):
        PiiEntityGroup(
            entity_group_id="a" * 32,
            entity_type="LOCATION",
            occurrence_ids=["b" * 32, "c" * 32],
            occurrence_count=2,
            normalized_fingerprint="d" * 64,
            projection_summary=PiiEntityGroupProjectionSummary(
                exact_count=0, partial_count=0, unmapped_count=1
            ),
        )


def test_entity_group_rejects_duplicate_occurrence_ids() -> None:
    with pytest.raises(ValidationError):
        PiiEntityGroup(
            entity_group_id="a" * 32,
            entity_type="LOCATION",
            occurrence_ids=["b" * 32, "b" * 32],
            occurrence_count=2,
            normalized_fingerprint="d" * 64,
            projection_summary=PiiEntityGroupProjectionSummary(
                exact_count=0, partial_count=0, unmapped_count=2
            ),
        )


@pytest.mark.parametrize(
    "decision",
    ["pseudonymize", "keep", "ignore", "false_positive"],
)
def test_review_decision_request_accepts_all_documented_decisions(decision: str) -> None:
    request = PiiReviewDecisionRequest(
        target_type="entity_group", target_id="a" * 32, decision=decision
    )
    assert request.decision == decision


def test_review_decision_request_rejects_unknown_decision_value() -> None:
    with pytest.raises(ValidationError):
        PiiReviewDecisionRequest(
            target_type="entity_group", target_id="a" * 32, decision="delete_forever"
        )


def test_review_decision_request_rejects_unknown_target_type() -> None:
    with pytest.raises(ValidationError):
        PiiReviewDecisionRequest(target_type="document", target_id="a" * 32, decision="keep")


def test_review_decision_request_normalizes_blank_note_to_none() -> None:
    request = PiiReviewDecisionRequest(
        target_type="occurrence", target_id="a" * 32, decision="keep", note="   "
    )
    assert request.note is None


def test_review_occurrence_rejects_inverted_offsets() -> None:
    with pytest.raises(ValidationError):
        PiiReviewOccurrence(
            occurrence_id="a" * 32,
            entity_type="LOCATION",
            entity_group_id="b" * 32,
            raw_start=10,
            raw_end=5,
            score=0.9,
            recognizer="FakeRecognizer",
        )


def test_review_occurrence_defaults_to_pending_with_no_decision() -> None:
    occurrence = PiiReviewOccurrence(
        occurrence_id="a" * 32,
        entity_type="LOCATION",
        entity_group_id="b" * 32,
        raw_start=0,
        raw_end=4,
        score=0.9,
        recognizer="FakeRecognizer",
    )
    assert occurrence.review_status == "pending"
    assert occurrence.review_decision is None
    assert occurrence.decision_scope is None


def test_entity_group_review_extends_group_with_review_state() -> None:
    review = PiiEntityGroupReview(
        entity_group_id="a" * 32,
        entity_type="LOCATION",
        occurrence_ids=["b" * 32],
        occurrence_count=1,
        normalized_fingerprint="c" * 64,
        projection_summary=PiiEntityGroupProjectionSummary(
            exact_count=0, partial_count=0, unmapped_count=1
        ),
    )
    assert review.review_status == "pending"
    assert review.review_decision is None
    assert review.updated_at is None


def test_review_decision_record_requires_valid_document_and_artifact_ids() -> None:
    with pytest.raises(ValidationError):
        PiiReviewDecisionRecord(
            app_version="test",
            recorded_at="2026-07-03T10:00:00.000001Z",
            document_id="not-a-valid-id",
            artifact_id="a" * 32,
            target_type="entity_group",
            target_id="b" * 32,
            decision="keep",
        )
