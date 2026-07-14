"""Integration tests for manual add of missed PII entities (PII L14 / Review L10, ADR-0035).

All data is synthetic. These tests exercise ``POST …/pii/review/manual-additions`` end to end:
creation, the best-effort canonical→raw reverse projection (exact and unmapped), validation errors,
round-tripping through ``GET …/pii/review`` (never merged into ``occurrences``/``groups``),
deciding a manual addition through the existing decisions endpoint, staleness after a new text
artifact, and the invariant that no request or response ever carries raw document text.
"""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from tests.artifact_helpers import save_pii_artifact, save_text_artifact

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

_MANUAL_ADDITIONS_URL = "/api/documents/{document_id}/pii/review/manual-additions"
_REVIEW_URL = "/api/documents/{document_id}/pii/review"
_DECISIONS_URL = "/api/documents/{document_id}/pii/review/decisions"
_PII_URL = "/api/documents/{document_id}/pii"

_RAW = "Hans Mueller wohnt in Wien. Peter Schmidt kommt aus Graz."
# "Wien" (genuinely missed by the two detected entities below) and "Graz" (already detected).
_WIEN_START, _WIEN_END = 22, 26
_GRAZ_START, _GRAZ_END = 52, 56


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
    map_reading: bool = True,
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
        if map_reading and reading_text is not None and len(reading_text) == len(raw)
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
    input_text_artifact_id: str = "a" * 32,
    text_char_count: int = 500,
    reading_text_char_count: int | None = None,
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
        text_char_count=text_char_count,
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
        created_at="2026-07-11T10:00:00.000001Z",
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def _save_pii_over_text(
    settings: Settings,
    document_id: str,
    raw: str,
    entities: list[PiiEntity],
    *,
    reading_text: str | None,
    map_reading: bool = True,
) -> str:
    text_id = uuid4().hex
    _save_text(
        settings,
        document_id,
        text_id=text_id,
        raw=raw,
        reading_text=reading_text,
        map_reading=map_reading,
    )
    _save_pii(
        settings,
        document_id,
        entities,
        input_text_artifact_id=text_id,
        text_char_count=len(raw),
        reading_text_char_count=(len(reading_text) if reading_text is not None else None),
    )
    return text_id


def _detected_entities() -> list[PiiEntity]:
    return [
        _entity("PERSON", "Hans Mueller", 0),
        _entity("LOCATION", "Graz", _GRAZ_START),
    ]


def _addition_payload(entity_type: str, start: int, end: int) -> dict[str, object]:
    return {"entity_type": entity_type, "canonical_start": start, "canonical_end": end}


def test_manual_addition_exact_reverse_projection(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recorded"] is True
    assert body["entity_type"] == "LOCATION"
    assert body["canonical_start"] == _WIEN_START
    assert body["canonical_end"] == _WIEN_END
    assert body["raw_projection_status"] == "exact"


def test_manual_addition_unmapped_reverse_projection_still_creates(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings, document_id, _RAW, _detected_entities(), reading_text=_RAW, map_reading=False
    )

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_projection_status"] == "unmapped"

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    addition = review["manual_additions"][0]
    assert addition["raw_start"] is None
    assert addition["raw_end"] is None


def test_manual_addition_out_of_bounds_offsets_returns_422(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", 0, len(_RAW) + 100),
    )

    assert response.status_code == 422


def test_manual_addition_inverted_offsets_returns_422(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", 10, 5),
    )

    assert response.status_code == 422


def test_manual_addition_unconfigured_entity_type_returns_422(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("ORGANIZATION", _WIEN_START, _WIEN_END),
    )

    assert response.status_code == 422


def test_manual_addition_without_pii_result_returns_404(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", 0, 4),
    )

    assert response.status_code == 404


def test_manual_addition_without_text_result_returns_404(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, _detected_entities())  # no matching text artifact saved

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", 0, 4),
    )

    assert response.status_code == 404


def test_manual_addition_round_trips_through_review_and_never_in_occurrences(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    created = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    ).json()

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert len(review["manual_additions"]) == 1
    addition = review["manual_additions"][0]
    assert addition["addition_id"] == created["addition_id"]
    assert addition["origin"] == "human"
    assert addition["review_status"] == "accepted"
    assert len(review["occurrences"]) == 2
    occurrence_ids = {occurrence["occurrence_id"] for occurrence in review["occurrences"]}
    assert created["addition_id"] not in occurrence_ids


def test_manual_addition_decision_resolves_through_existing_endpoint(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)
    created = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    ).json()

    decision_response = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={
            "target_type": "manual_addition",
            "target_id": created["addition_id"],
            "decision": "false_positive",
        },
    )
    assert decision_response.status_code == 201

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    addition = review["manual_additions"][0]
    assert addition["review_status"] == "rejected"
    assert addition["review_decision"] == "false_positive"


def test_manual_addition_becomes_stale_after_new_text_artifact(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)
    created = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    ).json()

    review_before = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert review_before["has_stale_decisions"] is False

    # Simulate a later OCR/Text re-run: a new text artifact for the same document.
    _save_text(
        settings,
        document_id,
        text_id=uuid4().hex,
        raw=_RAW,
        reading_text=_RAW,
        created_at="2026-07-11T09:05:00.000000Z",
    )

    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert review_after["has_stale_decisions"] is True
    assert review_after["stale_decision_count"] >= 1
    # The manual addition itself is still shown, not silently dropped.
    assert len(review_after["manual_additions"]) == 1

    # A new decision can no longer target the now-stale addition.
    stale_decision_response = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={
            "target_type": "manual_addition",
            "target_id": created["addition_id"],
            "decision": "keep",
        },
    )
    assert stale_decision_response.status_code == 404


def test_manual_addition_request_and_responses_never_carry_raw_text(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)

    response = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    )
    review = client.get(_REVIEW_URL.format(document_id=document_id))

    for payload in (response.text, review.text):
        assert "Wien" not in payload
        assert "Hans" not in payload
        assert "Graz" not in payload


def test_manual_addition_never_mutates_pii_result(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, _RAW, _detected_entities(), reading_text=_RAW)
    before = client.get(_PII_URL.format(document_id=document_id)).json()

    client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json=_addition_payload("LOCATION", _WIEN_START, _WIEN_END),
    )

    after = client.get(_PII_URL.format(document_id=document_id)).json()
    assert before == after
