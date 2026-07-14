"""Integration and unit tests for the unified Review Result v1 entry contract.

Review Result v1 introduces ``PiiReviewResult.entries``: one stable, coherent
``PiiReviewResultEntry`` per detected occurrence and manual addition (see
``app/services/pii_review_result.py``). This suite proves the behavior named in the branch's
required-proof list end to end, mostly through the real ``GET/POST …/pii/review*`` API:

1. A detected entity can receive a review decision and produce one stable Review Result entry.
2. The same result is returned consistently across repeated reads and both text views (raw +
   canonical identity agree, via the entity contract's anchor-derived ``entity_id``).
3. Accept/keep/reject preserve the existing product semantics.
4. A manual addition produces a coherent entry, not a separate incompatible entity type.
5. Detection evidence and anchor identity remain unchanged after review.
6. A stale (superseded) artifact pairing does not silently inherit a decision.
7. Missing/ambiguous identity produces an explicit ``unresolved`` state.
8. Mapping quality (exact/projected/...) stays visible and is never upgraded by a decision.
9. No copied source text ever appears in the response.

A few rare, defensive states (a structurally broken/"incompatible" artifact reference) are exercised
as focused unit tests directly against ``pii_review_result.py``'s builder functions, since they
cannot arise through the normal, coherent artifact-creation path exercised by the API.
"""

from __future__ import annotations

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
    PiiManualAddition,
    PiiReviewOccurrence,
    PiiValidationSummary,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
)
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors
from app.services.pii_review_result import (
    _detected_identity,
    build_detected_entries,
    build_manual_addition_entries,
)
from app.services.pii_review_service import get_pii_review_result

_REVIEW_URL = "/api/documents/{document_id}/pii/review"
_REVIEW_RESULT_URL = "/api/documents/{document_id}/pii/review-result"
_DECISIONS_URL = "/api/documents/{document_id}/pii/review/decisions"
_MANUAL_ADDITIONS_URL = "/api/documents/{document_id}/pii/review/manual-additions"
_PII_URL = "/api/documents/{document_id}/pii"
_CONTRACT_URL = "/api/documents/{document_id}/pii/entity-contract"

_SECRET_ORG = "TopSecret Insurance GmbH"
_SECRET_PERSON = "Adalbert Geheimrat"
_RAW = f"{_SECRET_ORG} beschaeftigt {_SECRET_PERSON} seit 2020."


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


def _text_artifact(
    document_id: str, text_id: str, raw: str, *, reading_text: str | None = None
) -> TextArtifact:
    reading = raw if reading_text is None else reading_text
    reading_map = (
        [
            ReadingTextMapSegment(
                reading_start=0,
                reading_end=len(reading),
                raw_start=0,
                raw_end=len(raw),
                mapping_status="exact",
            )
        ]
        if len(reading) == len(raw)
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
        reading_text_version="1",
        reading_text=reading,
        reading_text_status="heuristic",
        reading_text_map_version="1",
        reading_text_map=reading_map,
    )
    return TextArtifact(
        id=text_id,
        document_id=document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        created_at="2026-07-11T09:00:00.000000Z",
        content=content,
    )


def _save_pii_over_text(
    settings: Settings, document_id: str, raw: str, entities: list[PiiEntity]
) -> tuple[str, str]:
    """Persist a coherent text + PII artifact pair with real reading-text lineage.

    ``raw == reading_text`` here, so every entity's raw span binds ``anchor_exact`` with an
    ``exact`` canonical display range -- a clean, deterministic "fully resolved" fixture.
    """
    text_id = uuid4().hex
    save_text_artifact(settings, _text_artifact(document_id, text_id, raw))

    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    content = PiiContent(
        document_id=document_id,
        input_text_artifact_id=text_id,
        profile="custom",
        language="de",
        score_threshold=0.5,
        text_char_count=len(raw),
        reading_text_char_count=len(raw),
        configured_entity_types=sorted(counts),
        entities=entities,
        entity_counts=dict(sorted(counts.items())),
        tool_versions={},
        flags=[],
        validation=PiiValidationSummary(enabled=True, kept=len(entities), dropped=0, score_down=0),
    )
    pii_id = uuid4().hex
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=pii_id,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-11T10:00:00.000000Z",
            content=content,
        ),
    )
    return pii_id, text_id


