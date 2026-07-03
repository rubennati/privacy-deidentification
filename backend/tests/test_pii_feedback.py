"""Integration tests for dev-only PII review feedback capture."""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings, get_settings
from app.main import app
from app.schemas import (
    PiiArtifact,
    PiiContent,
    PiiEngineSettings,
    PiiEntity,
    PiiValidationSummary,
)
from app.services.artifact_service import save_pii_artifact

_DOC_TEXT_MARKER = "TOPSECRETDOCUMENTTEXT"


@pytest.fixture(autouse=True)
def _allow_larger_fixtures(settings: Settings) -> None:
    settings.max_upload_bytes = 2 * 1024 * 1024


@pytest.fixture
def gate_on_settings(settings: Settings) -> Settings:
    """The same isolated settings as the base fixture, but with the dev gate enabled."""
    return settings.model_copy(update={"enable_dev_engine_settings": True})


@pytest.fixture
def gate_on_client(gate_on_settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: gate_on_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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


def _save_pii(
    settings: Settings, document_id: str, *, with_engine_settings: bool = True
) -> PiiArtifact:
    """Persist one valid PII artifact to reference from feedback.

    The entity text below is *only* used to satisfy the artifact's own offset/text invariant; it
    is never part of the feedback payload nor of what feedback persists.
    """
    entity_text = "Wien"
    entity = PiiEntity(
        id=uuid4().hex,
        entity_type="LOCATION",
        text=entity_text,
        start_offset=0,
        end_offset=len(entity_text),
        score=0.9,
        recognizer="FakeRecognizer",
    )
    engine_settings = (
        PiiEngineSettings(
            pii_profile="review-heavy",
            candidate_validation_enabled=True,
            score_threshold=0.5,
            source="server-default",
        )
        if with_engine_settings
        else None
    )
    content = PiiContent(
        document_id=document_id,
        input_text_artifact_id="a" * 32,
        profile="review-heavy",
        language="de",
        score_threshold=0.5,
        text_char_count=len(_DOC_TEXT_MARKER),
        configured_entity_types=["LOCATION"],
        entities=[entity],
        entity_counts={"LOCATION": 1},
        tool_versions={},
        flags=[],
        validation=PiiValidationSummary(enabled=True, kept=1, dropped=0, score_down=0),
        engine_settings=engine_settings,
    )
    artifact = PiiArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_text_artifact_id="a" * 32,
        created_at="2026-07-02T10:00:00.000001Z",
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def _feedback_file(document_data_dir: Path, document_id: str) -> Path:
    return document_data_dir / document_id / "feedback" / "pii_feedback.jsonl"


def _archive_file(pii_feedback_archive_dir: Path) -> Path:
    return pii_feedback_archive_dir / "pii_feedback.jsonl"


def _positive_payload(artifact_id: str) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "entity": {
            "type": "LOCATION",
            "start": 0,
            "end": 4,
            "score": 0.9,
            "recognizer": "FakeRecognizer",
        },
        "feedback": {"verdict": "positive", "issue_type": "correct"},
    }


def test_feedback_rejected_when_gate_disabled(
    client: TestClient, settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(client)
    artifact = _save_pii(settings, document_id)

    response = client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert response.status_code == 403
    # A disabled gate must never touch disk.
    assert not _feedback_file(document_data_dir, document_id).exists()


def test_feedback_gate_is_checked_before_document_or_artifact_access(
    client: TestClient, document_data_dir: Path
) -> None:
    document_id = "0" * 32

    response = client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload("f" * 32),
    )

    assert response.status_code == 403
    assert not (document_data_dir / document_id).exists()


