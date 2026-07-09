"""Integration tests for the review-ready PII entity contract (ADR-0029).

All data is synthetic. The review-ready contract is a pure, derived view over a persisted
``pii_result`` and (optionally) its text artifact: it connects each entity to the technical raw text
and canonical reading text with an explicit mapping status, a stable entity id, deterministic
overlap provenance, the resolved review state, and a text-free display model. These tests exercise
the additive ``GET …/pii/entity-contract`` endpoint end to end and assert backward compatibility of
the existing PII/review routes plus the privacy invariants (no context snippet leaks into display,
warnings, or provenance).
"""

from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.schemas import (
    PiiArtifact,
    PiiContent,
    PiiEntity,
    PiiEntityProvenance,
    PiiValidationSummary,
    TextArtifact,
    TextContent,
)
from app.services.artifact_service import save_pii_artifact, save_text_artifact

_CONTRACT_URL = "/api/documents/{document_id}/pii/entity-contract"


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


def _entity(
    entity_type: str,
    text: str,
    start: int,
    *,
    score: float = 0.9,
    recognizer: str = "TestRecognizer",
    projection_status: str | None = None,
    projection_method: str | None = None,
    reading_start: int | None = None,
    reading_end: int | None = None,
    provenance: PiiEntityProvenance | None = None,
) -> PiiEntity:
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=start + len(text),
        score=score,
        recognizer=recognizer,
        projection_status=projection_status,
        projection_method=projection_method,
        reading_start_offset=reading_start,
        reading_end_offset=reading_end,
        provenance=provenance,
    )


def _save_pii(
    settings: Settings,
    document_id: str,
    entities: list[PiiEntity],
    *,
    input_text_artifact_id: str = "a" * 32,
    reading_text_char_count: int | None = None,
    text_char_count: int = 500,
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
        created_at="2026-07-09T10:00:00.000001Z",
        content=content,
    )
    save_pii_artifact(settings, artifact)
    return artifact


def _save_text(
    settings: Settings, document_id: str, *, text_id: str, raw: str, reading_text: str | None
) -> None:
    """Persist a minimal DOCX-style text artifact so the builder can read canonical reading text."""
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
    )
    artifact = TextArtifact(
        id=text_id,
        document_id=document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        created_at="2026-07-09T09:00:00.000000Z",
        content=content,
    )
    save_text_artifact(settings, artifact)


def _get_contract(client: TestClient, document_id: str) -> dict[str, object]:
    response = client.get(_CONTRACT_URL.format(document_id=document_id))
    assert response.status_code == 200
    return response.json()


# --- 404 / preconditions -------------------------------------------------------------------------


def test_unknown_document_returns_404(client: TestClient) -> None:
    assert client.get(_CONTRACT_URL.format(document_id="0" * 32)).status_code == 404


def test_document_without_pii_result_returns_404(client: TestClient) -> None:
    document_id = _upload_document(client)
    assert client.get(_CONTRACT_URL.format(document_id=document_id)).status_code == 404


# --- raw span + baseline shape -------------------------------------------------------------------


def test_every_entity_carries_a_raw_span_and_stable_shape(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 10)])

    body = _get_contract(client, document_id)

    assert body["contract_version"] == "1.0"
    assert body["document_id"] == document_id
    assert len(body["entities"]) == 1
    entity = body["entities"][0]
    assert entity["entity_type"] == "LOCATION"
    assert entity["value"] == "Wien"
    assert entity["raw_text_range"] == {
        "start": 10,
        "end": 14,
        "page_number": None,
        "page_start": None,
        "page_end": None,
    }
    assert entity["detection_source"] == "raw_text"
    assert entity["source_role"] == "primary"
    assert entity["display"]["raw_highlight_range"] == {"start": 10, "end": 14}
    assert entity["display"]["display_label"] == "LOCATION"


# --- mapping status: exact / projected -----------------------------------------------------------


