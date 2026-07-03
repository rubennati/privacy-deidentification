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
from app.schemas import (
    LayoutBlock,
    StructuredContent,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.artifact_service import save_text_artifact
from app.services.pii_adapters import DetectedEntity, PiiUnavailableError
from app.services.pii_profiles import get_pii_profile
from app.services.structured_content import build_structured_content


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
    pii_input_text: str | None = None,
    layout_text_result: str | None = None,
    readable_text: str | None = None,
    layout_blocks: list[LayoutBlock] | None = None,
    structured_content: StructuredContent | None = None,
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
            pii_input_text=pii_input_text,
            layout_text_result=layout_text_result,
            readable_text=readable_text,
            layout_blocks_version="1" if layout_blocks else None,
            layout_blocks=layout_blocks or [],
            structured_content_version="1" if structured_content else None,
            structured_content=structured_content,
        ),
    )
    save_text_artifact(settings, artifact)
    return artifact


def _entity(
    entity_type: str, start: int, end: int, score: float = 0.8
) -> DetectedEntity:
    return DetectedEntity(entity_type, start, end, score, "FakeRecognizer")


def test_post_uses_latest_text_result_and_returns_entity_fields(
    client: TestClient,
    settings: Settings,
    document_data_dir: Path,
    pii_fake: FakePiiAnalyzer,
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
    assert artifact["content"]["engine_settings"] == {
        "pii_profile": "custom",
        "candidate_validation_enabled": True,
        "score_threshold": 0.5,
        "source": "server-default",
    }
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
        "original_score": 0.86,
        "validation_status": "kept",
        "validation_reasons": [],
    }
    assert pii_fake.calls == ["Max Mustermann"]
    artifact_path = document_data_dir / document_id / "artifacts" / f"{artifact['id']}.json"
    assert artifact_path.is_file()