def test_feedback_recorded_when_gate_enabled(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recorded"] is True
    assert body["schema_version"] == "1"
    assert body["recorded_at"]

    lines = _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["document_id"] == document_id
    assert entry["artifact_id"] == artifact.id
    assert entry["recorded_at"]
    assert entry["app_version"]
    assert entry["schema_version"] == "1"
    assert entry["feedback"] == {"verdict": "positive", "issue_type": "correct", "comment": None}
    assert entry["entity"]["type"] == "LOCATION"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "PERSON"),
        ("start", 1),
        ("end", 3),
        ("recognizer", "ManipulatedRecognizer"),
    ],
)
def test_manipulated_entity_reference_is_rejected_without_storage(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    document_data_dir: Path,
    field: str,
    value: object,
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    payload = _positive_payload(artifact.id)
    entity = payload["entity"]
    assert isinstance(entity, dict)
    entity[field] = value

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Feedback entity reference does not match any entity in the referenced PII artifact."
    )
    assert not _feedback_file(document_data_dir, document_id).exists()


def test_feedback_uses_artifact_score_instead_of_client_score(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    payload = _positive_payload(artifact.id)
    entity = payload["entity"]
    assert isinstance(entity, dict)
    entity["score"] = 0.1

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=payload,
    )

    assert response.status_code == 201
    entry = json.loads(
        _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()[0]
    )
    assert entry["entity"]["score"] == 0.9


def test_raw_text_like_text_hash_is_rejected(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    document_data_dir: Path,
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    payload = _positive_payload(artifact.id)
    entity = payload["entity"]
    assert isinstance(entity, dict)
    entity["text_hash"] = "Wien"

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=payload,
    )

    assert response.status_code == 422
    assert not _feedback_file(document_data_dir, document_id).exists()


def test_sha256_text_hash_is_accepted(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    payload = _positive_payload(artifact.id)
    entity = payload["entity"]
    assert isinstance(entity, dict)
    digest = "a" * 64
    entity["text_hash"] = digest

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=payload,
    )

    assert response.status_code == 201
    entry = json.loads(
        _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()[0]
    )
    assert entry["entity"]["text_hash"] == digest


def test_feedback_appends_without_overwriting(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    url = f"/api/documents/{document_id}/pii/feedback"

    assert gate_on_client.post(url, json=_positive_payload(artifact.id)).status_code == 201
    issue = {
        "artifact_id": artifact.id,
        "entity": {
            "type": "LOCATION",
            "start": 0,
            "end": 4,
            "score": 0.9,
            "recognizer": "FakeRecognizer",
        },
        "feedback": {
            "verdict": "issue",
            "issue_type": "wrong_type",
            "comment": "should be PERSON",
        },
    }
    assert gate_on_client.post(url, json=issue).status_code == 201

    lines = _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    assert second["feedback"]["verdict"] == "issue"
    assert second["feedback"]["issue_type"] == "wrong_type"
    assert second["feedback"]["comment"] == "should be PERSON"


def test_feedback_entry_contains_engine_settings(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id, with_engine_settings=True)

    gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    entry = json.loads(
        _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()[0]
    )
    assert entry["engine_settings_origin"] == "artifact"
    assert entry["engine_settings"]["pii_profile"] == "review-heavy"
    assert entry["engine_settings"]["candidate_validation_enabled"] is True
    assert entry["engine_settings"]["score_threshold"] == 0.5


def test_legacy_artifact_without_optional_metadata_still_records(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id, with_engine_settings=False)

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert response.status_code == 201
    entry = json.loads(
        _feedback_file(document_data_dir, document_id).read_text("utf-8").splitlines()[0]
    )
    assert entry["engine_settings"] is None
    assert entry["engine_settings_origin"] == "unknown"


@pytest.mark.parametrize(
    "feedback",
    [
        {"verdict": "issue", "issue_type": "not_a_real_issue"},
        {"verdict": "positive", "issue_type": "wrong_type"},
        {"verdict": "issue", "issue_type": "correct"},
        {"verdict": "maybe", "issue_type": "correct"},
    ],
)
def test_invalid_feedback_is_rejected(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    feedback: dict[str, str],
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json={
            "artifact_id": artifact.id,
            "entity": {
                "type": "LOCATION",
                "start": 0,
                "end": 4,
                "score": 0.9,
                "recognizer": "FakeRecognizer",
            },
            "feedback": feedback,
        },
    )

    assert response.status_code == 422


def test_no_document_or_entity_text_is_stored(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)

    gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    raw = _feedback_file(document_data_dir, document_id).read_text("utf-8")
    assert _DOC_TEXT_MARKER not in raw
    assert '"Wien"' not in raw
    entry = json.loads(raw.splitlines()[0])
    # The persisted entity fingerprint carries offsets/type/recognizer only — never raw text.
    assert "text" not in entry["entity"]
    assert entry["entity"].get("text_hash") is None


def test_unknown_document_returns_404(gate_on_client: TestClient) -> None:
    response = gate_on_client.post(
        f"/api/documents/{'0' * 32}/pii/feedback",
        json=_positive_payload("f" * 32),
    )
    assert response.status_code == 404


def test_unknown_artifact_returns_404(
    gate_on_client: TestClient, gate_on_settings: Settings
) -> None:
    document_id = _upload_document(gate_on_client)
    _save_pii(gate_on_settings, document_id)

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload("f" * 32),
    )
    assert response.status_code == 404


