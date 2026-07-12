"""Integration tests for the anchor-bound review-ready PII entity contract (ADR-0031 Phase C).

All data is synthetic. The contract is a pure, derived view over a persisted ``pii_result`` and,
where available, the matching OCR/Text artifact's Text Anchor Graph v1: each entity is normalized
into an anchor-bound domain object whose identity derives from anchor identity when an exact binding
exists, while raw offsets, canonical ranges, and the value remain evidence/display. These tests
exercise the additive ``GET …/pii/entity-contract`` endpoint end to end and assert backward
compatibility of the existing PII/review routes plus the privacy invariants (no token text leaks
into binding metadata, display, warnings, provenance, or ids).
"""

from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from tests.artifact_helpers import save_pii_artifact, save_text_artifact

from app.config import Settings
from app.schemas import (
    DocumentTextAnchorGraphSummary,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorGraphValidation,
    DocumentTextAnchorRange,
    DocumentTextAnchorSource,
    DocumentTextAnchorV1,
    PiiArtifact,
    PiiContent,
    PiiEntity,
    PiiEntityProvenance,
    PiiValidationSummary,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)
from app.services.pii_overlap import resolve_pii_overlaps

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
    settings: Settings,
    document_id: str,
    *,
    text_id: str,
    raw: str,
    reading_text: str | None = None,
    layout_text: str | None = None,
    map_reading: bool = True,
) -> None:
    """Persist a minimal DOCX-style text artifact so the builder can derive a Text Anchor Graph."""
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
        layout_text_result=layout_text,
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


