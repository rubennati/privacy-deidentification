"""Integration tests for PII review-entity decisions: grouping, decisions, and the review API.

Covers PII L11 (entity grouping) and the Review L8 decision-overlay slice: the reviewable
groups/occurrences view, group- and occurrence-level decisions, persistence, and the invariants
that `pii_result` and its raw/projected offsets are never mutated by a decision.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from tests.artifact_helpers import save_pii_artifact

from app.config import Settings
from app.schemas import PiiArtifact, PiiContent, PiiEntity, PiiValidationSummary

_SECRET_ORG = "TopSecret Insurance GmbH"


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
    settings: Settings, document_id: str, entities: list[PiiEntity], *, text_char_count: int = 500
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
        created_at="2026-07-03T10:00:00.000001Z",
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


# --- fetching reviewable groups/occurrences -------------------------------------------------


def test_review_before_pii_result_returns_404(client: TestClient) -> None:
    document_id = _upload_document(client)

    response = client.get(f"/api/documents/{document_id}/pii/review")

    assert response.status_code == 404


def test_unknown_document_returns_404_for_get_and_post(client: TestClient) -> None:
    document_id = "0" * 32

    assert client.get(f"/api/documents/{document_id}/pii/review").status_code == 404
    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", "f" * 32, "keep"),
    )
    assert response.status_code == 404


def test_review_lists_groups_and_occurrences_with_default_pseudonymize_status(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _make_entity("LOCATION", "Wien", 0),
        _make_entity("LOCATION", "Wien", 20),
    ]
    _save_pii(settings, document_id, entities)

    response = client.get(f"/api/documents/{document_id}/pii/review")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["input_text_artifact_id"] == "a" * 32
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["entity_type"] == "LOCATION"
    assert group["occurrence_count"] == 2
    # No explicit decision yet: the implied default is "pseudonymize", not a separate pending state.
    assert group["review_status"] == "accepted"
    assert group["review_decision"] is None
    assert group["updated_at"] is None
    assert group["projection_summary"] == {
        "exact_count": 0,
        "partial_count": 0,
        "unmapped_count": 2,
    }
    assert len(body["occurrences"]) == 2
    for occurrence in body["occurrences"]:
        assert occurrence["review_status"] == "accepted"
        assert occurrence["review_decision"] is None
        assert occurrence["decision_scope"] is None
        assert occurrence["entity_group_id"] == group["entity_group_id"]


def test_legacy_document_without_any_review_decisions_still_loads(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("EMAIL_ADDRESS", "max@example.at", 0)])

    response = client.get(f"/api/documents/{document_id}/pii/review")

    assert response.status_code == 200
    assert response.json()["groups"][0]["review_status"] == "accepted"


# --- group-level decisions -------------------------------------------------------------------


def test_group_level_pseudonymize_decision_applies_to_all_group_occurrences(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _make_entity("EMAIL_ADDRESS", "max@example.at", 0),
        _make_entity("EMAIL_ADDRESS", "max@example.at", 20),
    ]
    _save_pii(settings, document_id, entities)
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    post_response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "pseudonymize"),
    )
    assert post_response.status_code == 201
    ack = post_response.json()
    assert ack == {
        "recorded": True,
        "target_type": "entity_group",
        "target_id": group_id,
        "decision": "pseudonymize",
        "review_status": "accepted",
        "updated_at": ack["updated_at"],
    }

    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    assert review["groups"][0]["review_status"] == "accepted"
    assert review["groups"][0]["review_decision"] == "pseudonymize"
    for occurrence in review["occurrences"]:
        assert occurrence["review_status"] == "accepted"
        assert occurrence["review_decision"] == "pseudonymize"
        assert occurrence["decision_scope"] == "entity_group"


def test_occurrence_level_override_wins_over_group_decision(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _make_entity("EMAIL_ADDRESS", "max@example.at", 0),
        _make_entity("EMAIL_ADDRESS", "max@example.at", 20),
    ]
    _save_pii(settings, document_id, entities)
    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    group_id = review["groups"][0]["entity_group_id"]
    first_occurrence_id, second_occurrence_id = (o["occurrence_id"] for o in review["occurrences"])

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "keep"),
    )
    override = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", first_occurrence_id, "false_positive"),
    )
    assert override.status_code == 201

    review_after = client.get(f"/api/documents/{document_id}/pii/review").json()
    by_id = {o["occurrence_id"]: o for o in review_after["occurrences"]}
    assert by_id[first_occurrence_id]["review_status"] == "rejected"
    assert by_id[first_occurrence_id]["review_decision"] == "false_positive"
    assert by_id[first_occurrence_id]["decision_scope"] == "occurrence"
    assert by_id[second_occurrence_id]["review_status"] == "kept"
    assert by_id[second_occurrence_id]["review_decision"] == "keep"
    assert by_id[second_occurrence_id]["decision_scope"] == "entity_group"
    # The group-level view is unaffected by the occurrence override.
    assert review_after["groups"][0]["review_decision"] == "keep"


def test_kept_remains_distinct_from_false_positive(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _make_entity("LOCATION", "Wien", 0),
        _make_entity("LOCATION", "Graz", 20),
    ]
    _save_pii(settings, document_id, entities)
    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    wien_group, graz_group = (g["entity_group_id"] for g in review["groups"])

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", wien_group, "keep"),
    )
    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", graz_group, "false_positive"),
    )

    review_after = client.get(f"/api/documents/{document_id}/pii/review").json()
    by_id = {g["entity_group_id"]: g for g in review_after["groups"]}
    assert by_id[wien_group]["review_status"] == "kept"
    assert by_id[graz_group]["review_status"] == "rejected"
    assert by_id[wien_group]["review_status"] != by_id[graz_group]["review_status"]


def test_fetch_after_update_returns_persisted_decision(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("PERSON", "Max Mustermann", 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "keep", note="reviewed manually"),
    )

    first = client.get(f"/api/documents/{document_id}/pii/review").json()
    second = client.get(f"/api/documents/{document_id}/pii/review").json()
    assert first["groups"][0]["review_decision"] == "keep"
    assert second["groups"][0]["review_decision"] == "keep"
    assert first["groups"][0]["updated_at"] == second["groups"][0]["updated_at"]


# --- invariants: no mutation of raw/projected offsets -----------------------------------------


def test_decisions_do_not_mutate_detection_or_projection_offsets(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _make_entity("PERSON", "Max Mustermann", 10)
    _save_pii(settings, document_id, [entity])
    before = client.get(f"/api/documents/{document_id}/pii").json()["content"]["entities"][0]
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "pseudonymize"),
    )

    after = client.get(f"/api/documents/{document_id}/pii").json()["content"]["entities"][0]
    assert before == after
    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    occurrence = review["occurrences"][0]
    assert occurrence["raw_start"] == entity.start_offset
    assert occurrence["raw_end"] == entity.end_offset
    assert occurrence["reading_start_offset"] == entity.reading_start_offset
    assert occurrence["reading_end_offset"] == entity.reading_end_offset


def test_pii_endpoint_still_returns_raw_entities_and_projection_metadata(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]
    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "false_positive"),
    )

    response = client.get(f"/api/documents/{document_id}/pii")

    assert response.status_code == 200
    entity = response.json()["content"]["entities"][0]
    assert entity["entity_type"] == "LOCATION"
    assert entity["text"] == "Wien"
    assert "projection_status" in entity
    assert "review_status" not in entity
    assert "review_decision" not in entity


# --- validation / error handling ---------------------------------------------------------------


def test_invalid_decision_value_returns_422(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "delete_forever"),
    )

    assert response.status_code == 422


def test_invalid_decision_scope_returns_422(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("document", group_id, "keep"),
    )

    assert response.status_code == 422


def test_unknown_group_target_returns_404(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])

    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", "f" * 32, "keep"),
    )

    assert response.status_code == 404


def test_unknown_occurrence_target_returns_404(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])

    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("occurrence", "f" * 32, "keep"),
    )

    assert response.status_code == 404


def test_malformed_decision_payload_returns_422_not_a_crash(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])

    response = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json={"target_type": "entity_group"},
    )

    assert response.status_code == 422


# --- privacy / logging --------------------------------------------------------------------------


def test_review_response_does_not_duplicate_raw_sensitive_text(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("ORGANIZATION", _SECRET_ORG, 0)])

    response = client.get(f"/api/documents/{document_id}/pii/review")

    assert response.status_code == 200
    assert _SECRET_ORG not in response.text
    group = response.json()["groups"][0]
    assert "text" not in group
    assert "display_text" not in group


def test_logs_do_not_contain_raw_pii_values(
    client: TestClient, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("ORGANIZATION", _SECRET_ORG, 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    with caplog.at_level(logging.INFO, logger="app"):
        client.post(
            f"/api/documents/{document_id}/pii/review/decisions",
            json=_decision_payload("entity_group", group_id, "keep", note="looks fine"),
        )
        client.get(f"/api/documents/{document_id}/pii/review")

    assert all(_SECRET_ORG not in record.getMessage() for record in caplog.records)


def test_decision_note_is_persisted_but_not_leaked_into_group_response(
    client: TestClient, settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_make_entity("LOCATION", "Wien", 0)])
    group_id = client.get(f"/api/documents/{document_id}/pii/review").json()["groups"][0][
        "entity_group_id"
    ]

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json=_decision_payload("entity_group", group_id, "keep", note="reviewer note"),
    )

    decisions_file = document_data_dir / document_id / "review" / "pii_review_decisions.jsonl"
    assert decisions_file.is_file()
    entry = json.loads(decisions_file.read_text("utf-8").splitlines()[0])
    assert entry["note"] == "reviewer note"
    assert entry["source"] == "user"
    assert entry["text_artifact_id"] == "a" * 32