def test_pdf_pages_have_local_and_global_offsets(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    # A two-token capitalized name survives candidate validation by shape, unlike a bare
    # single-token candidate (see test_pii_candidate_validation.py) — this test is about
    # page-local/global offset math, not validation, so the fixture is chosen to pass through.
    pages = ["Max Mustermann", "Kontakt max@example.at"]
    _save_text(settings, document_id, "\n\n".join(pages), pages=pages)
    pii_fake.results = {
        "Max Mustermann": [_entity("PERSON", 0, 14)],
        "Kontakt max@example.at": [_entity("EMAIL_ADDRESS", 8, 22)],
    }

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    first, second = response.json()["content"]["entities"]
    assert (first["start_offset"], first["end_offset"], first["page_number"]) == (0, 14, 1)
    assert (first["page_start_offset"], first["page_end_offset"]) == (0, 14)
    assert (second["start_offset"], second["end_offset"], second["page_number"]) == (
        len(pages[0]) + 2 + 8,
        len(pages[0]) + 2 + 22,
        2,
    )
    assert (second["page_start_offset"], second["page_end_offset"]) == (8, 22)
    assert second["text"] == "max@example.at"
    assert pii_fake.calls == pages


def test_pii_ignores_all_non_canonical_text_views(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    canonical = "Name: Max Mustermann"
    page = TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=canonical,
        text_char_count=len(canonical),
    )
    structured_content = build_structured_content(canonical, [page], [], None)
    _save_text(
        settings,
        document_id,
        canonical,
        pages=[canonical],
        readable_text="Readable replacement",
        layout_text_result="Layout replacement",
        pii_input_text="PII input replacement",
        layout_blocks=[
            LayoutBlock(
                page_number=1,
                order=1,
                block_type="body",
                text="Block replacement",
                x0=0.1,
                y0=0.1,
                x1=0.9,
                y1=0.2,
                source="pdf_text_layer",
            )
        ],
        structured_content=structured_content,
    )

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    assert pii_fake.calls == [canonical]


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
    # Two-token capitalized names survive candidate validation by shape (unlike a bare
    # single-token candidate); this test is about sort order and count derivation, not
    # validation, so the fixture is chosen to pass through unchanged.
    text = "Max Mustermann in Wien mit Erika Musterfrau"
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("PERSON", 27, 43),  # "Erika Musterfrau"
        _entity("LOCATION", 18, 22),  # "Wien"
        _entity("PERSON", 0, 14),  # "Max Mustermann"
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert [entity["text"] for entity in content["entities"]] == [
        "Max Mustermann",
        "Wien",
        "Erika Musterfrau",
    ]
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
    assert content["profile"] == "custom"
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
    assert response.json()["content"]["profile"] == "structured-only"


def test_post_rejects_dev_override_when_disabled(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Kontakt max@example.at")
    pii_fake.results["Kontakt max@example.at"] = [_entity("EMAIL_ADDRESS", 8, 22, 1.0)]

    response = client.post(
        f"/api/documents/{document_id}/pii",
        json={"pii_profile": "review-heavy"},
    )

    assert response.status_code == 403


def test_post_without_body_continues_to_work_when_dev_gate_is_enabled(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    settings.enable_dev_engine_settings = True
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Kontakt max@example.at")
    pii_fake.results["Kontakt max@example.at"] = [_entity("EMAIL_ADDRESS", 8, 22, 1.0)]

    response = client.post(f"/api/documents/{document_id}/pii")

    assert response.status_code == 201
    assert response.json()["content"]["engine_settings"] == {
        "pii_profile": "custom",
        "candidate_validation_enabled": True,
        "score_threshold": 0.5,
        "source": "server-default",
    }


@pytest.mark.parametrize(
    "profile",
    ["structured-only", "insurance-at-de", "broad-review", "review-heavy"],
)
def test_post_accepts_dev_profile_override_when_enabled_for_all_profiles(
    profile: str,
    client: TestClient,
    settings: Settings,
    pii_fake: FakePiiAnalyzer,
) -> None:
    settings.enable_dev_engine_settings = True
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Kontakt max@example.at")
    pii_fake.results["Kontakt max@example.at"] = [_entity("EMAIL_ADDRESS", 8, 22, 1.0)]

    response = client.post(
        f"/api/documents/{document_id}/pii",
        json={"pii_profile": profile},
    )

    assert response.status_code == 201
    assert pii_fake.entity_types_seen == [get_pii_profile(profile).entity_types]
    assert response.json()["content"]["engine_settings"] == {
        "pii_profile": profile,
        "candidate_validation_enabled": True,
        "score_threshold": 0.5,
        "source": "dev-ui-override",
    }


def test_post_rejects_unknown_dev_profile(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Kontakt max@example.at")

    response = client.post(
        f"/api/documents/{document_id}/pii",
        json={"pii_profile": "maximum-everything"},
    )

    assert response.status_code == 422


def test_missing_text_result_returns_409(
    client: TestClient, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)

    response = client.post(f"/api/documents/{upload['id']}/pii")

    assert response.status_code == 409


def test_invalid_text_result_returns_409(
    client: TestClient, document_data_dir: Path, pii_fake: FakePiiAnalyzer
) -> None:
    upload = _upload_document(client)
    directory = document_data_dir / str(upload["id"]) / "artifacts"
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
    document_data_dir: Path,
    pii_fake: FakePiiAnalyzer,
) -> None:
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, "Anna")
    pii_fake.results["Anna"] = [_entity("PERSON", 0, 4)]
    assert client.post(f"/api/documents/{document_id}/pii").status_code == 201
    artifact_directory = document_data_dir / document_id / "artifacts"
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


# --- Engine-5 candidate validation integration ---------------------------------------------------


def test_dropped_candidate_is_excluded_from_final_entities_and_counted(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    text = "Für Kontakt max@example.at"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("PERSON", 0, 3),  # "Für" — function word, obvious false positive
        _entity("EMAIL_ADDRESS", 12, 26),  # "max@example.at"
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert [entity["entity_type"] for entity in content["entities"]] == ["EMAIL_ADDRESS"]
    assert content["entity_counts"] == {"EMAIL_ADDRESS": 1}
    assert content["validation"]["enabled"] is True
    assert content["validation"]["dropped"] == 1
    assert content["validation"]["dropped_by_reason"] == {"FUNCTION_WORD_ONLY": 1}
    assert content["validation"]["kept"] == 1


def test_score_down_candidate_is_excluded_by_default_threshold_but_counted(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    text = "Musterhaft"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [_entity("PERSON", 0, len(text), 0.85)]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert content["entities"] == []
    assert content["validation"]["score_down"] == 1
    assert content["validation"]["dropped"] == 0
    assert content["validation"]["score_down_by_reason"] == {"MISSING_REQUIRED_CONTEXT": 1}


def test_structured_only_profile_is_stable_under_validation(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    settings.pii_profile = "structured-only"
    settings.pii_entity_types = (
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "URL",
    )
    text = "Kontakt max@example.at"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [_entity("EMAIL_ADDRESS", 8, 22, 0.6)]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert content["profile"] == "structured-only"
    assert len(content["entities"]) == 1
    assert content["entities"][0]["score"] == 0.6
    assert content["validation"]["dropped"] == 0
    assert content["validation"]["score_down"] == 0


def test_insurance_at_de_domain_types_stay_stable_bic_gets_moderate_check(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    settings.pii_profile = "insurance-at-de"
    settings.pii_entity_types = ("EMAIL_ADDRESS", "PHONE_NUMBER", "URL", "POLICY_NUMBER", "BIC")
    text = "Polizzennummer POL-KFZ-2026-00871 Kennung ABCDEFGH"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("POLICY_NUMBER", 15, 33, 0.7),  # POL-KFZ-2026-00871 — unaffected light type
        _entity("BIC", 42, 50, 0.7),  # ABCDEFGH — no bank/BIC/IBAN context word nearby
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    entities_by_type = {entity["entity_type"]: entity for entity in content["entities"]}
    assert entities_by_type["POLICY_NUMBER"]["score"] == 0.7
    assert entities_by_type["POLICY_NUMBER"]["validation_status"] == "kept"
    # BIC has no adjacent bank/BIC/IBAN keyword here, so it is scored down (not hard-dropped).
    assert content["validation"]["score_down_by_reason"] == {"BIC_WITHOUT_FINANCIAL_CONTEXT": 1}


def test_broad_review_profile_applies_validation_to_organization(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    settings.pii_entity_types = (
        "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "IP_ADDRESS", "URL",
        "PERSON", "ORGANIZATION", "LOCATION",
    )
    text = "Rechnung von Muster GmbH"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("ORGANIZATION", 0, 8),  # "Rechnung" — generic document word
        _entity("ORGANIZATION", 13, 24),  # "Muster GmbH" — has a company-form signal
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert [entity["text"] for entity in content["entities"]] == ["Muster GmbH"]
    assert content["validation"]["dropped_by_reason"] == {"GENERIC_DOCUMENT_WORD": 1}


def test_review_heavy_profile_applies_validation_to_date_time(
    client: TestClient, settings: Settings, pii_fake: FakePiiAnalyzer
) -> None:
    settings.pii_entity_types = (
        "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "IP_ADDRESS", "URL",
        "PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME",
    )
    # The two dates are kept far enough apart (> the 60-char context window) that the unrelated
    # "Geburtsdatum" label cannot leak into the bare year's context window.
    text = (
        "Geschaeftsjahr 2025 ist im internen Vermerk ohne weiteren Bezug eingetragen worden "
        "heute. Geburtsdatum 12.04.1980"
    )
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, text)
    pii_fake.results[text] = [
        _entity("DATE_TIME", 15, 19, 0.85),  # "2025" — bare year, no date-role context nearby
        _entity("DATE_TIME", 103, 113, 0.85),  # "12.04.1980" — has "Geburtsdatum" context
    ]

    response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert [entity["text"] for entity in content["entities"]] == ["12.04.1980"]
    assert content["validation"]["score_down_by_reason"] == {"DATE_YEAR_ONLY": 1}


def test_validation_summary_and_reasons_never_contain_the_raw_secret(
    client: TestClient,
    settings: Settings,
    pii_fake: FakePiiAnalyzer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "VerySecretUnlabelledName"
    upload = _upload_document(client)
    document_id = str(upload["id"])
    _save_text(settings, document_id, secret)
    pii_fake.results[secret] = [_entity("PERSON", 0, len(secret), 0.85)]

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.post(f"/api/documents/{document_id}/pii")

    content = response.json()["content"]
    assert response.status_code == 201
    assert content["entities"] == []
    assert content["validation"]["score_down"] == 1
    known_reason_codes = {
        "STOPWORD_ONLY", "FUNCTION_WORD_ONLY", "GENERIC_DOCUMENT_WORD",
        "TOO_SHORT_SINGLE_TOKEN", "NUMERIC_ONLY_FOR_NER", "MISSING_REQUIRED_CONTEXT",
        "LOW_SHAPE_CONFIDENCE", "NER_SINGLE_COMMON_WORD", "DATE_YEAR_ONLY",
        "ORG_WITHOUT_ORG_SIGNAL", "LOCATION_WITHOUT_LOCATION_SIGNAL",
        "BIC_WITHOUT_FINANCIAL_CONTEXT",
    }
    assert set(content["validation"]["score_down_by_reason"]).issubset(known_reason_codes)
    assert secret not in str(content["validation"])
    assert all(secret not in record.getMessage() for record in caplog.records)
