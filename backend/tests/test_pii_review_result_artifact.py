"""Integration + schema tests for the Review L8 `review_result` artifact (ADR-0034).

Covers: the new immutable per-run `PiiReviewResultArtifact` snapshot (saved after each recorded
decision), the new `GET .../pii/review-result` endpoint, and the additive `stale_decision_count`/
`has_stale_decisions` staleness signal on `PiiReviewResult` -- decisions recorded against a PII
result that was since re-run were already never silently reapplied (unchanged); this makes that
fact explicit instead of indistinguishable from "no decision recorded".
"""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from tests.artifact_helpers import save_pii_artifact

from app.config import Settings
from app.schemas import (
    PiiArtifact,
    PiiContent,
    PiiEntity,
    PiiReviewResult,
    PiiReviewResultArtifact,
    PiiValidationSummary,
)


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload_document(client: TestClient) -> str:
    response = client.post(
        "/api/uploads",
        files={"file": ("source.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _make_entity(entity_type: str, text: str, start: int, score: float = 0.9) -> PiiEntity:
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=start + len(text),
        score=score,
        recognizer="TestRecognizer",
    )


def _save_pii(
    settings: Settings,
    document_id: str,
    entities: list[PiiEntity],
    *,
    text_char_count: int = 500,
    created_at: str = "2026-07-10T10:00:00.000001Z",
) -> PiiArtifact:
    configured_types = sorted({entity.entity_type for entity in entities}) or ["LOCATION"]
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    content = PiiContent(
        document_id=document_id,
        input_text_artifact_id="a" * 32,
        profile="custom",
        language="de",
        score_threshold=0.5,
        text_char_count=text_char_count,
        configured_entity_types=configured_types,
        entities=entities,
        entity_counts=dict(sorted(counts.items())),
        tool_versions={},
        flags=[],
        validation=PiiValidationSummary(enabled=True, kept=len(entities), dropped=0, score_down=0),
    )
    artifact = PiiArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_text_artifact_id="a" * 32,
        created_at=created_at,
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def _decision_payload(
    target_type: str, target_id: str, decision: str, note: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "target_type": target_type,
        "target_id": target_id,
        "decision": decision,
    }
    if note is not None:
        payload["note"] = note
    return payload


# --- GET .../pii/review-result -------------------------------------------------------------------


def test_no_snapshot_before_any_decision_returns_404(client: TestClient) -> None:
    document_id = _upload_document(client)
    response = client.get(f"/api/documents/{document_id}/pii/review-result")
    assert response.status_code == 404


def test_unknown_document_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/documents/{'0' * 32}/pii/review-result")
    assert response.status_code == 404


def test_decision_creates_a_persisted_snapshot(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    entity = _make_entity("LOCATION", "Wien", 0)
    artifact = _save_pii(settings, document_id, [entity])

    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    [group] = review["groups"]
    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group["entity_group_id"], "keep"),
    )
    assert response.status_code == 201

    snapshot_response = client.get(f"/api/documents/{document_id}/pii/review-result")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["document_id"] == document_id
    assert snapshot["input_pii_artifact_id"] == artifact.id
    assert snapshot["input_text_artifact_id"] == "a" * 32
    assert snapshot["artifact_type"] == "pii_review_result"
    assert snapshot["content"]["input_text_artifact_id"] == "a" * 32
    assert snapshot["content"]["occurrences"][0]["review_status"] == "kept"
    assert snapshot["content"]["stale_decision_count"] == 0
    assert snapshot["content"]["has_stale_decisions"] is False


def test_each_decision_creates_a_new_immutable_snapshot(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _make_entity("LOCATION", "Wien", 0)
    _save_pii(settings, document_id, [entity])

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", entity.id, "keep"),
    )
    first = client.get(f"/api/documents/{document_id}/pii/review-result").json()

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", entity.id, "false_positive"),
    )
    second = client.get(f"/api/documents/{document_id}/pii/review-result").json()

    # Immutable-per-run: a new decision produces a new snapshot artifact id, and the latest one
    # reflects the latest decision.
    assert first["id"] != second["id"]
    assert first["content"]["occurrences"][0]["review_status"] == "kept"
    assert second["content"]["occurrences"][0]["review_status"] == "rejected"


# --- staleness --------------------------------------------------------------------------------


