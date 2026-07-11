"""Synthetic unit tests for the anchor-binding / normalization service (ADR-0031 Phase C).

All data is synthetic. The service turns offset-based PII detections (detection evidence) plus the
OCR/Text Text Anchor Graph v1 into stable anchor-bound PII entities: identity derives from anchor
identity where an exact binding exists, missing/partial/ambiguous binding is explicit and never
drops a detection, and no raw token text ever enters binding metadata.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from app.schemas import (
    DocumentTextAnchorGraphSummary,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorGraphValidation,
    DocumentTextAnchorRange,
    DocumentTextAnchorSource,
    DocumentTextAnchorV1,
    PiiEntity,
    PiiEntityProvenance,
    ReadingTextMapSegment,
    TextArtifact,
    TextContent,
    TextPageResult,
)
from app.services.document_text_anchors import build_document_text_anchor_graph
from app.services.document_text_package import build_document_text_package
from app.services.pii_anchor_binding import bind_pii_entities_to_anchors
from app.services.reading_text_projection import build_reading_text_map


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


_DOCUMENT_ID = _hex("bind-document")
_ORIGINAL_ID = _hex("bind-original")
_AUDIT_ID = _hex("bind-audit")
_TEXT_ID = _hex("bind-text")


def _entity(
    entity_type: str,
    text: str,
    start: int,
    *,
    score: float = 0.9,
    recognizer: str = "TestRecognizer",
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
        provenance=provenance,
    )


def _segment(
    reading_start: int, reading_end: int, raw_start: int, raw_end: int
) -> ReadingTextMapSegment:
    return ReadingTextMapSegment(
        reading_start=reading_start,
        reading_end=reading_end,
        raw_start=raw_start,
        raw_end=raw_end,
        mapping_status="exact",
    )


def _graph_from_raw(
    raw: str,
    *,
    reading: str | None = None,
    reading_map: list[ReadingTextMapSegment] | None = None,
    layout: str | None = None,
) -> DocumentTextAnchorGraphV1:
    content = TextContent(
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        source="docx_text",
        text=raw,
        text_char_count=len(raw),
        pages=[],
        tool_versions={"test": "1"},
        flags=[],
        reading_text_version=("1" if reading is not None else None),
        reading_text=reading,
        reading_text_status=("heuristic" if reading is not None else None),
        reading_text_map_version=("1" if reading is not None else None),
        reading_text_map=reading_map or [],
        layout_text_result=layout,
    )
    artifact = TextArtifact(
        id=_TEXT_ID,
        document_id=_DOCUMENT_ID,
        input_artifact_id=_ORIGINAL_ID,
        input_audit_artifact_id=_AUDIT_ID,
        created_at="2026-07-09T10:00:00.000000Z",
        content=content,
    )
    return build_document_text_anchor_graph(build_document_text_package(artifact))


def _manual_raw_graph(
    raw_char_count: int, spans: list[tuple[int, int]]
) -> DocumentTextAnchorGraphV1:
    """A hand-built raw-only anchor graph for cases the real builder cannot produce (e.g. a raw span
    with no overlapping anchor, or two mutually overlapping raw anchors)."""
    anchors = [
        DocumentTextAnchorV1(
            anchor_id=_hex(f"manual-anchor-{index}-{start}-{end}"),
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
        for index, (start, end) in enumerate(spans)
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
        warnings=warnings,  # type: ignore[arg-type]
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
        document_id=_DOCUMENT_ID,
        text_artifact_id=_TEXT_ID,
        source_artifact_id=_TEXT_ID,
        package_id=_TEXT_ID,
        package_contract_version="1.0",
        created_at="2026-07-09T10:00:00.000000Z",
        sources=sources,
        anchors=anchors,
        summary=summary,
        validation=validation,
        warnings=warnings,  # type: ignore[arg-type]
    )


def _bind(entities: list[PiiEntity], graph: DocumentTextAnchorGraphV1 | None) -> list:
    bound, _summary = bind_pii_entities_to_anchors(entities, graph, document_id=_DOCUMENT_ID)
    return bound


# --- exact / partial / missing / ambiguous -------------------------------------------------------


def test_detection_binds_exactly_to_one_anchor() -> None:
    graph = _graph_from_raw("Wien")
    [entity] = _bind([_entity("LOCATION", "Wien", 0)], graph)

    assert entity.binding_status == "exact"
    assert entity.identity_basis == "anchor_exact"
    assert entity.anchor_set.anchor_ids == [graph.anchors[0].anchor_id]
    assert entity.anchor_set.count == 1
    entity_span_refs = [ref for ref in entity.anchor_refs if ref.binding_role == "entity_span"]
    assert len(entity_span_refs) == 1
    assert entity_span_refs[0].binding_status == "exact"
    assert entity_span_refs[0].reason_codes == ["anchor_exact_match"]


def test_detection_spanning_multiple_tokens_binds_to_multiple_anchors() -> None:
    graph = _graph_from_raw("Max Mustermann")
    [entity] = _bind([_entity("PERSON", "Max Mustermann", 0)], graph)

    assert entity.binding_status == "exact"
    assert len(entity.anchor_set.anchor_ids) == 2
    entity_anchor_ref_ids = {
        ref.anchor_id for ref in entity.anchor_refs if ref.binding_role == "entity_span"
    }
    assert entity_anchor_ref_ids == set(entity.anchor_set.anchor_ids)


def test_exact_binding_emits_canonical_and_layout_display_refs_when_available() -> None:
    raw = "Max Mustermann"
    graph = _graph_from_raw(
        raw,
        reading=raw,
        reading_map=[_segment(0, len(raw), 0, len(raw))],
        layout=raw,
    )
    [entity] = _bind([_entity("PERSON", raw, 0)], graph)

    assert entity.binding_status == "exact"
    canonical_refs = [
        ref for ref in entity.anchor_refs if ref.source_name == "canonical_reading_text"
    ]
    layout_refs = [ref for ref in entity.anchor_refs if ref.source_name == "layout_text"]
    assert len(canonical_refs) == entity.anchor_set.count
    assert len(layout_refs) == entity.anchor_set.count
    assert "canonical_range_missing" not in entity.binding_reasons
    assert "layout_range_missing" not in entity.binding_reasons


def test_partial_overlap_produces_partial_status() -> None:
    graph = _graph_from_raw("Max Mustermann")
    # "Max Muster" cuts through the second token, so the binding is partial, not exact.
    [entity] = _bind([_entity("PERSON", "Max Muster", 0)], graph)

    assert entity.binding_status == "partial"
    assert entity.identity_basis == "anchor_partial"
    assert "anchor_partial_overlap" in entity.binding_reasons
    assert "canonical_range_missing" in entity.binding_reasons
    assert "layout_range_missing" in entity.binding_reasons
    statuses = {
        ref.binding_status for ref in entity.anchor_refs if ref.binding_role == "entity_span"
    }
    assert statuses == {"exact", "partial"}


def test_partial_binding_does_not_emit_whole_anchor_display_refs() -> None:
    raw = "Max Mustermann"
    graph = _graph_from_raw(
        raw,
        reading=raw,
        reading_map=[_segment(0, len(raw), 0, len(raw))],
        layout=raw,
    )
    [entity] = _bind([_entity("PERSON", "Max Muster", 0)], graph)

    assert entity.binding_status == "partial"
    assert [
        ref for ref in entity.anchor_refs if ref.binding_role == "display_span"
    ] == []
    assert "canonical_range_missing" in entity.binding_reasons
    assert "layout_range_missing" in entity.binding_reasons


# --- trailing non-semantic slack / boundary bridging --------------------------------------------


def test_trailing_newline_in_detection_span_stays_exact_with_canonical_display() -> None:
    # A detector may report a span that runs one character past the last word into whitespace the
    # tokenizer never anchors (e.g. a trailing line break). That slack must not turn a complete
    # multi-token binding into a partial one, nor block its canonical display range.
    raw = "Max Mustermann\n"
    reading = "Max Mustermann"
    graph = _graph_from_raw(
        raw, reading=reading, reading_map=[_segment(0, len(reading), 0, len(reading))]
    )
    [entity] = _bind([_entity("PERSON", raw, 0)], graph)

    assert entity.binding_status == "exact"
    assert entity.identity_basis == "anchor_exact"
    assert entity.raw_text_range.start == 0
    assert entity.raw_text_range.end == len(raw)
    canonical_refs = [
        ref
        for ref in entity.anchor_refs
        if ref.source_name == "canonical_reading_text" and ref.binding_role == "display_span"
    ]
    assert len(canonical_refs) == entity.anchor_set.count
    assert "canonical_range_missing" not in entity.binding_reasons


def test_genuine_mid_token_cut_still_partial() -> None:
    # Contrast with the above: cutting through the middle of a token is a real partial overlap, not
    # trimmable slack, and must still be classified "partial".
    graph = _graph_from_raw("Max Mustermann")
    [entity] = _bind([_entity("PERSON", "Max Muster", 0)], graph)

    assert entity.binding_status == "partial"


def test_repeated_interior_token_does_not_destroy_entity_canonical_range() -> None:
    # "Perchtoldsdorf" is the middle word of the company name and also appears standalone
    # elsewhere in the document (as part of an address line). That makes its own anchor
    # individually ambiguous, but the company name's boundary anchors ("Sanierungsbau", "GmbH")
    # are each unique and resolve cleanly -- strong enough evidence to bridge the whole entity's
    # canonical range without ever resolving the interior anchor's own ambiguity.
    raw = "Sanierungsbau Perchtoldsdorf GmbH\nHauptstrasse 5, Perchtoldsdorf\n"
    reading = "Hauptstrasse 5, Perchtoldsdorf\nSanierungsbau Perchtoldsdorf GmbH\n"
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
    graph = _graph_from_raw(raw, reading=reading, reading_map=reading_map)

    org_start = raw.index("Sanierungsbau")
    org_end = org_start + len("Sanierungsbau Perchtoldsdorf GmbH")
    [entity] = _bind(
        [_entity("ORGANIZATION", raw[org_start:org_end], org_start)], graph
    )

    assert entity.binding_status == "exact"
    assert entity.identity_basis == "anchor_exact"
    assert "repeated_token_ambiguity" in entity.binding_reasons
    assert "canonical_range_missing" not in entity.binding_reasons

    canonical_refs = [
        ref
        for ref in entity.anchor_refs
        if ref.source_name == "canonical_reading_text" and ref.binding_role == "display_span"
    ]
    assert canonical_refs, "expected a bridged canonical display range"
    start = min(ref.source_range.start for ref in canonical_refs)
    end = max(ref.source_range.end for ref in canonical_refs)
    assert reading[start:end] == "Sanierungsbau Perchtoldsdorf GmbH"


def test_ambiguous_single_token_entity_stays_without_canonical_range() -> None:
    # Contrast with the above: when the *entire* entity is the one repeated, ambiguous token (no
    # unique boundary anchor of its own to bridge from), the canonical range correctly stays
    # absent rather than being guessed.
    raw = "Sanierungsbau Perchtoldsdorf GmbH\nHauptstrasse 5, Perchtoldsdorf\n"
    reading = "Hauptstrasse 5, Perchtoldsdorf\nSanierungsbau Perchtoldsdorf GmbH\n"
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
    graph = _graph_from_raw(raw, reading=reading, reading_map=reading_map)

    loc_start = raw.index("Perchtoldsdorf", raw.index("Hauptstrasse"))
    [entity] = _bind([_entity("LOCATION", "Perchtoldsdorf", loc_start)], graph)

    assert entity.binding_status == "exact"  # anchor identity is still solid
    assert entity.anchor_refs[0].source_range.start == loc_start
    canonical_refs = [
        ref
        for ref in entity.anchor_refs
        if ref.source_name == "canonical_reading_text" and ref.binding_role == "display_span"
    ]
    assert canonical_refs == []
    assert "canonical_range_missing" in entity.binding_reasons
    assert "repeated_token_ambiguity" in entity.binding_reasons


def test_genuine_full_duplicate_entity_stays_ambiguous_for_both_occurrences() -> None:
    # Unlike the repeated *interior* token above, here the entire multi-word value repeats
    # verbatim (header + footer), so its boundary anchors are ambiguous too -- there is no
    # stronger evidence to bridge from, and both occurrences must keep their canonical range
    # absent rather than being guessed by textual order.
    raw = (
        "Sicherheitsdienst Wien KG\n"
        "Email: office@example.at\n"
        "Sicherheitsdienst Wien KG\n"
    )
    reading = (
        "Email: office@example.at\n"
        "Sicherheitsdienst Wien KG\n"
        "Sicherheitsdienst Wien KG\n"
    )
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
    graph = _graph_from_raw(raw, reading=reading, reading_map=reading_map)

    first_start = raw.index("Sicherheitsdienst Wien KG")
    second_start = raw.index("Sicherheitsdienst Wien KG", first_start + 1)
    bound = _bind(
        [
            _entity("ORG", "Sicherheitsdienst Wien KG", first_start),
            _entity("ORG", "Sicherheitsdienst Wien KG", second_start),
        ],
        graph,
    )

    assert len(bound) == 2  # never collapsed into one guessed identity
    for entity in bound:
        canonical_refs = [
            ref
            for ref in entity.anchor_refs
            if ref.source_name == "canonical_reading_text" and ref.binding_role == "display_span"
        ]
        assert canonical_refs == []
        assert "canonical_range_missing" in entity.binding_reasons


def test_no_overlap_produces_missing_evidence_only_status() -> None:
    graph = _manual_raw_graph(raw_char_count=20, spans=[(10, 14)])
    [entity] = _bind([_entity("LOCATION", "Wien", 0)], graph)

    assert entity.binding_status == "missing"
    assert entity.identity_basis == "evidence_only"
    assert entity.anchor_set.anchor_ids == []
    assert entity.anchor_refs == []
    assert "anchor_missing" in entity.binding_reasons


def test_ambiguous_anchor_case_is_represented_explicitly() -> None:
    # Two mutually overlapping raw anchors cover the detection: no single anchor set is implied.
    graph = _manual_raw_graph(raw_char_count=20, spans=[(0, 5), (3, 8)])
    [entity] = _bind([_entity("LOCATION", "AbcdeFgh", 0)], graph)

    assert entity.binding_status == "ambiguous"
    assert entity.identity_basis == "evidence_only"
    assert entity.anchor_set.anchor_ids == []  # not a reliable identity
    assert "anchor_ambiguous" in entity.binding_reasons
    # The competing candidate anchors are still surfaced as inferred spans, never silently dropped.
    assert {ref.binding_role for ref in entity.anchor_refs} == {"inferred_span"}
    assert len(entity.anchor_refs) == 2


def test_not_applicable_when_no_anchor_graph() -> None:
    [entity] = _bind([_entity("LOCATION", "Wien", 0)], None)

    assert entity.binding_status == "not_applicable"
    assert entity.identity_basis == "evidence_only"
    assert "text_anchor_graph_missing" in entity.binding_reasons
    assert "evidence_only_identity" in entity.binding_reasons


# --- repeated tokens, merging, separation --------------------------------------------------------


def test_repeated_identical_words_are_not_globally_matched() -> None:
    graph = _graph_from_raw("Wien Wien")
    bound = _bind([_entity("LOCATION", "Wien", 0), _entity("LOCATION", "Wien", 5)], graph)

    assert len(bound) == 2  # two occurrences stay two entities
    first, second = bound
    assert first.anchor_set.anchor_ids != second.anchor_set.anchor_ids
    assert first.entity_id != second.entity_id
    assert first.raw_text_range.start == 0
    assert second.raw_text_range.start == 5


def test_same_anchor_set_and_type_merges_provenance() -> None:
    graph = _graph_from_raw("Wien")
    entities = [
        _entity(
            "LOCATION",
            "Wien",
            0,
            recognizer="R1",
            provenance=PiiEntityProvenance(recognizers=["R1"], candidate_count=1),
        ),
        _entity(
            "LOCATION",
            "Wien",
            0,
            recognizer="R2",
            provenance=PiiEntityProvenance(recognizers=["R2"], candidate_count=1),
        ),
    ]
    bound = _bind(entities, graph)

    assert len(bound) == 1  # merged, not two independent domain entities
    [entity] = bound
    assert entity.provenance is not None
    assert entity.provenance.recognizers == ["R1", "R2"]
    assert entity.provenance.candidate_count == 2
    assert len(entity.source_observations) == 2


def test_different_entity_types_over_same_anchor_set_stay_separate() -> None:
    graph = _graph_from_raw("Wien")
    bound = _bind([_entity("LOCATION", "Wien", 0), _entity("PERSON", "Wien", 0)], graph)

    assert len(bound) == 2
    assert {entity.entity_type for entity in bound} == {"LOCATION", "PERSON"}
    assert bound[0].entity_id != bound[1].entity_id


# --- determinism + stable identity ---------------------------------------------------------------


def test_output_is_deterministic_regardless_of_input_order() -> None:
    graph = _graph_from_raw("Max Mustermann Wien")
    person = _entity("PERSON", "Max Mustermann", 0)
    location = _entity("LOCATION", "Wien", 15)

    forward, _ = bind_pii_entities_to_anchors([person, location], graph, document_id=_DOCUMENT_ID)
    reverse, _ = bind_pii_entities_to_anchors([location, person], graph, document_id=_DOCUMENT_ID)

    assert [entity.entity_id for entity in forward] == [entity.entity_id for entity in reverse]
    assert [entity.model_dump() for entity in forward] == [
        entity.model_dump() for entity in reverse
    ]


def test_exact_entity_id_is_derived_from_anchor_ids() -> None:
    graph = _graph_from_raw("Wien")
    [entity] = _bind([_entity("LOCATION", "Wien", 0)], graph)

    anchor_id = graph.anchors[0].anchor_id
    material = f"{_DOCUMENT_ID}\x00anchor_exact\x00LOCATION\x00{anchor_id}"
    assert entity.entity_id == hashlib.sha256(material.encode()).hexdigest()[:32]


def test_fallback_entity_id_is_evidence_only_when_no_anchors() -> None:
    [entity] = _bind([_entity("LOCATION", "Wien", 0)], None)

    material = f"{_DOCUMENT_ID}\x00LOCATION\x000\x004"
    assert entity.entity_id == hashlib.sha256(material.encode()).hexdigest()[:32]
    assert entity.identity_basis == "evidence_only"


def test_binding_summary_counts_every_status() -> None:
    graph = _graph_from_raw("Wien Graz")
    _bound, summary = bind_pii_entities_to_anchors(
        [_entity("LOCATION", "Wien", 0), _entity("LOCATION", "Graz", 5)],
        graph,
        document_id=_DOCUMENT_ID,
    )
    assert summary.total == 2
    assert summary.total_entities == 2
    assert summary.exact == 2
    assert summary.anchor_bound == 2
    assert summary.anchor_bound_entities == 2
    assert summary.evidence_only == 0
    assert summary.entities_with_raw_range == 2
    assert summary.missing_canonical_range_count == 2
    assert summary.missing_layout_range_count == 2
    assert summary.binding_reason_counts["anchor_exact_match"] == 2
    assert "canonical_range_missing" in summary.warning_codes
    assert "layout_range_missing" in summary.warning_codes


# --- privacy: no raw token text in binding metadata ----------------------------------------------


def test_no_private_token_text_in_binding_metadata() -> None:
    secret = "Geheimname"
    graph = _graph_from_raw(f"{secret} lebt in Wien")
    [entity] = _bind([_entity("PERSON", secret, 0)], graph)

    metadata = json.dumps(
        {
            "anchor_set": entity.anchor_set.model_dump(),
            "anchor_refs": [ref.model_dump() for ref in entity.anchor_refs],
            "binding_reasons": list(entity.binding_reasons),
            "source_observations": [obs.model_dump() for obs in entity.source_observations],
        }
    )
    assert secret not in metadata
    # The value lives only on the entity's dedicated value field (as GET …/pii already exposes it).
    assert entity.value == secret
    assert secret not in json.dumps(graph.model_dump())
