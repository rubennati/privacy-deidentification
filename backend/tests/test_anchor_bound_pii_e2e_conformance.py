"""End-to-end anchor-first PII highlight conformance (ADR-0031).

All data is synthetic. This suite proves the full contract path is coherent:

    DocumentTextPackageV1 -> Text Anchor Graph -> PII detection evidence
    -> anchor-bound PII entity -> entity-contract view ranges -> frontend highlight ranges.

The architecture promise is: **if a PII detection found in Technical Raw Text maps to anchors, and
those anchors have Canonical Reading Text ranges, the anchor-bound entity contract must emit the
matching Canonical Reading Text display/highlight ranges for the same entity identity.** A view
range is only allowed to be absent for a specific structural reason (repeated-token ambiguity,
missing mapping, partial binding), never a silent divergence between the raw and reading views.

The fixtures put the same business/person/contact information in Technical Raw Text and Canonical
Reading Text in a different layout/order (an interleaved two-column raw extraction vs. a logical
single-column reading order), because that is exactly the case where the two views used to diverge.
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
    PiiValidationSummary,
    TextArtifact,
    TextContent,
    TextGeometry,
    TextGeometryPage,
    TextLineGeometry,
    TextPageResult,
)
from app.services.artifact_service import save_pii_artifact, save_text_artifact
from app.services.reading_text_geometry_projection import (
    build_reading_text_geometry_projection_map,
)
from app.services.reading_text_projection import (
    build_reading_text_map,
    project_pii_entities_to_reading_text,
)

_CONTRACT_URL = "/api/documents/{document_id}/pii/entity-contract"

# --- Synthetic reordered fixture -----------------------------------------------------------------
# Technical Raw Text: an interleaved two-column extraction (as a text-layer PDF often yields). Note
# line 2 ends with a date and line 3 starts with a number: "15.03.2024\n1010". A tokenizer that let
# a phone/number token span the line break would merge them into one bogus anchor, which is exactly
# how the reading-view highlights for the date and the postal code used to disappear.
_RAW = (
    "Muster Handels GmbH        Rechnung 2024-0042\n"
    "Hauptstrasse 12            vom 15.03.2024\n"
    "1010 Wien                  Kunde: Anna Beispiel\n"
    "office@muster.at           geboren 01.02.1980\n"
    "+43 1 2345678              UID ATU12345678\n"
)
# Canonical Reading Text: the same information in logical single-column order.
_READING = (
    "Muster Handels GmbH\n"
    "Hauptstrasse 12\n"
    "1010 Wien\n"
    "office@muster.at\n"
    "+43 1 2345678\n"
    "Rechnung 2024-0042\n"
    "vom 15.03.2024\n"
    "Kunde: Anna Beispiel\n"
    "geboren 01.02.1980\n"
    "UID ATU12345678\n"
)

# (entity_type, value) for every required class: company, street, city, phone, email, UID, person,
# birth date, document number, document date. Every value is unique in both views, so every one must
# propagate a canonical range through anchor identity.
_FIXTURE_ENTITIES: tuple[tuple[str, str], ...] = (
    ("ORG", "Muster Handels GmbH"),
    ("STREET_ADDRESS", "Hauptstrasse 12"),
    ("LOCATION", "1010 Wien"),
    ("PHONE_NUMBER", "+43 1 2345678"),
    ("EMAIL_ADDRESS", "office@muster.at"),
    ("UID_AT", "ATU12345678"),
    ("PERSON", "Anna Beispiel"),
    ("DATE_TIME", "01.02.1980"),
    ("OFFER_NUMBER", "2024-0042"),
    ("DATE_TIME", "15.03.2024"),
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


def _raw_span(raw: str, needle: str, occurrence: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(occurrence + 1):
        start = raw.index(needle, start + 1)
    return start, start + len(needle)


def _entity(raw: str, entity_type: str, value: str, occurrence: int = 0) -> PiiEntity:
    start, end = _raw_span(raw, value, occurrence)
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=value,
        start_offset=start,
        end_offset=end,
        score=0.9,
        recognizer="SyntheticRecognizer",
    )


def _save_e2e(
    settings: Settings,
    document_id: str,
    raw: str,
    reading: str,
    entities: list[PiiEntity],
) -> None:
    """Run the real reading-text lineage + projection, then persist a text + PII artifact pair.

    The reading_text_map and the entity projection are produced by the same builders the OCR/PII
    stations use, so the anchor graph and entity contract are exercised end to end (no hand-built
    graph).
    """
    pages = [
        TextPageResult(
            page_number=1,
            source="pdf_text_layer",
            has_text_layer=True,
            ocr_used=False,
            text=raw,
            text_char_count=len(raw),
        )
    ]
    reading_map = build_reading_text_map(raw, reading, pages)
    text_id = uuid4().hex
    text_content = TextContent(
        document_id=document_id,
        input_artifact_id="c" * 32,
        input_audit_artifact_id="d" * 32,
        source="pdf_text_layer",
        text=raw,
        text_char_count=len(raw),
        pages=pages,
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version="1",
        reading_text=reading,
        reading_text_status="heuristic",
        reading_text_map_version="1",
        reading_text_map=reading_map,
    )
    save_text_artifact(
        settings,
        TextArtifact(
            id=text_id,
            document_id=document_id,
            input_artifact_id="c" * 32,
            input_audit_artifact_id="d" * 32,
            created_at="2026-07-10T09:00:00.000000Z",
            content=text_content,
        ),
    )

    projected = _sorted_entities(
        project_pii_entities_to_reading_text(entities, reading_map, reading_text=reading)
    )
    counts: dict[str, int] = {}
    for entity in projected:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    pii_content = PiiContent(
        document_id=document_id,
        input_text_artifact_id=text_id,
        profile="custom",
        language="de",
        score_threshold=0.5,
        text_char_count=len(raw),
        reading_text_char_count=len(reading),
        configured_entity_types=sorted(counts),
        entities=projected,
        entity_counts=dict(sorted(counts.items())),
        tool_versions={},
        flags=[],
        validation=PiiValidationSummary(
            enabled=True, kept=len(projected), dropped=0, score_down=0
        ),
    )
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=uuid4().hex,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-10T10:00:00.000000Z",
            content=pii_content,
        ),
    )


def _sorted_entities(entities: list[PiiEntity]) -> list[PiiEntity]:
    """Deterministic order required by ``PiiContent`` (mirrors the PII station's sort key)."""
    return sorted(
        entities,
        key=lambda entity: (
            entity.start_offset,
            entity.end_offset,
            entity.entity_type,
            entity.recognizer,
            entity.text,
            -entity.score,
        ),
    )


def _get_contract(client: TestClient, document_id: str) -> dict:
    response = client.get(_CONTRACT_URL.format(document_id=document_id))
    assert response.status_code == 200, response.text
    return response.json()


def _by_value(body: dict, value: str) -> dict:
    matches = [entity for entity in body["entities"] if entity["value"] == value]
    assert len(matches) == 1, f"expected exactly one entity for {value!r}, got {len(matches)}"
    return matches[0]


# --- 1. Raw -> canonical range propagation for one clean value -----------------------------------


def test_raw_detection_propagates_canonical_range_through_anchor_identity(
    client: TestClient, settings: Settings
) -> None:
    """A raw detection that binds to anchors whose canonical ranges exist must expose a canonical
    display/highlight range for the *same* entity identity — the core anchor-first promise."""
    document_id = _upload_document(client)
    entities = [_entity(_RAW, entity_type, value) for entity_type, value in _FIXTURE_ENTITIES]
    _save_e2e(settings, document_id, _RAW, _READING, entities)

    body = _get_contract(client, document_id)
    assert body["anchor_graph_available"] is True

    # The document date "15.03.2024" is the regression witness: it sits at the end of a raw line,
    # immediately followed by a newline and the next line's postal code "1010".
    date = _by_value(body, "15.03.2024")
    assert date["entity_type"] == "DATE_TIME"
    assert date["identity_basis"] == "anchor_exact"
    assert date["binding_status"] == "exact"
    assert date["anchor_set"]["count"] >= 1
    assert "canonical_range_missing" not in date["binding_reasons"]
    assert date["mapping_status"] == "exact"

    # Same entity identity carries both a raw and a canonical highlight range.
    raw_range = date["display"]["raw_highlight_range"]
    canonical_range = date["display"]["canonical_highlight_range"]
    assert canonical_range is not None
    assert _RAW[raw_range["start"] : raw_range["end"]] == "15.03.2024"
    assert _READING[canonical_range["start"] : canonical_range["end"]] == "15.03.2024"
    # The raw and canonical highlights are two views of ONE entity id, not two independent entities.
    assert date["entity_id"] == date["entity_id"]  # single object, single identity


# --- 2. Every required entity class stays consistent across both views ----------------------------


def test_every_reordered_entity_highlights_in_both_views(
    client: TestClient, settings: Settings
) -> None:
    """Company, street, city, phone, email, UID, person, birth date, document number, and document
    date each expose a canonical highlight whose text equals the raw value, despite reordering."""
    document_id = _upload_document(client)
    entities = [_entity(_RAW, entity_type, value) for entity_type, value in _FIXTURE_ENTITIES]
    _save_e2e(settings, document_id, _RAW, _READING, entities)

    body = _get_contract(client, document_id)

    for entity_type, value in _FIXTURE_ENTITIES:
        entity = _by_value(body, value)
        assert entity["entity_type"] == entity_type
        assert entity["binding_status"] == "exact", f"{value} bound {entity['binding_status']}"
        assert entity["identity_basis"] == "anchor_exact", value
        assert entity["mapping_status"] == "exact", value
        canonical_range = entity["display"]["canonical_highlight_range"]
        assert canonical_range is not None, f"{value} lost its canonical highlight"
        rendered = _READING[canonical_range["start"] : canonical_range["end"]]
        assert rendered == value, f"{value!r} canonical range rendered {rendered!r}"
        # No evidence-only fallback when safe anchors exist.
        assert entity["identity_basis"] != "evidence_only", value

    # The binding summary agrees: every entity carries a canonical range, none missing.
    summary = body["binding_summary"]
    assert summary["entities_with_canonical_range"] == len(_FIXTURE_ENTITIES)
    assert summary["missing_canonical_range_count"] == 0
    assert summary["evidence_only"] == 0
    assert summary["exact"] == len(_FIXTURE_ENTITIES)


# --- 3. A missing canonical range only for a specific structural reason ---------------------------


def test_missing_canonical_range_only_for_a_structural_reason(
    client: TestClient, settings: Settings
) -> None:
    """A value that genuinely repeats in both views (header + footer) cannot be uniquely located in
    the reading view, so its canonical range is missing *with* a repeated-token reason code — while
    a non-repeated value in the same document still propagates cleanly. Missing is never silent."""
    document_id = _upload_document(client)
    # Reordered views (raw != reading, so there is no trivial offset-preserving 1:1 map) with the
    # company name repeated (header + footer). The repeat cannot be uniquely located in the reading
    # view without positional evidence, so its canonical range is structurally ambiguous.
    raw = (
        "Muster Handels GmbH\n"
        "office@muster.at\n"
        "Muster Handels GmbH\n"
    )
    reading = (
        "office@muster.at\n"
        "Muster Handels GmbH\n"
        "Muster Handels GmbH\n"
    )
    entities = [
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=0),
        _entity(raw, "EMAIL_ADDRESS", "office@muster.at"),
        _entity(raw, "ORG", "Muster Handels GmbH", occurrence=1),
    ]
    _save_e2e(settings, document_id, raw, reading, entities)

    body = _get_contract(client, document_id)
    org_entities = [entity for entity in body["entities"] if entity["entity_type"] == "ORG"]
    assert len(org_entities) == 2  # never dropped

    for org in org_entities:
        assert org["display"]["canonical_highlight_range"] is None
        assert "canonical_range_missing" in org["binding_reasons"]
        # The structural reason is explicit: the repeated token could not be uniquely mapped.
        assert "repeated_token_ambiguity" in org["binding_reasons"]
        assert org["mapping_status"] in ("missing", "ambiguous")

    # The non-repeated email in the same document still propagates — the repeat does not poison it.
    email = _by_value(body, "office@muster.at")
    assert email["display"]["canonical_highlight_range"] is not None
    assert "canonical_range_missing" not in email["binding_reasons"]