def test_stale_decisions_are_surfaced_after_a_pii_rerun(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    first_entity = _make_entity("LOCATION", "Wien", 0)
    _save_pii(settings, document_id, [first_entity])

    decision_response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", first_entity.id, "keep"),
    )
    assert decision_response.status_code == 201

    # Before the re-run: no staleness yet.
    review_before = client.get(f"/api/documents/{document_id}/pii/review").json()
    assert review_before["stale_decision_count"] == 0
    assert review_before["has_stale_decisions"] is False

    # Simulate a PII re-run: a new artifact, new occurrence ids (fresh detection uuids), same as a
    # real re-detection would produce.
    second_entity = _make_entity("LOCATION", "Graz", 20)
    _save_pii(settings, document_id, [second_entity], created_at="2026-07-10T11:00:00.000001Z")

    review_after = client.get(f"/api/documents/{document_id}/pii/review").json()
    assert review_after["stale_decision_count"] == 1
    assert review_after["has_stale_decisions"] is True
    # The old decision never silently reapplies to the new (unrelated) occurrence -- unchanged
    # existing behavior, now paired with the explicit staleness signal above.
    assert review_after["occurrences"][0]["review_status"] == "accepted"
    assert review_after["occurrences"][0]["review_decision"] is None


def test_new_decision_against_the_current_run_does_not_count_as_stale(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    first_entity = _make_entity("LOCATION", "Wien", 0)
    _save_pii(settings, document_id, [first_entity])
    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", first_entity.id, "keep"),
    )

    second_entity = _make_entity("LOCATION", "Graz", 20)
    _save_pii(settings, document_id, [second_entity], created_at="2026-07-10T11:00:00.000001Z")
    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", second_entity.id, "false_positive"),
    )

    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    # One decision from the superseded run (stale) and one fresh decision against the current run
    # (not stale) -- the count only reflects the former.
    assert review["stale_decision_count"] == 1
    assert review["has_stale_decisions"] is True
    assert review["occurrences"][0]["review_status"] == "rejected"


# --- leak safety ------------------------------------------------------------------------------


def test_snapshot_response_does_not_leak_raw_pii_text(
    client: TestClient, settings: Settings
) -> None:
    secret = "TopSecret Insurance GmbH"
    entity = _make_entity("ORGANIZATION", secret, 0)
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [entity])
    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", entity.id, "keep"),
    )

    response = client.get(f"/api/documents/{document_id}/pii/review-result")
    assert secret not in response.text


# --- schema-level validation -------------------------------------------------------------------


def _review_result(document_id: str, artifact_id: str) -> PiiReviewResult:
    return PiiReviewResult(document_id=document_id, artifact_id=artifact_id)


def test_content_identity_mismatch_document_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PiiReviewResultArtifact(
            id=uuid4().hex,
            document_id="a" * 32,
            input_pii_artifact_id="b" * 32,
            created_at="2026-07-10T10:00:00.000001Z",
            content=_review_result("c" * 32, "b" * 32),
        )


def test_content_identity_mismatch_artifact_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PiiReviewResultArtifact(
            id=uuid4().hex,
            document_id="a" * 32,
            input_pii_artifact_id="b" * 32,
            created_at="2026-07-10T10:00:00.000001Z",
            content=_review_result("a" * 32, "d" * 32),
        )


def test_content_identity_mismatch_text_artifact_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PiiReviewResultArtifact(
            id=uuid4().hex,
            document_id="a" * 32,
            input_pii_artifact_id="b" * 32,
            input_text_artifact_id="c" * 32,
            created_at="2026-07-10T10:00:00.000001Z",
            content=PiiReviewResult(
                document_id="a" * 32,
                artifact_id="b" * 32,
                input_text_artifact_id="d" * 32,
            ),
        )


def test_has_stale_decisions_must_match_count() -> None:
    with pytest.raises(ValidationError):
        PiiReviewResult(
            document_id="a" * 32,
            artifact_id="b" * 32,
            stale_decision_count=0,
            has_stale_decisions=True,
        )
    with pytest.raises(ValidationError):
        PiiReviewResult(
            document_id="a" * 32,
            artifact_id="b" * 32,
            stale_decision_count=2,
            has_stale_decisions=False,
        )


def test_valid_snapshot_round_trips_through_json() -> None:
    artifact = PiiReviewResultArtifact(
        id=uuid4().hex,
        document_id="a" * 32,
        input_pii_artifact_id="b" * 32,
        created_at="2026-07-10T10:00:00.000001Z",
        content=_review_result("a" * 32, "b" * 32),
    )
    restored = PiiReviewResultArtifact.model_validate_json(artifact.model_dump_json())
    assert restored == artifact
