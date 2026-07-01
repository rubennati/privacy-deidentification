"""Integration tests for PII Workstation v1 detection and persistence."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.api.pii import provide_pii_analyzer
from app.config import Settings
from app.main import app
from app.schemas import TextArtifact, TextContent, TextPageResult
from app.services.artifact_service import save_text_artifact
from app.services.pii_adapters import DetectedEntity, PiiUnavailableError


class FakePiiAnalyzer:
    def __init__(self) -> None:
        self.results: dict[str, list[DetectedEntity]] = {}
        self.calls: list[str] = []
        self.entity_types_seen: list[tuple[str, ...]] = []
        self.unavailable = False
        self.fail = False

    def analyze(
        self,
        text: str,
        language: str,
        entity_types: tuple[str, ...],
        score_threshold: float,
    ) -> list[DetectedEntity]:
        self.calls.append(text)
        self.entity_types_seen.append(entity_types)
        assert language == "de"
        assert entity_types
        assert score_threshold == 0.5
        if self.unavailable:
            raise PiiUnavailableError
        if self.fail:
            raise RuntimeError("simulated analyzer failure")
        return self.results.get(text, [])

    def tool_versions(self) -> dict[str, str]:
        return {
            "presidio_analyzer": "test",
            "spacy": "test",
            "spacy_model": "de_core_news_sm",
        }


@pytest.fixture(autouse=True)
def _allow_larger_pii_fixtures(settings: Settings) -> None:
    settings.max_upload_bytes = 2 * 1024 * 1024


@pytest.fixture
def pii_fake(client: TestClient) -> Iterator[FakePiiAnalyzer]:
    analyzer = FakePiiAnalyzer()
    app.dependency_overrides[provide_pii_analyzer] = lambda: analyzer
    yield analyzer


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload_document(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/uploads",
        files={"file": ("source.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    return response.json()


def _save_text(
    settings: Settings,
    document_id: str,
    text: str,
    *,
    pages: list[str] | None = None,
    created_at: str = "2026-07-01T10:00:00.000001Z",
) -> TextArtifact:
    text_pages = [
        TextPageResult(
            page_number=index,
            source="pdf_text_layer",
            has_text_layer=True,
            ocr_used=False,
            text=page_text,
            text_char_count=len(page_text),
        )
        for index, page_text in enumerate(pages or [], start=1)
    ]
    source = "pdf_text_layer" if pages is not None else "docx_text"
    artifact = TextArtifact(
        id=uuid4().hex,
        document_id=document_id,
        input_artifact_id="a" * 32,
        input_audit_artifact_id="b" * 32,
        created_at=created_at,
        content=TextContent(
            document_id=document_id,
            input_artifact_id="a" * 32,
            input_audit_artifact_id="b" * 32,
            source=source,
            text=text,
            text_char_count=len(text),
            pages=text_pages,
        ),
    )
    save_text_artifact(settings, artifact)
    return artifact


def _entity(
    entity_type: str, start: int, end: int, score: float = 0.8
) -> DetectedEntity:
    return DetectedEntity(entity_type, start, end, score, "FakeRecognizer")


def test_post_uses_latest_text_result_and_returns_entity_fields(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Old", created_at="2026-07-01T10:00:00.000001Z")
    latest = _save_text(
        settings,
        document_id,
        "Max Mustermann",
        created_at="2026-07-01T10:00:00.000002Z",
    )
    pii_fake.results["Max Mustermann"] = [_entity("PERSON", 0, 14, 0.86)]

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    artifact = response.json()
    assert artifact["artifact_type"] == "pii_result"
    assert artifact["station"] == "pii"
    assert artifact["input_text_artifact_id"] == latest.id
    entity = artifact["content"]["entities"][0]
    assert entity == {
        "id": entity["id"],
        "entity_type": "PERSON",
        "text": "Max Mustermann",
        "start_offset": 0,
        "end_offset": 14,
        "page_number": None,
        "page_start_offset": None,
        "page_end_offset": None,
        "score": 0.86,
        "recognizer": "FakeRecognizer",
    }
    assert pii_fake.calls == ["Max Mustermann"]


def test_pdf_pages_have_local_and_global_offsets(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    pages = ["Anna", "Kontakt max@example.at"]
    _save_text(settings, document_id, "\n\n".join(pages), pages=pages)
    pii_fake.results = {
        "Anna": [_entity("PERSON", 0, 4)],
        "Kontakt max@example.at": [_entity("EMAIL_ADDRESS", 8, 22)],
    }

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    first, second = response.json()["content"]["entities"]
    assert (first["start_offset"], first["end_offset"], first["page_number"]) == (0, 4, 1)
    assert (first["page_start_offset"], first["page_end_offset"]) == (0, 4)
    assert (second["start_offset"], second["end_offset"], second["page_number"]) == (
        len(pages[0]) + 2 + 8,
        len(pages[0]) + 2 + 22,
        2,
    )
    assert (second["page_start_offset"], second["page_end_offset"]) == (8, 22)
    assert second["text"] == "max@example.at"
    assert pii_fake.calls == pages


def test_docx_has_no_page_mapping(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Wien")
    pii_fake.results["Wien"] = [_entity("LOCATION", 0, 4)]

    response = client.post(f"/api/documents/{document_id}/pii")

    entity = response.json()["content"]["entities"][0]
    assert response.status_code == 201
    assert entity["page_number"] is None
    assert entity["page_start_offset"] is None
    assert entity["page_end_offset"] is None


def test_entities_are_sorted_and_counts_are_derived(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    text = "Anna in Wien mit Bob"
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("PERSON", 17, 20),
        _entity("LOCATION", 8, 12),
        _entity("PERSON", 0, 4),
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert [entity["text"] for entity in content["entities"]] == ["Anna", "Wien", "Bob"]
    assert content["entity_counts"] == {"LOCATION": 1, "PERSON": 2}


def test_empty_text_creates_empty_result_without_loading_analyzer(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "")

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert content["entities"] == []
    assert content["entity_counts"] == {}
    assert content["flags"] == ["empty_text"]
    assert pii_fake.calls == []


def test_service_forwards_configured_allowlist_verbatim(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    # The shipped default allowlist: structured recognizers only, no spaCy NER.
    settings.pii_entity_types = (
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "URL",
    )
    _save_text(settings, document_id, "Kontakt max@example.at")
    pii_fake.results["Kontakt max@example.at"] = [_entity("EMAIL_ADDRESS", 8, 22, 1.0)]

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    # The analyzer is asked for exactly the configured types — the noisy spaCy NER types are
    # never requested when they are not configured.
    assert pii_fake.entity_types_seen == [settings.pii_entity_types]
    for requested in pii_fake.entity_types_seen:
        assert "PERSON" not in requested
        assert "ORGANIZATION" not in requested
        assert "LOCATION" not in requested
    assert response.json()["content"]["configured_entity_types"] == list(
        settings.pii_entity_types
    )


def test_missing_text_result_returns_409(
    client: TestClient, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)

    response = client.post(f"/api/documents/{upload['id']}/pii")

    assert response.status_code == 409


def test_invalid_text_result_returns_409(
    client: TestClient, upload_dir: Path, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    directory = upload_dir / "artifacts" / str(upload["id"])
    directory.mkdir(parents=True)
    (directory / f"{uuid4().hex}.json").write_text(
        json.dumps({"artifact_type": "text_result", "content": "invalid"}),
        encoding="utf-8",
    )

    response = client.post(f"/api/documents/{upload['id']}/pii")

    assert response.status_code == 409


def test_get_without_pii_result_returns_404(client: TestClient) -> None:
    upload = _upload_document(client)

    response = client.get(f"/api/documents/{upload['id']}/pii")

    assert response.status_code == 404


def test_get_returns_latest_pii_result(
    client: TestClient,
    settings: Settings,
    pii_fake: FakePiiAnalyzer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Anna")
    pii_fake.results["Anna"] = [_entity("PERSON", 0, 4)]
    timestamps = iter(["2026-07-01T10:00:00.000001Z", "2026-07-01T10:00:00.000002Z"])
    monkeypatch.setattr("app.services.pii_service._now_utc_iso", lambda: next(timestamps))
    first = client.post(f"/api/documents/{document_id}/pii")
    second = client.post(f"/api/documents/{document_id}/pii")

    response = client.get(f"/api/documents/{document_id}/pii")

    assert first.status_code == 201
    assert second.status_code == 201
    assert response.status_code == 200
    assert response.json()["id"] == second.json()["id"]


def test_unavailable_analyzer_returns_503(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Anna")
    pii_fake.unavailable = True

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 503


def test_analyzer_processing_failure_returns_422(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Anna")
    pii_fake.fail = True

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 422


def test_delete_removes_all_document_artifacts(
    client: TestClient,
    settings: Settings,
    upload_dir: Path,
    pii_fake: FakePiiAnalyzer,
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Anna")
    pii_fake.results["Anna"] = [_entity("PERSON", 0, 4)]
    assert client.post(f"/api/documents/{document_id}/pii").status_code == 201
    artifact_directory = upload_dir / "artifacts" / document_id
    assert len(list(artifact_directory.glob("*.json"))) == 2

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 204
    assert not artifact_directory.exists()


def test_logs_do_not_contain_source_or_entity_text(
    client: TestClient,
    settings: Settings,
    pii_fake: FakePiiAnalyzer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    secret = "VerySecretPerson"
    _save_text(settings, document_id, secret)
    pii_fake.results[secret] = [_entity("PERSON", 0, len(secret))]

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    assert all(secret not in record.getMessage() for record in caplog.records)
