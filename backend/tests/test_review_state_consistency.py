"""Regression tests: one coherent Review state for current vs. stale review decisions.

All data is synthetic. These tests pin the consistency contract between the aggregate
staleness signal (``stale_decision_count``/``has_stale_decisions``) and the per-item view:

- a review item that is counted as stale must also be itemized (``stale_decisions``) and must
  never be presented as an active current decision (manual-addition ``artifact_currency``,
  group-level ``stale_decision``);
- compatible current decisions keep working exactly as before;
- staleness reporting never mutates ``pii_result`` or text artifacts.
"""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.schemas import (
    PiiArtifact,
    PiiContent,
    PiiEntity,
    PiiValidationSummary,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)
from app.services.artifact_service import (
    get_pii_artifact,
    get_text_artifact,
    save_pii_artifact,
    save_text_artifact,
)

_REVIEW_URL = "/api/documents/{document_id}/pii/review"
_DECISIONS_URL = "/api/documents/{document_id}/pii/review/decisions"
_MANUAL_ADDITIONS_URL = "/api/documents/{document_id}/pii/review/manual-additions"
_PII_URL = "/api/documents/{document_id}/pii"
_OCR_URL = "/api/documents/{document_id}/ocr"

_RAW = "Hans Mueller wohnt in Wien. Peter Schmidt kommt aus Graz."
_WIEN_START, _WIEN_END = 22, 26


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload_document(client: TestClient) -> str:
    response = client.post(
        "/api/uploads", files={"file": ("source.pdf", _pdf_bytes(), "application/pdf")}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _entity(entity_type: str, text: str, start: int, *, score: float = 0.9) -> PiiEntity:
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=start + len(text),
        score=score,
        recognizer="TestRecognizer",
    )


def _save_text(
    settings: Settings,
    document_id: str,
    *,
    text_id: str,
    raw: str,
    reading_text: str | None,
    created_at: str = "2026-07-11T09:00:00.000000Z",
) -> None:
    reading_map = (
        [
            ReadingTextMapSegment(
                reading_start=0,
                reading_end=len(reading_text),
                raw_start=0,
                raw_end=len(raw),
                mapping_status="exact",
            )
        ]
        if reading_text is not None and len(reading_text) == len(raw)
        else []
    )
    content = TextContent(
        document_id=document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version=("1" if reading_text is not None else None),
        reading_text=reading_text,
        reading_text_status=("heuristic" if reading_text is not None else None),
        reading_text_map_version=("1" if reading_text is not None else None),
        reading_text_map=reading_map,
    )
    artifact = TextArtifact(
        id=text_id,
        document_id=document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        created_at=created_at,
        content=content,
    )
    save_text_artifact(settings, artifact)


def _save_pii(
    settings: Settings,
    document_id: str,
    entities: list[PiiEntity],
    *,
    input_text_artifact_id: str,
    raw: str = _RAW,
    reading_text_char_count: int | None = None,
    created_at: str = "2026-07-11T10:00:00.000001Z",
) -> PiiArtifact:
    configured_types = sorted({entity.entity_type for entity in entities}) or ["LOCATION"]
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    content = PiiContent(
        document_id=document_id,
        input_text_artifact_id=input_text_artifact_id,
        profile="custom",
        language="de",
        score_threshold=0.5,
        text_char_count=len(raw),
        reading_text_char_count=reading_text_char_count,
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
        input_text_artifact_id=input_text_artifact_id,
        created_at=created_at,
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def _detected_entities() -> list[PiiEntity]:
    return [
        _entity("PERSON", "Hans Mueller", 0),
        _entity("LOCATION", "Graz", 52),
    ]


def _setup_run(
    settings: Settings,
    document_id: str,
    *,
    text_created_at: str = "2026-07-11T09:00:00.000000Z",
    pii_created_at: str = "2026-07-11T10:00:00.000001Z",
) -> tuple[str, PiiArtifact]:
    text_id = uuid4().hex
    _save_text(
        settings,
        document_id,
        text_id=text_id,
        raw=_RAW,
        reading_text=_RAW,
        created_at=text_created_at,
    )
    artifact = _save_pii(
        settings,
        document_id,
        _detected_entities(),
        input_text_artifact_id=text_id,
        reading_text_char_count=len(_RAW),
        created_at=pii_created_at,
    )
    return text_id, artifact


def _decision(
    client: TestClient, document_id: str, target_type: str, target_id: str, value: str
) -> None:
    response = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={"target_type": target_type, "target_id": target_id, "decision": value},
    )
    assert response.status_code == 201