def _save_pii_over_text(
    settings: Settings,
    document_id: str,
    raw: str,
    entities: list[PiiEntity],
    *,
    reading_text: str | None = None,
    layout_text: str | None = None,
    map_reading: bool = True,
) -> str:
    """Save a matching text artifact plus a PII result whose offsets live in that raw text."""
    text_id = uuid4().hex
    _save_text(
        settings,
        document_id,
        text_id=text_id,
        raw=raw,
        reading_text=reading_text,
        layout_text=layout_text,
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


def _get_contract(client: TestClient, document_id: str) -> dict[str, object]:
    pii = client.get(f"/api/documents/{document_id}/pii").json()
    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={
            "pii_artifact_id": pii["id"],
            "text_artifact_id": pii["input_text_artifact_id"],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_entity_contract_uses_one_exact_snapshot_when_newer_artifacts_exist(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    old_text_id = "1" * 32
    new_text_id = "2" * 32
    _save_text(settings, document_id, text_id=old_text_id, raw="Alpha Person")
    old_pii = _save_pii(
        settings,
        document_id,
        [_entity("PERSON", "Alpha Person", 0)],
        input_text_artifact_id=old_text_id,
        text_char_count=len("Alpha Person"),
    )
    _save_text(settings, document_id, text_id=new_text_id, raw="Beta Place")
    _save_pii(
        settings,
        document_id,
        [_entity("LOCATION", "Beta Place", 0)],
        input_text_artifact_id=new_text_id,
        text_char_count=len("Beta Place"),
    )

    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": old_pii.id, "text_artifact_id": old_text_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pii_artifact_id"] == old_pii.id
    assert body["text_artifact_id"] == old_text_id
    assert [entity["value"] for entity in body["entities"]] == ["Alpha Person"]


def test_entity_contract_rejects_mixed_pii_and_text_snapshot(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_text(settings, document_id, text_id="1" * 32, raw="Alpha")
    pii = _save_pii(
        settings,
        document_id,
        [_entity("PERSON", "Alpha", 0)],
        input_text_artifact_id="1" * 32,
        text_char_count=5,
    )
    _save_text(settings, document_id, text_id="2" * 32, raw="Beta")

    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": pii.id, "text_artifact_id": "2" * 32},
    )

    assert response.status_code == 409


def test_partial_same_type_overlaps_survive_entity_contract(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    raw = "ABCDEFGHIJKLMNO"
    first = _entity("PERSON", raw[0:10], 0)
    second = _entity("PERSON", raw[5:15], 5)
    resolved, _summary = resolve_pii_overlaps([first, second])
    _save_pii_over_text(settings, document_id, raw, resolved)

    body = _get_contract(client, document_id)

    ranges = [
        (entity["raw_text_range"]["start"], entity["raw_text_range"]["end"])
        for entity in body["entities"]
    ]
    assert ranges == [
        (0, 10),
        (5, 15),
    ]
    assert all(entity["provenance"]["candidate_count"] == 1 for entity in body["entities"])


def _manual_overlapping_anchor_graph(document_id: str, text_id: str) -> DocumentTextAnchorGraphV1:
    """Synthetic raw-only graph for the endpoint's ambiguous-binding branch."""
    anchors = [
        DocumentTextAnchorV1(
            anchor_id=uuid4().hex,
            anchor_kind="word",
            anchor_status="single_source",
            source_ranges=[
                DocumentTextAnchorRange(
                    source_name="technical_raw_text",
                    start=start,
                    end=end,
                    range_role="primary",
                    mapping_status="exact",
                    confidence=1.0,
                )
            ],
            normalized_shape="alpha",
            token_class="alpha",
            confidence=1.0,
            flags=["raw_primary"],
            warnings=[],
        )
        for start, end in ((0, 5), (3, 8))
    ]
    warnings = ["missing_canonical_reading_text", "missing_layout_text"]
    return DocumentTextAnchorGraphV1(
        document_id=document_id,
        text_artifact_id=text_id,
        source_artifact_id=text_id,
        package_id=text_id,
        package_contract_version="1.0",
        created_at="2026-07-09T10:00:00.000000Z",
        sources=[
            DocumentTextAnchorSource(
                source_name="technical_raw_text",
                available=True,
                text_char_count=8,
                range_count=2,
                mapped_anchor_count=2,
            ),
            DocumentTextAnchorSource(source_name="canonical_reading_text", available=False),
            DocumentTextAnchorSource(source_name="layout_text", available=False),
        ],
        anchors=anchors,
        summary=DocumentTextAnchorGraphSummary(
            total_anchors=2,
            anchors_with_raw_range=2,
            anchors_with_canonical_range=0,
            anchors_with_layout_range=0,
            raw_anchor_count=2,
            canonical_anchor_count=0,
            layout_anchor_count=0,
            anchors_with_raw_and_canonical=0,
            anchors_with_raw_only=2,
            anchors_with_canonical_only=0,
            anchors_with_layout=0,
            exact_count=0,
            projected_count=0,
            partial_count=0,
            missing_count=0,
            ambiguous_count=0,
            single_source_count=2,
            ambiguous_anchor_count=0,
            single_source_anchor_count=2,
            unmapped_raw_token_count=0,
            unmapped_canonical_token_count=0,
            canonical_unmapped_count=0,
            layout_unmapped_count=2,
            repeated_token_ambiguity_count=0,
            evidence_only_possible_count=0,
            raw_to_canonical_coverage_ratio=0.0,
            raw_to_layout_coverage_ratio=0.0,
        ),
        validation=DocumentTextAnchorGraphValidation(
            status="degraded",
            warning_count=len(warnings),
            blocker_count=0,
            invalid_range_count=0,
            overlapping_anchor_range_count=1,
            warnings=warnings,
            blockers=[],
        ),
        warnings=warnings,
    )


# --- 404 / preconditions -------------------------------------------------------------------------


def test_unknown_document_returns_404(client: TestClient) -> None:
    assert client.get(
        _CONTRACT_URL.format(document_id="0" * 32),
        params={"pii_artifact_id": "1" * 32, "text_artifact_id": "2" * 32},
    ).status_code == 404


def test_document_without_pii_result_returns_404(client: TestClient) -> None:
    document_id = _upload_document(client)
    assert client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": "1" * 32, "text_artifact_id": "2" * 32},
    ).status_code == 404


# --- anchor-bound identity when the graph supports it --------------------------------------------


def test_entity_is_anchor_bound_when_graph_supports_it(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, "Wien Graz", [_entity("LOCATION", "Wien", 0)])

    body = _get_contract(client, document_id)

    assert body["anchor_graph_available"] is True
    assert body["anchor_graph_status"] in ("valid", "degraded")
    entity = body["entities"][0]
    assert entity["identity_basis"] == "anchor_exact"
    assert entity["binding_status"] == "exact"
    assert entity["anchor_set"]["count"] == 1
    assert len(entity["anchor_set"]["anchor_ids"]) == 1
    assert "anchor_exact_match" in entity["binding_reasons"]
    assert body["binding_summary"]["exact"] == 1
    assert body["binding_summary"]["anchor_bound"] == 1
    assert body["binding_summary"]["entities_with_raw_range"] == 1


def test_entity_id_is_anchor_derived_not_offset_only_when_bound(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(settings, document_id, "Wien Graz", [_entity("LOCATION", "Wien", 0)])

    entity = _get_contract(client, document_id)["entities"][0]
    # The old ADR-0029 offset-only id (hash of document + type + raw span) is NOT the identity here.
    import hashlib

    offset_only_id = hashlib.sha256(
        f"{document_id}\x00LOCATION\x000\x004".encode()
    ).hexdigest()[:32]
    assert entity["entity_id"] != offset_only_id
    assert entity["source_entity_ids"]  # the volatile occurrence id(s) are kept as evidence


def test_entity_carries_detection_evidence_observations(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity("LOCATION", "Wien", 0, recognizer="StructuredRecognizer")
    _save_pii_over_text(settings, document_id, "Wien Graz", [entity])

    entity_out = _get_contract(client, document_id)["entities"][0]
    observations = entity_out["source_observations"]
    assert len(observations) == 1
    observation = observations[0]
    assert observation["detection_id"] == entity.id
    assert observation["recognizer"] == "StructuredRecognizer"
    assert observation["source_name"] == "technical_raw_text"
    assert observation["binding_status"] == "exact"
    assert entity_out["source_entity_ids"] == [entity.id]


# --- raw + canonical display remain available as view/evidence fields -----------------------------


def test_raw_and_canonical_display_ranges_available_as_evidence(
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
    _save_pii_over_text(
        settings, document_id, "Wien Graz", [entity], reading_text="Wien Graz"
    )

    entity_out = _get_contract(client, document_id)["entities"][0]
    # Identity is anchors; canonical/raw ranges are display/evidence and both remain present.
    assert entity_out["identity_basis"] == "anchor_exact"
    assert entity_out["mapping_status"] == "exact"
    assert entity_out["raw_text_range"]["start"] == 0
    assert entity_out["canonical_reading_text_range"] == {
        "start": 0,
        "end": 4,
        "projection_method": "offset_map",
    }
    assert entity_out["display"]["preferred_text_source"] == "canonical_reading_text"


def test_anchor_canonical_range_used_when_entity_projection_is_missing(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Wien Graz",
        [_entity("LOCATION", "Wien", 0)],
        reading_text="Wien Graz",
    )

    body = _get_contract(client, document_id)
    entity_out = body["entities"][0]

    assert entity_out["binding_status"] == "exact"
    assert entity_out["mapping_status"] == "exact"
    assert entity_out["canonical_reading_text_range"] == {
        "start": 0,
        "end": 4,
        "projection_method": "offset_map",
    }
    assert entity_out["display"]["canonical_highlight_range"] == {"start": 0, "end": 4}
    assert body["binding_summary"]["entities_with_canonical_range"] == 1
    assert body["binding_summary"]["missing_canonical_range_count"] == 0


def test_anchor_layout_range_is_emitted_when_available(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Wien Graz",
        [_entity("LOCATION", "Wien", 0)],
        reading_text="Wien Graz",
        layout_text="Wien Graz",
    )

    body = _get_contract(client, document_id)
    entity_out = body["entities"][0]
    layout_refs = [
        ref for ref in entity_out["anchor_refs"] if ref["source_name"] == "layout_text"
    ]

    assert layout_refs == [
        {
            "anchor_id": entity_out["anchor_set"]["anchor_ids"][0],
            "source_name": "layout_text",
            "source_range": {"start": 0, "end": 4},
            "binding_status": "exact",
            "binding_role": "display_span",
            "confidence": None,
            "reason_codes": [],
            "mapping_status": "exact",
        }
    ]
    assert body["binding_summary"]["entities_with_layout_range"] == 1
    assert body["binding_summary"]["missing_layout_range_count"] == 0


def test_missing_canonical_range_is_reason_coded_without_guessing(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Wien Graz",
        [_entity("LOCATION", "Wien", 0)],
        reading_text="Wien Graz",
        map_reading=False,
    )

    body = _get_contract(client, document_id)
    entity_out = body["entities"][0]

    assert entity_out["binding_status"] == "exact"
    assert entity_out["canonical_reading_text_range"] is None
    assert entity_out["mapping_status"] == "missing"
    assert "canonical_range_missing" in entity_out["binding_reasons"]
    assert "reading_text_mapping_missing" in entity_out["binding_reasons"]
    assert body["binding_summary"]["entities_with_canonical_range"] == 0
    assert body["binding_summary"]["missing_canonical_range_count"] == 1
    assert "canonical_range_missing" in body["binding_summary"]["warning_codes"]


def test_missing_layout_range_is_reason_coded_without_guessing(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Wien Graz",
        [_entity("LOCATION", "Wien", 0)],
        reading_text="Wien Graz",
        layout_text="Graz Wien",
    )

    body = _get_contract(client, document_id)
    entity_out = body["entities"][0]

    assert [ref for ref in entity_out["anchor_refs"] if ref["source_name"] == "layout_text"] == []
    assert "layout_range_missing" in entity_out["binding_reasons"]
    assert "layout_mapping_unavailable" in entity_out["binding_reasons"]
    assert body["binding_summary"]["entities_with_layout_range"] == 0
    assert body["binding_summary"]["missing_layout_range_count"] == 1


# --- degrade / never drop ------------------------------------------------------------------------


def test_missing_exact_text_artifact_makes_contract_unavailable(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    _save_pii(settings, document_id, [_entity("LOCATION", "Wien", 10)])

    pii = client.get(f"/api/documents/{document_id}/pii").json()
    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": pii["id"], "text_artifact_id": "a" * 32},
    )
    assert response.status_code == 404


def test_missing_binding_does_not_drop_and_flags_review(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    # The raw text has one token ("Wien"); the detection's offsets land past it (a stale/mismatched
    # projection), so it binds "missing" — still reviewable, never dropped.
    raw = "Wien      "
    _save_pii_over_text(settings, document_id, raw, [_entity("LOCATION", "Graz", 6)])

    entity = _get_contract(client, document_id)["entities"][0]
    assert entity["binding_status"] == "missing"
    assert entity["identity_basis"] == "evidence_only"
    assert entity["display"]["needs_review"] is True
    assert "anchor_binding_missing" in entity["display"]["review_reason_codes"]


def test_partial_binding_flags_review(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings, document_id, "Max Mustermann", [_entity("PERSON", "Max Muster", 0)]
    )

    entity = _get_contract(client, document_id)["entities"][0]
    assert entity["binding_status"] == "partial"
    assert entity["identity_basis"] == "anchor_partial"
    assert entity["display"]["needs_review"] is True
    assert "anchor_binding_partial" in entity["display"]["review_reason_codes"]
    assert "anchor_binding_partial" in entity["warnings"]


def test_ambiguous_binding_is_explicit_and_not_dropped(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    document_id = _upload_document(client)
    text_id = _save_pii_over_text(
        settings, document_id, "AbcdeFgh", [_entity("LOCATION", "AbcdeFgh", 0)]
    )
    graph = _manual_overlapping_anchor_graph(document_id, text_id)
    monkeypatch.setattr("app.services.pii_entity_contract._anchor_graph", lambda _text: graph)

    body = _get_contract(client, document_id)

    assert len(body["entities"]) == 1
    entity = body["entities"][0]
    assert entity["binding_status"] == "ambiguous"
    assert entity["identity_basis"] == "evidence_only"
    assert entity["anchor_set"]["anchor_ids"] == []
    assert {ref["binding_role"] for ref in entity["anchor_refs"]} == {"inferred_span"}
    assert body["binding_summary"]["ambiguous"] == 1
    assert entity["display"]["needs_review"] is True
    assert "anchor_binding_ambiguous" in entity["display"]["review_reason_codes"]


def test_binding_summary_counts(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Max Mustermann Wien",
        [
            _entity("PERSON", "Max Mustermann", 0),  # exact (two tokens)
            _entity("LOCATION", "Wien", 15),  # exact (one token)
        ],
    )

    body = _get_contract(client, document_id)
    assert body["binding_summary"]["total"] == 2
    assert body["binding_summary"]["total_entities"] == 2
    assert body["binding_summary"]["anchor_bound"] == 2
    assert body["binding_summary"]["anchor_bound_entities"] == 2
    assert body["binding_summary"]["exact"] == 2
    assert body["binding_summary"]["exact_bound_entities"] == 2
    assert body["binding_summary"]["entities_with_raw_range"] == 2
    assert body["binding_summary"]["evidence_only"] == 0


def test_repeated_values_not_globally_bound(client: TestClient, settings: Settings) -> None:
    document_id = _upload_document(client)
    _save_pii_over_text(
        settings,
        document_id,
        "Wien Wien",
        [_entity("LOCATION", "Wien", 0), _entity("LOCATION", "Wien", 5)],
    )

    entities = _get_contract(client, document_id)["entities"]
    assert len(entities) == 2
    assert entities[0]["entity_id"] != entities[1]["entity_id"]
    assert entities[0]["anchor_set"]["anchor_ids"] != entities[1]["anchor_set"]["anchor_ids"]


def test_same_anchor_set_and_type_merges_source_observations(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    first = _entity(
        "LOCATION",
        "Wien",
        0,
        recognizer="R1",
        provenance=PiiEntityProvenance(recognizers=["R1"], candidate_count=1),
    )
    second = _entity(
        "LOCATION",
        "Wien",
        0,
        recognizer="R2",
        provenance=PiiEntityProvenance(recognizers=["R2"], candidate_count=1),
    )
    _save_pii_over_text(settings, document_id, "Wien", [first, second])

    body = _get_contract(client, document_id)

    assert len(body["entities"]) == 1
    entity = body["entities"][0]
    assert entity["binding_status"] == "exact"
    assert entity["identity_basis"] == "anchor_exact"
    assert sorted(entity["source_entity_ids"]) == sorted([first.id, second.id])
    assert sorted(obs["detection_id"] for obs in entity["source_observations"]) == sorted(
        [first.id, second.id]
    )
    assert entity["provenance"]["recognizers"] == ["R1", "R2"]
    assert entity["provenance"]["candidate_count"] == 2
    assert body["binding_summary"]["total"] == 1


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
    _save_text(settings, document_id, text_id="a" * 32, raw="Max")
    _save_pii(settings, document_id, [entity], text_char_count=3)

    entity_out = _get_contract(client, document_id)["entities"][0]

    assert entity_out["display"]["needs_review"] is True
    assert set(entity_out["display"]["review_reason_codes"]) >= {
        "conflicting_entity_type",
        "ambiguous_overlap_review_required",
    }
    assert entity_out["provenance"]["overlap_decision"] == "conflicting_entity_type"


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
    _save_text(settings, document_id, text_id="a" * 32, raw="max@example.at")
    _save_pii(settings, document_id, [entity], text_char_count=len("max@example.at"))

    entity_out = _get_contract(client, document_id)["entities"][0]

    # A merge is informational: it appears in warnings but does not force review on its own here
    # (the exact text snapshot is present and the merge itself is not a review reason).
    assert entity_out["display"]["needs_review"] is False
    assert "merged_provenance" in entity_out["warnings"]
    assert "recognizer_duplicate" in entity_out["warnings"]
    assert entity_out["provenance"]["superseded_candidate_ids"] == ["b" * 32]


# --- review state reflects the existing decision overlay -----------------------------------------


def test_review_decision_is_reflected_on_anchor_bound_entity(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entity = _entity("LOCATION", "Wien", 0)
    _save_pii_over_text(settings, document_id, "Wien Graz", [entity])
    review = client.get(f"/api/documents/{document_id}/pii/review").json()
    group_id = review["groups"][0]["entity_group_id"]
    occurrence_id = review["occurrences"][0]["occurrence_id"]

    ack = client.post(
        f"/api/documents/{document_id}/pii/review/decisions",
        json={"target_type": "entity_group", "target_id": group_id, "decision": "false_positive"},
    )
    assert ack.status_code == 201

    entity_out = _get_contract(client, document_id)["entities"][0]
    assert entity_out["source_entity_ids"] == [occurrence_id]
    assert entity_out["entity_group_id"] == group_id
    assert entity_out["review_state"] == "rejected"
    assert entity_out["review_decision"] == "false_positive"
    assert entity_out["decision_scope"] == "entity_group"
    # The review decision keys on the occurrence id and does not change the anchor-derived identity.
    assert entity_out["identity_basis"] == "anchor_exact"


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
    # The immutable artifact never grows the anchor-bound contract fields.
    assert "binding_status" not in entity
    assert "identity_basis" not in entity

    review = client.get(f"/api/documents/{document_id}/pii/review")
    assert review.status_code == 200
    assert "entity-contract" not in review.text


# --- privacy: value confined, no snippet/token leaks ----------------------------------------------


def test_value_is_confined_and_no_token_text_leaks(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    secret = "Geheimname"
    _save_pii_over_text(
        settings, document_id, f"{secret} in Wien", [_entity("PERSON", secret, 0)]
    )

    pii = client.get(f"/api/documents/{document_id}/pii").json()
    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": pii["id"], "text_artifact_id": pii["input_text_artifact_id"]},
    )
    entity_out = response.json()["entities"][0]

    # The value appears only in the dedicated value field, never in identity/binding metadata.
    assert entity_out["value"] == secret
    assert secret not in entity_out["entity_id"]
    assert secret not in json.dumps(entity_out["anchor_set"])
    assert secret not in json.dumps(entity_out["anchor_refs"])
    assert secret not in json.dumps(entity_out["binding_reasons"])
    assert secret not in json.dumps(entity_out["source_observations"])
    assert secret not in json.dumps(entity_out["display"])
    assert secret not in json.dumps(entity_out["warnings"])
    assert secret not in json.dumps(entity_out.get("provenance"))
    assert secret not in json.dumps(response.json()["binding_summary"])
    # Neighbour context words from the raw text are never sent by this endpoint at all.
    assert "in Wien" not in response.text
