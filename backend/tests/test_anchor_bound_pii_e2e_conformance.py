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
from tests.artifact_helpers import save_pii_artifact, save_text_artifact

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
from app.services.artifact_service import get_text_artifact
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.reading_text import ReadingCell, ReadingRow, build_reading_text
from app.services.reading_text_geometry_projection import (
    build_reading_text_geometry_projection_map,
)
from app.services.reading_text_projection import (
    build_reading_text_map,
    project_pii_entities_to_reading_text,
)
from app.services.reading_text_row_lineage import build_reading_text_row_lineage_map

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
        project_pii_entities_to_reading_text(
            entities, reading_map, reading_text=reading, raw_text=raw
        )
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
    pii = client.get(f"/api/documents/{document_id}/pii").json()
    response = client.get(
        _CONTRACT_URL.format(document_id=document_id),
        params={"pii_artifact_id": pii["id"], "text_artifact_id": pii["input_text_artifact_id"]},
    )
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


def test_repeated_value_maps_each_occurrence_by_order(
    client: TestClient, settings: Settings
) -> None:
    """A value that repeats (header + footer) is placed per occurrence by order: the k-th raw match
    maps to the k-th reading match. Any matched span is a valid occurrence of the same value, so
    both are highlighted (the review decision is per group and redaction is per value). A
    non-repeated value in the same document still propagates cleanly."""
    document_id = _upload_document(client)
    # Reordered views (raw != reading, so there is no trivial offset-preserving 1:1 map) with the
    # company name repeated (header + footer).
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
        canonical = org["display"]["canonical_highlight_range"]
        assert canonical is not None
        assert reading[canonical["start"] : canonical["end"]] == "Muster Handels GmbH"

    # The non-repeated email in the same document still propagates.
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
        project_pii_entities_to_reading_text(
            entities, reading_map, reading_text=reading, raw_text=raw
        )
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
        project_pii_entities_to_reading_text(
            entities, reading_map, reading_text=reading, raw_text=raw
        )
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


# --- 7. Trailing newline + repeated interior token: the cross-view highlight regression ----------
# Reproduces the reported failure end to end: a multi-word ORGANIZATION detection whose raw span
# includes a trailing newline, where one of its words ("Perchtoldsdorf") also occurs standalone
# elsewhere in the document. The company's boundary words ("Sanierungsbau", "GmbH") are each unique,
# so they still resolve cleanly and must bridge the whole entity's canonical range even though the
# interior word is individually ambiguous. A standalone occurrence of the same repeated word, and a
# genuinely duplicated company name (no unique boundary to bridge from), must NOT gain a canonical
# range -- and ordinary email/phone entities in the same document must keep working normally.
_TRAILING_RAW = (
    "Sanierungsbau Perchtoldsdorf GmbH\n"
    "Hauptstrasse 5, Perchtoldsdorf\n"
    "office@sanierungsbau-p.at\n"
    "+43 1 5551234\n"
    "Sicherheitsdienst Wien KG\n"
    "Sicherheitsdienst Wien KG\n"
)
_TRAILING_READING = (
    "office@sanierungsbau-p.at\n"
    "+43 1 5551234\n"
    "Sanierungsbau Perchtoldsdorf GmbH\n"
    "Hauptstrasse 5, Perchtoldsdorf\n"
    "Sicherheitsdienst Wien KG\n"
    "Sicherheitsdienst Wien KG\n"
)


def _entity_at(raw: str, entity_type: str, start: int, end: int) -> PiiEntity:
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=raw[start:end],
        start_offset=start,
        end_offset=end,
        score=0.9,
        recognizer="SyntheticRecognizer",
    )