# --- stale detector decisions ---------------------------------------------------------------


def test_stale_group_decision_is_itemized_and_correlated_to_current_group(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _, first_pii = _setup_run(settings, document_id)
    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    person_group = next(g for g in review["groups"] if g["entity_type"] == "PERSON")
    _decision(client, document_id, "entity_group", person_group["entity_group_id"], "keep")

    # PII re-run over the same text: same values are detected again, so group ids repeat, but the
    # decision was recorded against the superseded artifact and must not silently reapply.
    _setup_run(
        settings,
        document_id,
        text_created_at="2026-07-11T11:00:00.000000Z",
        pii_created_at="2026-07-11T12:00:00.000001Z",
    )
    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()

    # Aggregate signal and itemization must agree.
    assert review_after["stale_decision_count"] == 1
    assert review_after["has_stale_decisions"] is True
    stale_items = review_after["stale_decisions"]
    assert len(stale_items) == review_after["stale_decision_count"]
    item = stale_items[0]
    assert item["target_type"] == "entity_group"
    assert item["target_id"] == person_group["entity_group_id"]
    assert item["decision"] == "keep"
    assert item["artifact_id"] == first_pii.id

    # The current group must not carry the stale decision as its active state...
    current_person = next(g for g in review_after["groups"] if g["entity_type"] == "PERSON")
    assert current_person["review_decision"] is None
    assert current_person["review_status"] == "accepted"
    # ...but must surface it explicitly as a superseded previous decision.
    assert current_person["stale_decision"] == "keep"
    assert current_person["stale_decision_recorded_at"] == item["recorded_at"]

    # Groups without any previous decision carry no stale marker.
    current_location = next(g for g in review_after["groups"] if g["entity_type"] == "LOCATION")
    assert current_location["stale_decision"] is None


def test_redeciding_a_group_in_the_current_run_clears_its_staleness(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _setup_run(settings, document_id)
    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    person_group = next(g for g in review["groups"] if g["entity_type"] == "PERSON")
    _decision(client, document_id, "entity_group", person_group["entity_group_id"], "keep")

    _setup_run(
        settings,
        document_id,
        text_created_at="2026-07-11T11:00:00.000000Z",
        pii_created_at="2026-07-11T12:00:00.000001Z",
    )
    review_stale = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert review_stale["stale_decision_count"] == 1

    # Re-deciding the same (deterministic) group id against the current run supersedes the stale
    # line for that target and the current decision applies normally.
    current_person = next(g for g in review_stale["groups"] if g["entity_type"] == "PERSON")
    _decision(
        client, document_id, "entity_group", current_person["entity_group_id"], "false_positive"
    )
    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()

    assert review_after["stale_decision_count"] == 0
    assert review_after["has_stale_decisions"] is False
    assert review_after["stale_decisions"] == []
    person_after = next(g for g in review_after["groups"] if g["entity_type"] == "PERSON")
    assert person_after["review_decision"] == "false_positive"
    assert person_after["review_status"] == "rejected"
    assert person_after["stale_decision"] is None


def test_stale_occurrence_decision_is_itemized_without_group_correlation(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _setup_run(settings, document_id)
    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    occurrence_id = review["occurrences"][0]["occurrence_id"]
    _decision(client, document_id, "occurrence", occurrence_id, "false_positive")

    _setup_run(
        settings,
        document_id,
        text_created_at="2026-07-11T11:00:00.000000Z",
        pii_created_at="2026-07-11T12:00:00.000001Z",
    )
    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()

    assert review_after["stale_decision_count"] == 1
    assert len(review_after["stale_decisions"]) == 1
    item = review_after["stale_decisions"][0]
    assert item["target_type"] == "occurrence"
    assert item["target_id"] == occurrence_id
    assert item["decision"] == "false_positive"
    # Occurrence ids are new uuids per run, so no current occurrence may inherit the old decision.
    for occurrence in review_after["occurrences"]:
        assert occurrence["occurrence_id"] != occurrence_id
        assert occurrence["review_decision"] is None
        assert occurrence["review_status"] == "accepted"


# --- stale manual additions -----------------------------------------------------------------


def test_stale_manual_addition_is_marked_stale_and_itemized(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _setup_run(settings, document_id)
    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json={
            "entity_type": "LOCATION",
            "canonical_start": _WIEN_START,
            "canonical_end": _WIEN_END,
        },
    )
    assert response.status_code == 201
    addition_id = response.json()["addition_id"]

    review_before = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    addition_before = review_before["manual_additions"][0]
    assert addition_before["artifact_currency"] == "current"
    assert review_before["stale_decision_count"] == 0

    # A new text artifact (OCR re-run) supersedes the addition's offsets basis.
    _setup_run(
        settings,
        document_id,
        text_created_at="2026-07-11T11:00:00.000000Z",
        pii_created_at="2026-07-11T12:00:00.000001Z",
    )
    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()

    assert review_after["stale_decision_count"] == 1
    stale_items = review_after["stale_decisions"]
    assert len(stale_items) == 1
    assert stale_items[0]["target_type"] == "manual_addition"
    assert stale_items[0]["target_id"] == addition_id
    assert stale_items[0]["entity_type"] == "LOCATION"

    # The addition remains listed for audit/history, but is explicitly stale — the frontend must
    # not render it as an active highlight or active decision.
    addition_after = next(
        a for a in review_after["manual_additions"] if a["addition_id"] == addition_id
    )
    assert addition_after["artifact_currency"] == "stale"

    # Entries (Review Result v1) agree with the itemization.
    entry = next(e for e in review_after["entries"] if e["entry_id"] == addition_id)
    assert entry["artifact_currency"] == "stale"


def test_current_manual_addition_and_decisions_keep_working(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _setup_run(settings, document_id)
    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json={
            "entity_type": "LOCATION",
            "canonical_start": _WIEN_START,
            "canonical_end": _WIEN_END,
        },
    )
    assert response.status_code == 201
    addition_id = response.json()["addition_id"]
    _decision(client, document_id, "manual_addition", addition_id, "keep")

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    addition = review["manual_additions"][0]
    assert addition["artifact_currency"] == "current"
    assert addition["review_decision"] == "keep"
    assert addition["review_status"] == "kept"
    assert review["stale_decision_count"] == 0
    assert review["stale_decisions"] == []


# --- invariants -----------------------------------------------------------------------------


def test_staleness_reporting_does_not_mutate_pii_or_text_artifacts(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    first_text_id, first_pii = _setup_run(settings, document_id)
    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    group_id = review["groups"][0]["entity_group_id"]
    _decision(client, document_id, "entity_group", group_id, "keep")

    pii_before = get_pii_artifact(settings, document_id, first_pii.id)
    text_before = get_text_artifact(settings, document_id, first_text_id)
    assert pii_before is not None and text_before is not None

    _setup_run(
        settings,
        document_id,
        text_created_at="2026-07-11T11:00:00.000000Z",
        pii_created_at="2026-07-11T12:00:00.000001Z",
    )
    # Reading the (now stale-carrying) review view must not change any stored artifact.
    stale_review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert stale_review["has_stale_decisions"] is True

    pii_after = get_pii_artifact(settings, document_id, first_pii.id)
    text_after = get_text_artifact(settings, document_id, first_text_id)
    assert pii_after == pii_before
    assert text_after == text_before