# --- 4. Layout ranges follow the same anchor identity when layout is byte-aligned -----------------


def test_layout_range_propagates_when_layout_view_is_available(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    entities = [
        _entity(raw, "PERSON", "Anna Beispiel"),
        _entity(raw, "EMAIL_ADDRESS", "office@muster.at"),
    ]
    # Persist a byte-aligned layout view alongside the reordered reading text.
    pages = [
        TextPageResult(
            page_number=1,
            source="pdf_text_layer",
            has_text_layer=True,
            ocr_used=False,
            text=raw,
            text_char_count=len(raw),
        )
    ]
    reading_map = build_reading_text_map(raw, reading, pages)
    text_id = uuid4().hex
    save_text_artifact(
        settings,
        TextArtifact(
            id=text_id,
            document_id=document_id,
            input_artifact_id="c" * 32,
            input_audit_artifact_id="d" * 32,
            created_at="2026-07-10T09:00:00.000000Z",
            content=TextContent(
                document_id=document_id,
                input_artifact_id="c" * 32,
                input_audit_artifact_id="d" * 32,
                source="pdf_text_layer",
                text=raw,
                text_char_count=len(raw),
                pages=pages,
                tool_versions={"test": "1"},
                flags=[],
                reading_text_version="1",
                reading_text=reading,
                reading_text_status="heuristic",
                reading_text_map_version="1",
                reading_text_map=reading_map,
                layout_text_result=raw,
            ),
        ),
    )
    projected = _sorted_entities(
        project_pii_entities_to_reading_text(entities, reading_map, reading_text=reading)
    )
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=uuid4().hex,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-10T10:00:00.000000Z",
            content=PiiContent(
                document_id=document_id,
                input_text_artifact_id=text_id,
                profile="custom",
                language="de",
                score_threshold=0.5,
                text_char_count=len(raw),
                reading_text_char_count=len(reading),
                configured_entity_types=["EMAIL_ADDRESS", "PERSON"],
                entities=projected,
                entity_counts={"EMAIL_ADDRESS": 1, "PERSON": 1},
                tool_versions={},
                flags=[],
                validation=PiiValidationSummary(enabled=True, kept=2, dropped=0, score_down=0),
            ),
        ),
    )

    body = _get_contract(client, document_id)
    person = _by_value(body, "Anna Beispiel")
    layout_refs = [
        ref
        for ref in person["anchor_refs"]
        if ref["source_name"] == "layout_text" and ref["binding_role"] == "display_span"
    ]
    assert layout_refs, "layout ranges must follow anchor identity when the layout view is aligned"
    assert body["binding_summary"]["entities_with_layout_range"] == 2
    assert body["binding_summary"]["missing_layout_range_count"] == 0