def test_feedback_directory_is_created_on_first_write(
    gate_on_client: TestClient, gate_on_settings: Settings, document_data_dir: Path
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    feedback_dir = document_data_dir / document_id / "feedback"
    assert not feedback_dir.exists()

    gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert feedback_dir.is_dir()
    assert (feedback_dir / "pii_feedback.jsonl").is_file()


def test_summary_rejected_when_gate_disabled(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    artifact = _save_pii(settings, document_id)

    response = client.get(
        f"/api/documents/{document_id}/pii/feedback",
        params={"artifact_id": artifact.id},
    )
    assert response.status_code == 403


def test_summary_collapses_history_to_latest_status_per_entity(
    gate_on_client: TestClient, gate_on_settings: Settings
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    url = f"/api/documents/{document_id}/pii/feedback"

    # Same entity, twice: positive then an issue — the issue is the latest status.
    gate_on_client.post(url, json=_positive_payload(artifact.id))
    gate_on_client.post(
        url,
        json={
            "artifact_id": artifact.id,
            "entity": {
                "type": "LOCATION",
                "start": 0,
                "end": 4,
                "score": 0.9,
                "recognizer": "FakeRecognizer",
            },
            "feedback": {"verdict": "issue", "issue_type": "wrong_type", "comment": "x"},
        },
    )
    response = gate_on_client.get(url, params={"artifact_id": artifact.id})
    assert response.status_code == 200
    items = {
        (i["type"], i["start"], i["end"], i["recognizer"]): i
        for i in response.json()["items"]
    }
    assert len(items) == 1
    location = items[("LOCATION", 0, 4, "FakeRecognizer")]
    assert location["verdict"] == "issue"
    assert location["issue_type"] == "wrong_type"


def test_summary_ignores_legacy_feedback_for_non_artifact_entity(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    document_data_dir: Path,
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    url = f"/api/documents/{document_id}/pii/feedback"
    assert gate_on_client.post(url, json=_positive_payload(artifact.id)).status_code == 201

    feedback_file = _feedback_file(document_data_dir, document_id)
    invalid_entry = json.loads(feedback_file.read_text("utf-8").splitlines()[0])
    invalid_entry["entity"]["start"] = 10
    invalid_entry["entity"]["end"] = 14
    with feedback_file.open("a", encoding="utf-8") as feedback_log:
        feedback_log.write(json.dumps(invalid_entry) + "\n")

    response = gate_on_client.get(url, params={"artifact_id": artifact.id})

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["start"] == 0


def test_summary_returns_no_comment_or_raw_text(
    gate_on_client: TestClient, gate_on_settings: Settings
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    url = f"/api/documents/{document_id}/pii/feedback"
    gate_on_client.post(
        url,
        json={
            "artifact_id": artifact.id,
            "entity": {
                "type": "LOCATION",
                "start": 0,
                "end": 4,
                "score": 0.9,
                "recognizer": "FakeRecognizer",
            },
            "feedback": {"verdict": "issue", "issue_type": "other", "comment": "SENSITIVE_NOTE"},
        },
    )

    response = gate_on_client.get(url, params={"artifact_id": artifact.id})
    assert response.status_code == 200
    assert "SENSITIVE_NOTE" not in response.text
    item = response.json()["items"][0]
    assert "comment" not in item
    assert "text" not in item


def test_summary_unknown_artifact_returns_404(
    gate_on_client: TestClient, gate_on_settings: Settings
) -> None:
    document_id = _upload_document(gate_on_client)
    _save_pii(gate_on_settings, document_id)

    response = gate_on_client.get(
        f"/api/documents/{document_id}/pii/feedback",
        params={"artifact_id": "f" * 32},
    )
    assert response.status_code == 404


def test_feedback_is_also_written_to_the_cross_document_archive(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    pii_feedback_archive_dir: Path,
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)

    response = gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert response.status_code == 201
    lines = _archive_file(pii_feedback_archive_dir).read_text("utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    # document_id is retained in the archive (ADR-0020): the archive is meant for later aggregate
    # PII-quality analysis, where knowing the source document remains useful.
    assert entry["document_id"] == document_id
    assert entry["artifact_id"] == artifact.id
    assert entry["entity"]["type"] == "LOCATION"
    assert "text" not in entry["entity"]


def test_archive_accumulates_across_multiple_documents(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    pii_feedback_archive_dir: Path,
) -> None:
    first_document_id = _upload_document(gate_on_client)
    first_artifact = _save_pii(gate_on_settings, first_document_id)
    second_document_id = _upload_document(gate_on_client)
    second_artifact = _save_pii(gate_on_settings, second_document_id)

    gate_on_client.post(
        f"/api/documents/{first_document_id}/pii/feedback",
        json=_positive_payload(first_artifact.id),
    )
    gate_on_client.post(
        f"/api/documents/{second_document_id}/pii/feedback",
        json=_positive_payload(second_artifact.id),
    )

    lines = _archive_file(pii_feedback_archive_dir).read_text("utf-8").splitlines()
    assert len(lines) == 2
    document_ids = {json.loads(line)["document_id"] for line in lines}
    assert document_ids == {first_document_id, second_document_id}


def test_disabled_gate_writes_neither_the_document_copy_nor_the_archive(
    client: TestClient,
    settings: Settings,
    document_data_dir: Path,
    pii_feedback_archive_dir: Path,
) -> None:
    document_id = _upload_document(client)
    artifact = _save_pii(settings, document_id)

    response = client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )

    assert response.status_code == 403
    assert not _feedback_file(document_data_dir, document_id).exists()
    assert not _archive_file(pii_feedback_archive_dir).exists()


def test_archive_survives_document_deletion(
    gate_on_client: TestClient,
    gate_on_settings: Settings,
    document_data_dir: Path,
    pii_feedback_archive_dir: Path,
) -> None:
    document_id = _upload_document(gate_on_client)
    artifact = _save_pii(gate_on_settings, document_id)
    gate_on_client.post(
        f"/api/documents/{document_id}/pii/feedback",
        json=_positive_payload(artifact.id),
    )
    assert _feedback_file(document_data_dir, document_id).exists()
    assert _archive_file(pii_feedback_archive_dir).exists()

    delete_response = gate_on_client.delete(f"/api/documents/{document_id}")

    assert delete_response.status_code == 204
    # The per-document copy is gone with the rest of the document's data (ADR-0008)...
    assert not (document_data_dir / document_id).exists()
    # ...but the cross-document archive is untouched by design (ADR-0020) and still has the entry.
    lines = _archive_file(pii_feedback_archive_dir).read_text("utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["document_id"] == document_id