def test_exact_offset_mapping_yields_exact_status_and_canonical_range(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity(
        "LOCATION",
        "Wien",
        0,
        projection_status="exact",
        projection_method="offset_map",
        reading_start=0,
        reading_end=4,
    )
    _save_pii(settings, document_id, [entity], reading_text_char_count=40)

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["mapping_status"] == "exact"
    assert entity_out["canonical_reading_text_range"] == {
        "start": 0,
        "end": 4,
        "projection_method": "offset_map",
    }
    assert entity_out["display"]["preferred_text_source"] == "canonical_reading_text"
    assert entity_out["display"]["canonical_highlight_range"] == {"start": 0, "end": 4}
    assert entity_out["display"]["display_context_available"] is True
    assert entity_out["display"]["needs_review"] is False
    assert entity_out["display"]["review_reason_codes"] == []


def test_text_match_projection_yields_projected_status(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity(
        "LOCATION",
        "Wien",
        0,
        projection_status="exact",
        projection_method="text_match",
        reading_start=5,
        reading_end=9,
    )
    _save_pii(settings, document_id, [entity], reading_text_char_count=40)

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["mapping_status"] == "projected"
    assert entity_out["canonical_reading_text_range"]["projection_method"] == "text_match"
    assert entity_out["display"]["needs_review"] is False


# --- mapping status: partial / missing / ambiguous / not_applicable ------------------------------


def test_partial_projection_needs_review_without_canonical_range(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity("LOCATION", "Wien", 0, projection_status="partial")
    _save_pii(settings, document_id, [entity], reading_text_char_count=40)

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["mapping_status"] == "partial"
    assert entity_out["canonical_reading_text_range"] is None
    assert entity_out["display"]["preferred_text_source"] == "technical_raw_text"
    assert entity_out["display"]["needs_review"] is True
    assert entity_out["display"]["review_reason_codes"] == ["canonical_mapping_partial"]
    assert "canonical_mapping_partial" in entity_out["warnings"]


def test_unmapped_entity_with_canonical_text_is_missing_not_dropped(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    # Canonical reading text exists for the run, but no matching text artifact is stored, so the
    # builder cannot count occurrences: an unmapped entity stays reviewable as "missing".
    entity = _entity("LOCATION", "Wien", 0, projection_status="unmapped")
    _save_pii(settings, document_id, [entity], reading_text_char_count=40)

    body = _get_contract(client, document_id)

    assert len(body["entities"]) == 1  # never dropped
    entity_out = body["entities"][0]
    assert entity_out["mapping_status"] == "missing"
    assert entity_out["display"]["needs_review"] is True
    assert entity_out["display"]["review_reason_codes"] == ["canonical_mapping_missing"]


def test_unmapped_entity_appearing_twice_in_reading_text_is_ambiguous(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    text_id = "e" * 32
    _save_text(
        settings, document_id, text_id=text_id, raw="Wien Wien", reading_text="Wien und Wien"
    )
    entity = _entity("LOCATION", "Wien", 0, projection_status="unmapped")
    _save_pii(
        settings,
        document_id,
        [entity],
        input_text_artifact_id=text_id,
        reading_text_char_count=13,
    )

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["mapping_status"] == "ambiguous"
    assert entity_out["display"]["needs_review"] is True
    assert entity_out["display"]["review_reason_codes"] == ["canonical_mapping_ambiguous"]


def test_no_canonical_text_is_not_applicable_and_not_flagged(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity("LOCATION", "Wien", 0)  # unmapped, no canonical text for the run
    _save_pii(settings, document_id, [entity], reading_text_char_count=None)

    body = _get_contract(client, document_id)

    assert body["reading_text_available"] is False
    entity_out = body["entities"][0]
    assert entity_out["mapping_status"] == "not_applicable"
    assert entity_out["display"]["needs_review"] is False
    assert entity_out["display"]["review_reason_codes"] == []
    assert entity_out["display"]["preferred_text_source"] == "technical_raw_text"


def test_mapping_summary_and_needs_review_count_are_consistent(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _entity(
            "LOCATION", "Wien", 0, projection_status="exact",
            projection_method="offset_map", reading_start=0, reading_end=4,
        ),
        _entity("PERSON", "Max", 10, projection_status="partial"),
        _entity("ORGANIZATION", "ACME", 20, projection_status="unmapped"),
    ]
    _save_pii(settings, document_id, entities, reading_text_char_count=40)

    body = _get_contract(client, document_id)

    assert body["mapping_summary"] == {
        "exact": 1,
        "projected": 0,
        "partial": 1,
        "missing": 1,
        "ambiguous": 0,
        "not_applicable": 0,
    }
    assert body["needs_review_count"] == 2


# --- stable entity ids ---------------------------------------------------------------------------


def test_entity_id_is_stable_across_requests_and_reruns(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 7)])
    first = _get_contract(client, document_id)["entities"][0]["entity_id"]
    second = _get_contract(client, document_id)["entities"][0]["entity_id"]
    assert first == second

    # A fresh detection run (new artifact + occurrence id) for the same span/type keeps the id.
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 7)])
    rerun = _get_contract(client, document_id)
    assert rerun["entities"][0]["entity_id"] == first
    assert rerun["entities"][0]["source_entity_id"] != first  # occurrence id is volatile, id is not


def test_entity_id_differs_by_type_and_span(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    entities = [
        _entity("LOCATION", "Wien", 0),
        _entity("PERSON", "Wien", 30),
    ]
    _save_pii(settings, document_id, entities)

    ids = {entity["entity_id"] for entity in _get_contract(client, document_id)["entities"]}
    assert len(ids) == 2


# --- overlap provenance surfacing ----------------------------------------------------------------


def test_cross_type_review_flag_is_surfaced_as_needs_review(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    provenance = PiiEntityProvenance(
        detection_source="raw_text",
        source_role="primary",
        recognizers=["R1"],
        overlap_decision="conflicting_entity_type",
        review_required=True,
    )
    entity = _entity("PERSON", "Max", 0, provenance=provenance)
    _save_pii(settings, document_id, [entity])

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["display"]["needs_review"] is True
    assert set(entity_out["display"]["review_reason_codes"]) == {
        "conflicting_entity_type",
        "ambiguous_overlap_review_required",
    }
    assert entity_out["overlap_decision"] == "conflicting_entity_type"


def test_merged_duplicate_provenance_is_surfaced_as_warning_only(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    provenance = PiiEntityProvenance(
        detection_source="raw_text",
        source_role="primary",
        recognizers=["RegexA", "RegexB"],
        candidate_count=2,
        merge_reason="recognizer_duplicate",
        overlap_decision="merged_provenance",
        superseded_candidate_ids=["b" * 32],
    )
    entity = _entity("EMAIL_ADDRESS", "max@example.at", 0, provenance=provenance)
    _save_pii(settings, document_id, [entity])

    entity_out = _get_contract(client, document_id)["entities"][0]

    # A merge is informational: it appears in warnings but does not force review on its own.
    assert entity_out["display"]["needs_review"] is False
    assert "merged_provenance" in entity_out["warnings"]
    assert "recognizer_duplicate" in entity_out["warnings"]
    assert entity_out["provenance"]["superseded_candidate_ids"] == ["b" * 32]


# --- review state reflects the existing decision overlay -----------------------------------------


def test_review_decision_is_reflected_in_review_state(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 0)])
    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    group_id = review["groups"][0]["entity_group_id"]
    occurrence_id = review["occurrences"][0]["occurrence_id"]

    client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json={"target_type": "entity_group", "target_id": group_id, "decision": "false_positive"},
    )

    entity_out = _get_contract(client, document_id)["entities"][0]
    assert entity_out["source_entity_id"] == occurrence_id
    assert entity_out["entity_group_id"] == group_id
    assert entity_out["review_state"] == "rejected"
    assert entity_out["review_decision"] == "false_positive"
    assert entity_out["decision_scope"] == "entity_group"


# --- backward compatibility ----------------------------------------------------------------------


def test_existing_pii_and_review_endpoints_are_unchanged(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 0)])

    pii = client.get(f"/api/documents/{document_id}/pii")
    assert pii.status_code == 200
    entity = pii.json()["content"]["entities"][0]
    assert entity["entity_type"] == "LOCATION"
    assert entity["text"] == "Wien"
    # The immutable artifact never grows the review-ready contract fields.
    assert "mapping_status" not in entity
    assert "entity_id" not in entity or entity.get("id") is not None

    review = client.get(f"/api/documents/{document_id}/pii/review")
    assert review.status_code == 200
    assert "entity-contract" not in review.text


# --- privacy: value confined, no context snippet leaks -------------------------------------------


def test_value_is_confined_and_no_context_snippet_leaks(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    secret = "geheim@example.at"
    entity = _entity("EMAIL_ADDRESS", secret, 0, projection_status="partial")
    _save_pii(settings, document_id, [entity], reading_text_char_count=40)

    response = client.get(_CONTRACT_URL.format(document_id=document_id))
    entity_out = response.json()["entities"][0]

    # The value appears only in the dedicated value field, never in display/warnings/provenance.
    assert entity_out["value"] == secret
    assert secret not in json.dumps(entity_out["display"])
    assert secret not in json.dumps(entity_out["warnings"])
    assert secret not in json.dumps(entity_out.get("provenance"))
    # Neighbour context words from the raw text are never sent by this endpoint at all.
    assert "Kontakt" not in response.text