def _save_pii_without_text(
    settings: Settings, document_id: str, entities: list[PiiEntity]
) -> str:
    """Persist a PII artifact whose ``input_text_artifact_id`` references no real text artifact."""
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    content = PiiContent(
        document_id=document_id,
        input_text_artifact_id="a" * 32,
        profile="custom",
        language="de",
        score_threshold=0.5,
        text_char_count=500,
        configured_entity_types=sorted(counts),
        entities=entities,
        entity_counts=dict(sorted(counts.items())),
        tool_versions={},
        flags=[],
        validation=PiiValidationSummary(enabled=True, kept=len(entities), dropped=0, score_down=0),
    )
    pii_id = uuid4().hex
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=pii_id,
            document_id=document_id,
            input_text_artifact_id="a" * 32,
            created_at="2026-07-11T10:00:00.000000Z",
            content=content,
        ),
    )
    return pii_id


def _entry(review: dict[str, object], entry_id: str) -> dict[str, object]:
    entries = review["entries"]
    assert isinstance(entries, list)
    matches = [entry for entry in entries if entry["entry_id"] == entry_id]
    assert len(matches) == 1, f"expected exactly one entry for {entry_id!r}"
    return matches[0]  # type: ignore[no-any-return]


# --- 1/3. detected entity -> stable entry; accept/keep/reject semantics --------------------------


def test_detected_entities_produce_stable_resolved_entries(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    person = _entity("PERSON", _SECRET_PERSON, _RAW.index(_SECRET_PERSON))
    _save_pii_over_text(settings, document_id, _RAW, [org, person])

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert len(review["entries"]) == 2
    entry = _entry(review, org.id)
    assert entry["origin"] == "detected"
    assert entry["entity_type"] == "ORGANIZATION"
    assert entry["identity_status"] == "resolved"
    assert entry["identity_reason_codes"] == []
    assert entry["mapping_status"] == "exact"
    assert entry["artifact_currency"] == "current"
    assert entry["review_status"] == "accepted"
    assert entry["review_decision"] is None
    anchor_entity_id = entry["anchor_entity_id"]
    assert isinstance(anchor_entity_id, str)
    assert len(anchor_entity_id) == 32


def test_accept_keep_reject_preserve_product_semantics_on_entries(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    person = _entity("PERSON", _SECRET_PERSON, _RAW.index(_SECRET_PERSON))
    _save_pii_over_text(settings, document_id, _RAW, [org, person])

    for entity, decision, _expected_status in (
        (org, "pseudonymize", "accepted"),
        (person, "false_positive", "rejected"),
    ):
        response = client.post(
            _DECISIONS_URL.format(document_id=document_id),
            json={"target_type": "occurrence", "target_id": entity.id, "decision": decision},
        )
        assert response.status_code == 201, response.text

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    org_entry = _entry(review, org.id)
    person_entry = _entry(review, person.id)
    assert org_entry["review_status"] == "accepted"
    assert org_entry["review_decision"] == "pseudonymize"
    assert person_entry["review_status"] == "rejected"
    assert person_entry["review_decision"] == "false_positive"

    # "keep" flips status without ever touching identity/mapping quality (proof 8 below covers the
    # unchanged-identity assertion explicitly).
    keep_response = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={"target_type": "occurrence", "target_id": org.id, "decision": "keep"},
    )
    assert keep_response.status_code == 201
    review_after_keep = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert _entry(review_after_keep, org.id)["review_status"] == "kept"


# --- 2. consistency across repeated reads and both text views ------------------------------------


def test_entries_are_consistent_across_repeated_reads_and_both_text_views(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_over_text(settings, document_id, _RAW, [org])

    first = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    second = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert first["entries"] == second["entries"]

    # The persisted immutable snapshot (Review L8) carries the same entries too.
    client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={"target_type": "occurrence", "target_id": org.id, "decision": "keep"},
    )
    snapshot = client.get(_REVIEW_RESULT_URL.format(document_id=document_id)).json()
    live = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert snapshot["content"]["entries"] == live["entries"]

    # Raw view (this occurrence's raw offsets) and canonical view (the entity contract's
    # canonical_reading_text_range) resolve to the *same* entity: the review entry's
    # `anchor_entity_id` matches the entity-contract entity that carries both ranges.
    pii = client.get(_PII_URL.format(document_id=document_id)).json()
    contract = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": pii["id"], "text_artifact_id": pii["input_text_artifact_id"]},
    ).json()
    entry = _entry(live, org.id)
    [contract_entity] = [e for e in contract["entities"] if org.id in e["source_entity_ids"]]
    assert entry["anchor_entity_id"] == contract_entity["entity_id"]
    assert contract_entity["display"]["raw_highlight_range"] == {
        "start": org.start_offset,
        "end": org.end_offset,
    }
    assert contract_entity["canonical_reading_text_range"] is not None