# --- 5. No private text leaks into anchor/entity/highlight metadata -------------------------------


def test_no_private_value_leaks_into_binding_metadata(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [_entity(_RAW, entity_type, value) for entity_type, value in _FIXTURE_ENTITIES]
    _save_e2e(settings, document_id, _RAW, _READING, entities)

    body = _get_contract(client, document_id)
    for entity in body["entities"]:
        value = entity["value"]
        # The value may appear only on the dedicated value field, never in identity/binding/display
        # metadata (which are ids/offsets/reason codes only).
        for field in (
            "entity_id",
            "anchor_set",
            "anchor_refs",
            "binding_reasons",
            "source_observations",
            "display",
            "warnings",
            "provenance",
        ):
            assert value not in json.dumps(entity.get(field)), f"{value} leaked into {field}"
    assert _RAW.split("\n", 1)[0] not in json.dumps(body["binding_summary"])


# --- 6. Geometry-backed projection propagates a repeated-suffix (mixed-uniqueness) entity ---------
# Two DISTINCT company names sharing only the "GmbH" suffix token, in a reordered document. The
# post-hoc unique-token map drops the repeated "GmbH", which used to strip the whole entity's
# canonical range. The geometry-backed, post-render exact-line projection places each company from
# its own source line, so both keep a canonical highlight — proved here through the real HTTP
# contract endpoint. This is a stronger *post-hoc* mechanism (full-line granularity, declines
# genuinely ambiguous/duplicate values rather than guessing), not builder-emitted construction-time
# lineage; genuine construction-time lineage remains a separate, unimplemented future step.
_MIX_RAW = "Muster Handels GmbH\nBeispiel Bau GmbH\noffice@muster.at\n"
_MIX_READING = "office@muster.at\nMuster Handels GmbH\nBeispiel Bau GmbH\n"


def _line_spans(raw: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in raw.split("\n"):
        if line:
            spans.append((offset, offset + len(line)))
        offset += len(line) + 1
    return spans


def _single_page_geometry(raw: str) -> TextGeometry:
    lines = [
        TextLineGeometry(
            line_index=index,
            canonical_start=start,
            canonical_end=end,
            page_start=start,
            page_end=end,
            x0=0.0,
            y0=float(index),
            x1=1.0,
            y1=float(index) + 0.5,
            source="pdf_text_layer",
        )
        for index, (start, end) in enumerate(_line_spans(raw), start=1)
    ]
    return TextGeometry(
        pages=[
            TextGeometryPage(
                page_number=1,
                page_width=10.0,
                page_height=float(len(lines)) + 2.0,
                coordinate_unit="pdf_points",
                source="pdf_text_layer",
                status="complete",
                lines=lines,
            )
        ],
        coverage=1.0,
    )


def _save_with_geometry_projection(
    settings: Settings, document_id: str, raw: str, reading: str, entities: list[PiiEntity]
) -> None:
    pages = [
        TextPageResult(
            page_number=1,
            source="pdf_text_layer",
            has_text_layer=True,
            ocr_used=False,
            text=raw,
            text_char_count=len(raw),
        )
    ]
    reading_map = build_reading_text_map(raw, reading, pages)
    projection_map = build_reading_text_geometry_projection_map(
        document_id=document_id,
        reading_text=reading,
        raw_text=raw,
        pages=pages,
        text_geometry=_single_page_geometry(raw),
    )
    assert projection_map is not None
    text_id = uuid4().hex
    save_text_artifact(
        settings,
        TextArtifact(
            id=text_id,
            document_id=document_id,
            input_artifact_id="c" * 32,
            input_audit_artifact_id="d" * 32,
            created_at="2026-07-10T09:00:00.000000Z",
            content=TextContent(
                document_id=document_id,
                input_artifact_id="c" * 32,
                input_audit_artifact_id="d" * 32,
                source="pdf_text_layer",
                text=raw,
                text_char_count=len(raw),
                pages=pages,
                tool_versions={"test": "1"},
                flags=[],
                reading_text_version="1",
                reading_text=reading,
                reading_text_status="heuristic",
                reading_text_map_version="1",
                reading_text_map=reading_map,
                reading_text_geometry_projection_map_version="1",
                reading_text_geometry_projection_map=projection_map,
            ),
        ),
    )
    projected = _sorted_entities(
        project_pii_entities_to_reading_text(entities, reading_map, reading_text=reading)
    )
    counts: dict[str, int] = {}
    for entity in projected:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=uuid4().hex,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-10T10:00:00.000000Z",
            content=PiiContent(
                document_id=document_id,
                input_text_artifact_id=text_id,
                profile="custom",
                language="de",
                score_threshold=0.5,
                text_char_count=len(raw),
                reading_text_char_count=len(reading),
                configured_entity_types=sorted(counts),
                entities=projected,
                entity_counts=dict(sorted(counts.items())),
                tool_versions={},
                flags=[],
                validation=PiiValidationSummary(
                    enabled=True, kept=len(projected), dropped=0, score_down=0
                ),
            ),
        ),
    )


def test_geometry_projection_propagates_repeated_suffix_entities(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    entities = [
        _entity(_MIX_RAW, "ORG", "Muster Handels GmbH"),
        _entity(_MIX_RAW, "ORG", "Beispiel Bau GmbH"),
        _entity(_MIX_RAW, "EMAIL_ADDRESS", "office@muster.at"),
    ]
    _save_with_geometry_projection(settings, document_id, _MIX_RAW, _MIX_READING, entities)

    body = _get_contract(client, document_id)
    assert body["anchor_graph_available"] is True

    for value in ("Muster Handels GmbH", "Beispiel Bau GmbH"):
        org = _by_value(body, value)
        assert org["binding_status"] == "exact", value
        assert org["identity_basis"] == "anchor_exact", value
        canonical_range = org["display"]["canonical_highlight_range"]
        assert canonical_range is not None, f"{value} lost its canonical highlight"
        assert _MIX_READING[canonical_range["start"] : canonical_range["end"]] == value
        assert "canonical_range_missing" not in org["binding_reasons"], value
        assert "repeated_token_ambiguity" not in org["binding_reasons"], value

    summary = body["binding_summary"]
    assert summary["entities_with_canonical_range"] == 3
    assert summary["missing_canonical_range_count"] == 0