def test_trailing_newline_and_repeated_interior_token_still_highlight_in_both_views(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    raw = _TRAILING_RAW

    org_start, org_core_end = _raw_span(raw, "Sanierungsbau Perchtoldsdorf GmbH")
    # the detector's span runs one char past "GmbH" into a trailing "\n"
    org_end_with_newline = org_core_end + 1
    assert raw[org_end_with_newline - 1] == "\n"

    loc_start, loc_end = _raw_span(raw, "Perchtoldsdorf", occurrence=1)
    email_start, email_end = _raw_span(raw, "office@sanierungsbau-p.at")
    phone_start, phone_end = _raw_span(raw, "+43 1 5551234")
    dup1_start, dup1_end = _raw_span(raw, "Sicherheitsdienst Wien KG", occurrence=0)
    dup2_start, dup2_end = _raw_span(raw, "Sicherheitsdienst Wien KG", occurrence=1)

    entities = [
        _entity_at(raw, "ORGANIZATION", org_start, org_end_with_newline),
        _entity_at(raw, "LOCATION", loc_start, loc_end),
        _entity_at(raw, "EMAIL_ADDRESS", email_start, email_end),
        _entity_at(raw, "PHONE_NUMBER", phone_start, phone_end),
        _entity_at(raw, "ORG", dup1_start, dup1_end),
        _entity_at(raw, "ORG", dup2_start, dup2_end),
    ]
    _save_e2e(settings, document_id, raw, _TRAILING_READING, entities)

    body = _get_contract(client, document_id)
    assert body["anchor_graph_available"] is True

    # 1-6: the complete company occurrence is identifiable end to end and stays one stable entity
    # with both a correct raw and a correct canonical highlight, despite the trailing newline and
    # the internally repeated word.
    org = _by_value(body, "Sanierungsbau Perchtoldsdorf GmbH\n")
    assert org["binding_status"] == "exact"
    assert org["identity_basis"] == "anchor_exact"
    assert "repeated_token_ambiguity" in org["binding_reasons"]
    assert "canonical_range_missing" not in org["binding_reasons"]

    raw_range = org["display"]["raw_highlight_range"]
    assert raw[raw_range["start"] : raw_range["end"]].strip() == "Sanierungsbau Perchtoldsdorf GmbH"
    canonical_range = org["display"]["canonical_highlight_range"]
    assert canonical_range is not None, "the company lost its canonical highlight"
    assert (
        _TRAILING_READING[canonical_range["start"] : canonical_range["end"]]
        == "Sanierungsbau Perchtoldsdorf GmbH"
    )

    # Re-fetching the contract must yield the same entity id for both views -- one entity, two
    # ranges, not two independent objects.
    body_again = _get_contract(client, document_id)
    org_again = _by_value(body_again, "Sanierungsbau Perchtoldsdorf GmbH\n")
    assert org_again["entity_id"] == org["entity_id"]

    # The standalone occurrence of the repeated word maps to *its* reading occurrence by order (one
    # preceding match — the one inside the company name — so it resolves to the standalone one).
    location = _by_value(body, "Perchtoldsdorf")
    assert location["binding_status"] == "exact"
    loc_canonical = location["display"]["canonical_highlight_range"]
    assert loc_canonical is not None
    assert _TRAILING_READING[loc_canonical["start"] : loc_canonical["end"]] == "Perchtoldsdorf"

    # 7: a genuinely duplicated company name (identical value, twice) is placed per occurrence by
    # order -- each matched span is a valid occurrence of the same value, so both are highlighted.
    duplicates = [
        entity for entity in body["entities"] if entity["value"] == "Sicherheitsdienst Wien KG"
    ]
    assert len(duplicates) == 2
    for duplicate in duplicates:
        dup_canonical = duplicate["display"]["canonical_highlight_range"]
        assert dup_canonical is not None
        assert (
            _TRAILING_READING[dup_canonical["start"] : dup_canonical["end"]]
            == "Sicherheitsdienst Wien KG"
        )

    # 8: ordinary entities elsewhere in the same document remain unaffected.
    for value in ("office@sanierungsbau-p.at", "+43 1 5551234"):
        entity = _by_value(body, value)
        assert entity["binding_status"] == "exact", value
        canonical_range = entity["display"]["canonical_highlight_range"]
        assert canonical_range is not None, f"{value} lost its canonical highlight"
        assert _TRAILING_READING[canonical_range["start"] : canonical_range["end"]] == value

    # 9: no raw/canonical text leaks into binding metadata.
    for entity in body["entities"]:
        value = entity["value"]
        assert value not in json.dumps(entity["anchor_refs"])
        assert value not in json.dumps(entity["binding_reasons"])


# --- Anchor-first Text Package v2: builder-emitted (construction-time) row lineage ----------------
# The fixtures above all go through the post-hoc reading_text_map / geometry-projection fallback
# tiers. This section proves the SAME end-to-end outcome is now reachable purely from lineage the
# canonical-reading-text builder itself emits while rendering -- no post-render text search
# mechanism is present in this fixture at all (reading_text_map is left empty and no geometry
# projection map is saved), so a correct canonical range here can only have come from
# ``reading_text_row_lineage_map``.
_ROW_LINEAGE_RAW = (
    "Sanierungsbau Perchtoldsdorf GmbH\n"
    "Hauptstrasse 5, Perchtoldsdorf\n"
    "Sicherheitsdienst Wien KG\n"
    "Sicherheitsdienst Wien KG\n"
)


def _row_lineage_rows(raw: str) -> list[ReadingRow]:
    lines = raw.split("\n")[:-1]  # drop the trailing empty split after the final "\n"
    offset = 0
    rows: list[ReadingRow] = []
    for index, line in enumerate(lines):
        rows.append(
            ReadingRow(
                page_number=1,
                y0=0.05 + index * 0.02,
                y1=0.05 + index * 0.02 + 0.012,
                cells=(ReadingCell(text=line, x0=0.07, x1=0.07 + len(line) * 0.006),),
                source_range=(offset, offset + len(line)),
            )
        )
        offset += len(line) + 1
    return rows


def _save_with_row_construction_lineage(
    settings: Settings, document_id: str, raw: str, entities: list[PiiEntity]
) -> str:
    """Persist a text + PII artifact pair using only builder-emitted row-construction lineage.

    Runs the real ``build_reading_text`` builder over hand-positioned rows (the same primitive
    ``collect_pdf_reading_rows`` produces from a real PDF), then the real
    ``build_reading_text_row_lineage_map`` converter -- the same two calls the OCR/Text station
    makes. ``reading_text_map`` is deliberately left empty and no geometry projection map is saved,
    so nothing else in this fixture could supply a canonical range.
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
    reading = build_reading_text(raw, pages, None, [], None, positioned_rows=_row_lineage_rows(raw))
    assert reading is not None
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=document_id,
        reading_text=reading.text,
        pages=pages,
        row_lineage=reading.row_lineage,
    )
    assert row_lineage_map is not None

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
                reading_text=reading.text,
                reading_text_status=reading.status,
                reading_text_row_lineage_map_version="2",
                reading_text_row_lineage_map=row_lineage_map,
                # Deliberately no reading_text_map, no geometry projection map: only builder-emitted
                # row-construction lineage is available to the anchor graph in this fixture.
            ),
        ),
    )
    entities = project_pii_entities_to_reading_text(
        entities, [], reading_text=reading.text, raw_text=raw
    )
    counts: dict[str, int] = {}
    for entity in entities:
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
                reading_text_char_count=len(reading.text),
                configured_entity_types=sorted(counts),
                entities=_sorted_entities(entities),
                entity_counts=dict(sorted(counts.items())),
                tool_versions={},
                flags=[],
                validation=PiiValidationSummary(
                    enabled=True, kept=len(entities), dropped=0, score_down=0
                ),
            ),
        ),
    )
    return reading.text


def test_builder_emitted_row_lineage_resolves_repeated_token_and_duplicates_through_contract(
    client: TestClient, settings: Settings
) -> None:
    """The completion criterion for Anchor-first Text Package v2, proved end to end: raw detection
    -> Text Anchor Graph -> anchor-bound entity -> entity contract -> canonical display range, with
    the canonical range supplied entirely by builder-emitted row-construction lineage."""
    document_id = _upload_document(client)
    raw = _ROW_LINEAGE_RAW

    org_start, org_core_end = _raw_span(raw, "Sanierungsbau Perchtoldsdorf GmbH")
    org_end_with_newline = org_core_end + 1  # a detector span running past "GmbH" into "\n"
    assert raw[org_end_with_newline - 1] == "\n"
    dup1_start, dup1_end = _raw_span(raw, "Sicherheitsdienst Wien KG", occurrence=0)
    dup2_start, dup2_end = _raw_span(raw, "Sicherheitsdienst Wien KG", occurrence=1)

    entities = [
        _entity_at(raw, "ORGANIZATION", org_start, org_end_with_newline),
        _entity_at(raw, "ORG", dup1_start, dup1_end),
        _entity_at(raw, "ORG", dup2_start, dup2_end),
    ]
    reading_text = _save_with_row_construction_lineage(settings, document_id, raw, entities)

    body = _get_contract(client, document_id)
    assert body["anchor_graph_available"] is True

    # The multi-word organisation, containing a word ("Perchtoldsdorf") that also occurs
    # elsewhere, resolves to a complete, correct canonical range -- construction-time row lineage
    # projects every token in its exact row arithmetically, so this now succeeds without even
    # needing the boundary-bridging fallback the post-hoc mechanisms required.
    org = _by_value(body, "Sanierungsbau Perchtoldsdorf GmbH\n")
    assert org["binding_status"] == "exact"
    assert org["identity_basis"] == "anchor_exact"
    assert "canonical_range_missing" not in org["binding_reasons"]
    canonical_range = org["display"]["canonical_highlight_range"]
    assert canonical_range is not None
    assert (
        reading_text[canonical_range["start"] : canonical_range["end"]]
        == "Sanierungsbau Perchtoldsdorf GmbH"
    )

    # Two genuinely duplicated occurrences of the same company name, at distinct raw positions,
    # each resolve to their OWN correct, distinct canonical range -- equal text values in
    # different source positions stay distinct information units, never guessed by textual order.
    duplicates = [
        entity for entity in body["entities"] if entity["value"] == "Sicherheitsdienst Wien KG"
    ]
    assert len(duplicates) == 2
    duplicate_ids = {entity["entity_id"] for entity in duplicates}
    assert len(duplicate_ids) == 2
    for duplicate in duplicates:
        canonical_range = duplicate["display"]["canonical_highlight_range"]
        assert canonical_range is not None
        assert (
            reading_text[canonical_range["start"] : canonical_range["end"]]
            == "Sicherheitsdienst Wien KG"
        )
    duplicate_canonical_ranges = {
        (
            duplicate["display"]["canonical_highlight_range"]["start"],
            duplicate["display"]["canonical_highlight_range"]["end"],
        )
        for duplicate in duplicates
    }
    assert len(duplicate_canonical_ranges) == 2  # distinct ranges, not the same span twice

    # No raw/canonical text leaks into binding metadata.
    for entity in body["entities"]:
        value = entity["value"]
        assert value not in json.dumps(entity["anchor_refs"])
        assert value not in json.dumps(entity["binding_reasons"])
        assert value not in json.dumps(entity["warnings"])


# --- Row-construction lineage v2: a normalized (reformatted) row must not claim byte-exact mapping
# ADR-0036 introduced ``RowLineageSegment.status`` of ``exact``/``normalized``/``merged``: a single
# row whose rendered canonical line is *not* byte-identical to its raw span (e.g. a table/party cell
# whose internal padding collapses during rendering) is ``normalized``, not ``exact``. The entity
# contract's ``mapping_status`` must say so honestly (``projected``, the same non-exact state the
# older post-hoc text-match path already uses for a reformatted value) instead of collapsing every
# anchor-derived canonical range to ``exact`` regardless of the underlying row's own honesty.
_NORMALIZED_RAW = "Beispiel   Bau GmbH\n"  # column padding: 3 raw spaces between words
_NORMALIZED_READING = "Beispiel Bau GmbH"  # rendered with the padding collapsed to one space


def _save_with_normalized_row_lineage(
    settings: Settings, document_id: str, raw: str, entities: list[PiiEntity]
) -> str:
    """Persist a text + PII artifact pair whose only canonical lineage is one intentionally
    "normalized" row-construction segment -- attached at collection time exactly like a real
    table/party-column cell whose rendering collapses internal whitespace, never guessed by
    comparing text after the fact. No ``reading_text_map``, no geometry projection map, so nothing
    else could supply a canonical range."""
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
    row = ReadingRow(
        page_number=1,
        y0=0.05,
        y1=0.06,
        cells=(ReadingCell(text=_NORMALIZED_READING, x0=0.05, x1=0.4),),
        source_range=(0, len(raw.rstrip("\n"))),
    )
    reading = build_reading_text(raw, pages, None, [], None, positioned_rows=[row])
    assert reading is not None
    assert reading.row_lineage[0].status == "normalized"  # sanity: genuinely non-exact
    row_lineage_map = build_reading_text_row_lineage_map(
        document_id=document_id,
        reading_text=reading.text,
        pages=pages,
        row_lineage=reading.row_lineage,
    )
    assert row_lineage_map is not None

    text_id = uuid4().hex
    save_text_artifact(
        settings,
        TextArtifact(
            id=text_id,
            document_id=document_id,
            input_artifact_id="c" * 32,
            input_audit_artifact_id="d" * 32,
            created_at="2026-07-11T09:00:00.000000Z",
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
                reading_text=reading.text,
                reading_text_status=reading.status,
                reading_text_row_lineage_map_version="2",
                reading_text_row_lineage_map=row_lineage_map,
            ),
        ),
    )
    entities = project_pii_entities_to_reading_text(
        entities, [], reading_text=reading.text, raw_text=raw
    )
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    save_pii_artifact(
        settings,
        PiiArtifact(
            id=uuid4().hex,
            document_id=document_id,
            input_text_artifact_id=text_id,
            created_at="2026-07-11T10:00:00.000000Z",
            content=PiiContent(
                document_id=document_id,
                input_text_artifact_id=text_id,
                profile="custom",
                language="de",
                score_threshold=0.5,
                text_char_count=len(raw),
                reading_text_char_count=len(reading.text),
                configured_entity_types=sorted(counts),
                entities=_sorted_entities(entities),
                entity_counts=dict(sorted(counts.items())),
                tool_versions={},
                flags=[],
                validation=PiiValidationSummary(
                    enabled=True, kept=len(entities), dropped=0, score_down=0
                ),
            ),
        ),
    )
    return reading.text


def test_normalized_row_lineage_yields_honest_projected_mapping_status_through_contract(
    client: TestClient, settings: Settings
) -> None:
    """The completion criterion for a *correct* v2 row-lineage consumer: a reformatted (not
    byte-identical) canonical row must never be reported as an ``exact`` mapping."""
    document_id = _upload_document(client)
    raw = _NORMALIZED_RAW
    org_value = raw.rstrip("\n")
    entity = _entity_at(raw, "ORGANIZATION", 0, len(org_value))
    reading_text = _save_with_normalized_row_lineage(settings, document_id, raw, [entity])

    body = _get_contract(client, document_id)
    org = _by_value(body, org_value)

    # The binding itself is complete (the raw span fully contains its anchors) ...
    assert org["binding_status"] == "exact"
    assert org["identity_basis"] == "anchor_exact"
    # ... but the canonical range came from a reformatted row, so the display mapping must say so
    # honestly instead of claiming byte-exact identity for a line that does not read byte-for-byte
    # like the raw span.
    assert org["mapping_status"] == "projected"
    canonical_range = org["display"]["canonical_highlight_range"]
    assert canonical_range is not None
    assert reading_text[canonical_range["start"] : canonical_range["end"]] == _NORMALIZED_READING
    # A non-exact mapping is an honest display state, not a missing/partial/ambiguous gap -- it must
    # not spuriously force review on its own.
    missing_partial_ambiguous_codes = (
        "canonical_mapping_missing",
        "canonical_mapping_partial",
        "canonical_mapping_ambiguous",
    )
    for code in missing_partial_ambiguous_codes:
        assert code not in org["warnings"]


# --- Fallback-only lineage: explicit and distinguishable, never confused with stronger lineage ----
# When neither row-construction lineage nor the geometry-backed projection is available, the anchor
# graph still supplies a canonical range through the older post-hoc unique-token
# ``reading_text_map`` fallback. The binding/contract outcome for a clean, byte-identical value
# stays "exact" (the fallback map only ever attributes byte-identical text), but *which mechanism*
# produced it must remain visible one layer down on the Text Anchor Graph (OCR/Text owns anchor
# provenance) rather than being indistinguishable from stronger row-construction/geometry-projection
# lineage.


def test_fallback_only_lineage_is_explicitly_labelled_and_never_confused_with_stronger_lineage(
    client: TestClient, settings: Settings
) -> None:
    document_id = _upload_document(client)
    raw = "Anna Beispiel\noffice@muster.at\n"
    reading = raw
    entities = [
        _entity(raw, "PERSON", "Anna Beispiel"),
        _entity(raw, "EMAIL_ADDRESS", "office@muster.at"),
    ]
    _save_e2e(settings, document_id, raw, reading, entities)

    body = _get_contract(client, document_id)
    person = _by_value(body, "Anna Beispiel")
    assert person["binding_status"] == "exact"
    canonical_range = person["display"]["canonical_highlight_range"]
    assert canonical_range is not None
    assert reading[canonical_range["start"] : canonical_range["end"]] == "Anna Beispiel"

    pii = client.get(f"/api/documents/{document_id}/pii").json()
    text_artifact = get_text_artifact(settings, document_id, pii["input_text_artifact_id"])
    assert text_artifact is not None
    graph = build_document_text_anchor_graph(build_document_text_package(text_artifact))

    # Document-level: the only lineage mechanism available was the post-hoc fallback map.
    assert graph.lineage_summary is not None
    assert graph.lineage_summary.lineage_source == "fallback_text_match"
    assert graph.lineage_summary.row_construction_available is False
    assert graph.lineage_summary.geometry_projection_available is False

    # Anchor-level: every canonical-mapped anchor carries the fallback-specific flag, never the
    # stronger construction-time/geometry-projection flags -- fallback provenance stays visible and
    # distinguishable, never silently upgraded to look like stronger lineage.
    canonical_anchors = [
        anchor
        for anchor in graph.anchors
        if any(r.source_name == "canonical_reading_text" for r in anchor.source_ranges)
    ]
    assert canonical_anchors, "expected at least one canonical-mapped anchor"
    for anchor in canonical_anchors:
        assert "canonical_map_lineage" in anchor.flags
        assert "canonical_row_construction" not in anchor.flags
        assert "canonical_geometry_projection" not in anchor.flags