# --- 4. manual addition -> coherent entry, not a separate incompatible type ----------------------


def test_manual_addition_produces_coherent_entry_in_same_shape(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_over_text(settings, document_id, _RAW, [org])
    # A single-token span ("2020") -- unlike a multi-word span, one raw anchor covers it fully with
    # no inter-word gap, so the reverse projection resolves "exact" (mirrors the single-word fixture
    # already used for this case in test_pii_manual_addition.py).
    year_start = _RAW.index("2020")
    year_end = year_start + len("2020")

    created = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json={
            "entity_type": "ORGANIZATION",
            "canonical_start": year_start,
            "canonical_end": year_end,
        },
    ).json()
    assert created["raw_projection_status"] == "exact"

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    entry = _entry(review, created["addition_id"])
    assert entry["origin"] == "manual"
    assert entry["entity_group_id"] is None
    assert entry["pii_artifact_id"] is None
    assert entry["identity_status"] == "resolved"
    assert entry["mapping_status"] == "exact"
    assert entry["anchor_entity_id"] is None  # ADR-0035: never merged into anchor identity
    assert set(entry.keys()) == set(_entry(review, org.id).keys())  # same unified shape

    decision = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={
            "target_type": "manual_addition",
            "target_id": created["addition_id"],
            "decision": "keep",
        },
    )
    assert decision.status_code == 201
    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert _entry(review_after, created["addition_id"])["review_status"] == "kept"


# --- 5. detection evidence and anchor identity unchanged after review ----------------------------


def test_detection_evidence_and_anchor_identity_unchanged_after_review(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_over_text(settings, document_id, _RAW, [org])

    pii_before = client.get(_PII_URL.format(document_id=document_id)).json()
    contract_before = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={
            "pii_artifact_id": pii_before["id"],
            "text_artifact_id": pii_before["input_text_artifact_id"],
        },
    ).json()

    for decision in ("pseudonymize", "keep", "false_positive"):
        client.post(
            _DECISIONS_URL.format(document_id=document_id),
            json={"target_type": "occurrence", "target_id": org.id, "decision": decision},
        )

    pii_after = client.get(_PII_URL.format(document_id=document_id)).json()
    contract_after = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={
            "pii_artifact_id": pii_before["id"],
            "text_artifact_id": pii_before["input_text_artifact_id"],
        },
    ).json()
    assert pii_after == pii_before
    entity_ids_before = {e["entity_id"] for e in contract_before["entities"]}
    entity_ids_after = {e["entity_id"] for e in contract_after["entities"]}
    assert entity_ids_after == entity_ids_before
    assert contract_after["entities"][0]["raw_text_range"] == contract_before["entities"][0][
        "raw_text_range"
    ]


# --- 6. stale artifact pairing does not silently inherit a decision ------------------------------


def test_manual_addition_entry_becomes_stale_after_new_text_artifact(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_over_text(settings, document_id, _RAW, [org])
    person_start = _RAW.index(_SECRET_PERSON)
    person_end = person_start + len(_SECRET_PERSON)
    created = client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json={
            "entity_type": "ORGANIZATION",
            "canonical_start": person_start,
            "canonical_end": person_end,
        },
    ).json()

    review_before = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    assert _entry(review_before, created["addition_id"])["artifact_currency"] == "current"

    # A later OCR/Text re-run: a new text artifact for the same document.
    save_text_artifact(settings, _text_artifact(document_id, uuid4().hex, _RAW))

    review_after = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    stale_entry = _entry(review_after, created["addition_id"])
    assert stale_entry["artifact_currency"] == "stale"
    # The entry is still shown -- never silently dropped -- and a new decision can no longer target
    # it (the existing target-existence check already guards this; this proves the entry-level flag
    # agrees with that guard rather than looking identical to "fully current").
    stale_decision = client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={
            "target_type": "manual_addition",
            "target_id": created["addition_id"],
            "decision": "keep",
        },
    )
    assert stale_decision.status_code == 404


def test_detected_entry_currency_reflects_a_superseded_pii_artifact(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    old_pii_id, _text_id = _save_pii_over_text(settings, document_id, _RAW, [org])

    # A later PII re-run: a brand-new pii_result artifact becomes "the" latest.
    _save_pii_over_text(settings, document_id, _RAW, [_entity("ORGANIZATION", _SECRET_ORG, 0)])

    old_review = get_pii_review_result(settings, document_id, old_pii_id)
    [entry] = old_review.entries
    assert entry.artifact_currency == "stale"


# --- 7. missing/ambiguous identity -> explicit "unresolved" state --------------------------------


def test_missing_text_artifact_produces_unresolved_identity(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_without_text(settings, document_id, [org])

    review = client.get(_REVIEW_URL.format(document_id=document_id)).json()
    entry = _entry(review, org.id)
    assert entry["identity_status"] == "unresolved"
    assert entry["identity_reason_codes"]
    assert entry["anchor_entity_id"] is None
    assert entry["mapping_status"] == "not_applicable"


def _manual_raw_graph(
    document_id: str, text_id: str, raw_char_count: int, spans: list[tuple[int, int]]
) -> DocumentTextAnchorGraphV1:
    """A hand-built raw-only anchor graph for cases the real builder cannot produce (mutually
    overlapping raw anchors) -- mirrors the equivalent fixture in test_pii_anchor_binding.py."""
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
        for start, end in spans
    ]
    warnings = ["missing_canonical_reading_text", "missing_layout_text"]
    summary = DocumentTextAnchorGraphSummary(
        total_anchors=len(anchors),
        anchors_with_raw_range=len(anchors),
        anchors_with_canonical_range=0,
        anchors_with_layout_range=0,
        raw_anchor_count=len(anchors),
        canonical_anchor_count=0,
        layout_anchor_count=0,
        anchors_with_raw_and_canonical=0,
        anchors_with_raw_only=len(anchors),
        anchors_with_canonical_only=0,
        anchors_with_layout=0,
        exact_count=0,
        projected_count=0,
        partial_count=0,
        missing_count=0,
        ambiguous_count=0,
        single_source_count=len(anchors),
        ambiguous_anchor_count=0,
        single_source_anchor_count=len(anchors),
        unmapped_raw_token_count=0,
        unmapped_canonical_token_count=0,
        canonical_unmapped_count=0,
        layout_unmapped_count=len(anchors),
        repeated_token_ambiguity_count=0,
        evidence_only_possible_count=0,
        raw_to_canonical_coverage_ratio=0.0,
        raw_to_layout_coverage_ratio=0.0,
    )
    validation = DocumentTextAnchorGraphValidation(
        status="degraded",
        warning_count=len(warnings),
        blocker_count=0,
        invalid_range_count=0,
        overlapping_anchor_range_count=0,
        warnings=warnings,
        blockers=[],
    )
    sources = [
        DocumentTextAnchorSource(
            source_name="technical_raw_text",
            available=True,
            text_char_count=raw_char_count,
            range_count=len(anchors),
            mapped_anchor_count=len(anchors),
        ),
        DocumentTextAnchorSource(source_name="canonical_reading_text", available=False),
        DocumentTextAnchorSource(source_name="layout_text", available=False),
    ]
    return DocumentTextAnchorGraphV1(
        document_id=document_id,
        text_artifact_id=text_id,
        source_artifact_id=text_id,
        package_id=text_id,
        package_contract_version="1.0",
        created_at="2026-07-11T09:00:00.000000Z",
        sources=sources,
        anchors=anchors,
        summary=summary,
        validation=validation,
        warnings=warnings,
    )


def test_ambiguous_anchor_binding_produces_unresolved_identity() -> None:
    # Two mutually overlapping raw anchors: no single anchor set is implied (mirrors the existing
    # ambiguity fixture in test_pii_anchor_binding.py).
    document_id = uuid4().hex
    text_id = uuid4().hex
    graph = _manual_raw_graph(document_id, text_id, raw_char_count=20, spans=[(0, 5), (3, 8)])
    entity = _entity("LOCATION", "AbcdeFgh", 0)
    bound_entities, _summary = bind_pii_entities_to_anchors(
        [entity], graph, document_id=document_id
    )
    [bound] = bound_entities

    identity_status, reason_codes, anchor_entity_id = _detected_identity(bound, "not_applicable")

    assert identity_status == "unresolved"
    assert reason_codes
    assert anchor_entity_id is None


# --- incompatible identity: structurally broken references (defensive, unit-level) ---------------


def test_detected_entry_incompatible_when_offsets_exceed_referenced_text() -> None:
    document_id = uuid4().hex
    text_id = uuid4().hex
    text_artifact = _text_artifact(document_id, text_id, "Wien")
    entity = _entity("LOCATION", "ViennaLongerThanFourChars", 0)
    occurrence = PiiReviewOccurrence(
        occurrence_id=entity.id,
        entity_type=entity.entity_type,
        entity_group_id=uuid4().hex,
        raw_start=entity.start_offset,
        raw_end=entity.end_offset,
        score=entity.score,
        recognizer=entity.recognizer,
    )

    [entry] = build_detected_entries(
        document_id=document_id,
        pii_artifact_id=uuid4().hex,
        text_artifact_id=text_id,
        text_artifact=text_artifact,
        entities=[entity],
        occurrences=[occurrence],
        is_current=True,
    )

    assert entry.identity_status == "incompatible"
    assert entry.identity_reason_codes
    assert entry.anchor_entity_id is None


def test_manual_addition_entry_incompatible_when_reference_is_broken() -> None:
    addition = PiiManualAddition(
        addition_id=uuid4().hex,
        entity_type="LOCATION",
        canonical_start=0,
        canonical_end=4,
        text_artifact_id=uuid4().hex,
        raw_start=0,
        raw_end=4,
        raw_projection_status="exact",
        created_at="2026-07-11T09:00:00.000000Z",
    )

    [entry] = build_manual_addition_entries(
        manual_additions=[addition],
        current_text_artifact_id=addition.text_artifact_id,
        text_artifacts_by_id={addition.text_artifact_id: None},
    )

    assert entry.identity_status == "incompatible"
    assert entry.identity_reason_codes


def test_manual_addition_entry_incompatible_when_offsets_exceed_its_own_text() -> None:
    document_id = uuid4().hex
    text_id = uuid4().hex
    text_artifact = _text_artifact(document_id, text_id, "Wien")
    addition = PiiManualAddition(
        addition_id=uuid4().hex,
        entity_type="LOCATION",
        canonical_start=0,
        canonical_end=100,
        text_artifact_id=text_id,
        raw_start=0,
        raw_end=4,
        raw_projection_status="exact",
        created_at="2026-07-11T09:00:00.000000Z",
    )

    [entry] = build_manual_addition_entries(
        manual_additions=[addition],
        current_text_artifact_id=text_id,
        text_artifacts_by_id={text_id: text_artifact},
    )

    assert entry.identity_status == "incompatible"
    assert entry.identity_reason_codes


# --- 8. mapping quality stays visible and is never upgraded by review ----------------------------


def test_mapping_status_is_not_upgraded_by_a_review_decision(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_without_text(settings, document_id, [org])  # no canonical text -> not_applicable

    before = _entry(client.get(_REVIEW_URL.format(document_id=document_id)).json(), org.id)
    assert before["mapping_status"] == "not_applicable"
    assert before["identity_status"] == "unresolved"

    for decision in ("pseudonymize", "keep", "false_positive"):
        client.post(
            _DECISIONS_URL.format(document_id=document_id),
            json={"target_type": "occurrence", "target_id": org.id, "decision": decision},
        )
        after = _entry(client.get(_REVIEW_URL.format(document_id=document_id)).json(), org.id)
        assert after["mapping_status"] == "not_applicable"
        assert after["identity_status"] == "unresolved"
        assert after["anchor_entity_id"] is None


def test_exact_mapping_status_and_anchor_id_survive_a_decision(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    _save_pii_over_text(settings, document_id, _RAW, [org])

    before = _entry(client.get(_REVIEW_URL.format(document_id=document_id)).json(), org.id)
    client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={"target_type": "occurrence", "target_id": org.id, "decision": "keep"},
    )
    after = _entry(client.get(_REVIEW_URL.format(document_id=document_id)).json(), org.id)

    assert after["mapping_status"] == before["mapping_status"] == "exact"
    assert after["anchor_entity_id"] == before["anchor_entity_id"]
    assert after["identity_status"] == before["identity_status"] == "resolved"


# --- 9. no copied source text ---------------------------------------------------------------------


def test_review_result_never_carries_copied_source_text(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    org = _entity("ORGANIZATION", _SECRET_ORG, 0)
    person = _entity("PERSON", _SECRET_PERSON, _RAW.index(_SECRET_PERSON))
    _save_pii_over_text(settings, document_id, _RAW, [org, person])
    client.post(
        _MANUAL_ADDITIONS_URL.format(document_id=document_id),
        json={
            "entity_type": "ORGANIZATION",
            "canonical_start": 0,
            "canonical_end": len(_SECRET_ORG),
        },
    )
    client.post(
        _DECISIONS_URL.format(document_id=document_id),
        json={"target_type": "occurrence", "target_id": org.id, "decision": "keep"},
    )

    review = client.get(_REVIEW_URL.format(document_id=document_id))
    snapshot = client.get(_REVIEW_RESULT_URL.format(document_id=document_id))

    for payload in (review.text, snapshot.text):
        assert _SECRET_ORG not in payload
        assert _SECRET_PERSON not in payload
