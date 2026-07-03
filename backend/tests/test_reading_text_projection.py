"""Schema, mapping, and projection regressions for the reading review bridge."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.schemas import PiiEntity, ReadingTextMapSegment, TextContent
from app.services.reading_text_projection import (
    build_reading_text_map,
    project_pii_entities_to_reading_text,
)


def _content(**fields: object) -> dict[str, object]:
    raw = "Anna\nMustermann"
    return {
        "document_id": "d" * 32,
        "input_artifact_id": "a" * 32,
        "input_audit_artifact_id": "b" * 32,
        "source": "docx_text",
        "text": raw,
        "text_char_count": len(raw),
        "reading_text_version": "1",
        "reading_text": "Anna Mustermann",
        "reading_text_status": "heuristic",
        **fields,
    }


def _entity(
    start: int, end: int, text: str, entity_type: str = "PERSON"
) -> PiiEntity:
    return PiiEntity(
        id="e" * 32,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=end,
        score=0.9,
        recognizer="test",
    )


def test_legacy_artifacts_and_empty_versioned_maps_validate() -> None:
    legacy = TextContent.model_validate(
        {key: value for key, value in _content().items() if not key.startswith("reading_")}
    )
    empty = TextContent.model_validate(
        _content(reading_text_map_version="1", reading_text_map=[])
    )
    assert legacy.reading_text_map == []
    assert empty.reading_text_map == []


@pytest.mark.parametrize(
    "segment",
    [
        {"reading_start": -1, "reading_end": 2, "raw_start": 0, "raw_end": 2},
        {"reading_start": 0, "reading_end": 99, "raw_start": 0, "raw_end": 2},
        {"reading_start": 0, "reading_end": 2, "raw_start": 0, "raw_end": 99},
        {"reading_start": 2, "reading_end": 2, "raw_start": 0, "raw_end": 2},
    ],
)
def test_schema_rejects_invalid_map_ranges(segment: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        TextContent.model_validate(
            _content(
                reading_text_map_version="1",
                reading_text_map=[{**segment, "mapping_status": "exact"}],
            )
        )


def test_schema_rejects_map_without_reading_text_and_unknown_status() -> None:
    fields = _content()
    fields.update(reading_text=None, reading_text_version=None, reading_text_status=None)
    with pytest.raises(ValidationError):
        TextContent.model_validate(
            {**fields, "reading_text_map_version": "1", "reading_text_map": []}
        )
    with pytest.raises(ValidationError):
        ReadingTextMapSegment.model_validate(
            {
                "reading_start": 0,
                "reading_end": 2,
                "raw_start": 0,
                "raw_end": 2,
                "mapping_status": "unsafe",
            }
        )


def test_raw_fallback_maps_as_one_exact_range() -> None:
    segments = build_reading_text_map("Anna Mustermann", "Anna Mustermann", [])
    assert len(segments) == 1
    assert segments[0].mapping_status == "exact"
    assert (segments[0].raw_start, segments[0].raw_end) == (0, 15)


def test_whitespace_join_maps_safely_and_synthetic_heading_does_not() -> None:
    segments = build_reading_text_map(
        "Anna\nMustermann\nPos Beschreibung", "LEISTUNGEN\nAnna Mustermann", []
    )
    assert any(segment.mapping_status == "normalized" for segment in segments)
    assert all(segment.reading_start >= len("LEISTUNGEN\n") for segment in segments)


def test_duplicate_ambiguous_fragments_are_not_guessed() -> None:
    assert build_reading_text_map("Anna Anna", "Anna", []) == []


def test_table_row_maps_only_safe_cell_tokens() -> None:
    reading = "1 | Service | 100,00"
    segments = build_reading_text_map("1\tService\t100,00", reading, [])
    mapped_ranges = {(segment.reading_start, segment.reading_end) for segment in segments}
    assert (4, 11) in mapped_ranges
    assert all(
        "|" not in reading[segment.reading_start : segment.reading_end]
        for segment in segments
    )


def test_schema_rejects_overlapping_or_out_of_order_reading_segments() -> None:
    with pytest.raises(ValidationError):
        TextContent.model_validate(
            _content(
                reading_text_map_version="1",
                reading_text_map=[
                    {
                        "reading_start": 5,
                        "reading_end": 10,
                        "raw_start": 5,
                        "raw_end": 10,
                        "mapping_status": "exact",
                    },
                    {
                        "reading_start": 0,
                        "reading_end": 4,
                        "raw_start": 0,
                        "raw_end": 4,
                        "mapping_status": "exact",
                    },
                ],
            )
        )


def test_projection_exact_across_normalized_segments_without_mutating_raw_offsets() -> None:
    segments = build_reading_text_map("Anna\nMustermann", "Anna Mustermann", [])
    original = _entity(0, 15, "Anna\nMustermann")
    projected = project_pii_entities_to_reading_text([original], segments)[0]
    assert projected.projection_status == "exact"
    assert projected.projection_method == "offset_map"
    assert (projected.reading_start_offset, projected.reading_end_offset) == (0, 15)
    assert (projected.start_offset, projected.end_offset, projected.text) == (0, 15, original.text)


def test_partial_and_unmapped_projection_never_get_highlight_offsets() -> None:
    segment = ReadingTextMapSegment(
        reading_start=0,
        reading_end=4,
        raw_start=0,
        raw_end=4,
        mapping_status="exact",
    )
    partial, unmapped = project_pii_entities_to_reading_text(
        [_entity(0, 15, "Anna\nMustermann"), _entity(5, 15, "Mustermann")], [segment]
    )
    assert (partial.projection_status, partial.reading_start_offset) == ("partial", None)
    assert (unmapped.projection_status, unmapped.reading_start_offset) == ("unmapped", None)


def test_partial_mapping_segment_cannot_produce_an_exact_highlight() -> None:
    segment = ReadingTextMapSegment(
        reading_start=0,
        reading_end=4,
        raw_start=0,
        raw_end=4,
        mapping_status="partial",
    )
    projected = project_pii_entities_to_reading_text([_entity(0, 4, "Anna")], [segment])[0]
    assert (projected.projection_status, projected.reading_start_offset) == ("partial", None)


def test_projection_does_not_log_sensitive_text(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        project_pii_entities_to_reading_text([_entity(0, 4, "Anna")], [])
    assert "Anna" not in caplog.text


def test_unmapped_entity_projects_from_one_unique_exact_reading_match() -> None:
    original = _entity(0, 4, "Anna")
    projected = project_pii_entities_to_reading_text(
        [original], [], reading_text="Kontakt: Anna"
    )[0]
    assert (projected.reading_start_offset, projected.reading_end_offset) == (9, 13)
    assert (projected.projection_status, projected.projection_method) == (
        "exact",
        "text_match",
    )
    assert (projected.start_offset, projected.end_offset, projected.text) == (0, 4, "Anna")


def test_whitespace_normalized_entity_projects_from_unique_reading_match() -> None:
    projected = project_pii_entities_to_reading_text(
        [_entity(0, 15, "Anna\nMustermann")],
        [],
        reading_text="Kontakt Anna   Mustermann",
    )[0]
    assert projected.projection_method == "text_match"
    assert (projected.reading_start_offset, projected.reading_end_offset) == (8, 25)


def test_phone_spacing_variant_projects_safely() -> None:
    value = "+43 (1) 234-5678"
    projected = project_pii_entities_to_reading_text(
        [_entity(0, len(value), value, "PHONE_NUMBER")],
        [],
        reading_text="Telefon: +43 1 234 5678",
    )[0]
    assert projected.projection_method == "text_match"
    assert projected.reading_start_offset == 9


def test_iban_spacing_variant_projects_safely() -> None:
    value = "AT61 3200 0000 1234 5678"
    projected = project_pii_entities_to_reading_text(
        [_entity(0, len(value), value, "IBAN_CODE")],
        [],
        reading_text="IBAN: AT613200000012345678",
    )[0]
    assert projected.projection_method == "text_match"
    assert projected.reading_start_offset == 6


@pytest.mark.parametrize(
    "reading_text",
    ["Anna und Anna", "Keine passende Person"],
)
def test_duplicate_or_absent_fallback_value_stays_unmapped(reading_text: str) -> None:
    projected = project_pii_entities_to_reading_text(
        [_entity(0, 4, "Anna")], [], reading_text=reading_text
    )[0]
    assert projected.projection_status == "unmapped"
    assert projected.projection_method is None
    assert projected.reading_start_offset is None


def test_fallback_projection_does_not_log_or_add_text_to_mapping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    segments: list[ReadingTextMapSegment] = []
    with caplog.at_level(logging.DEBUG):
        projected = project_pii_entities_to_reading_text(
            [_entity(0, 9, "SAMPLE-42", "POLICY_NUMBER")],
            segments,
            reading_text="Polizze: SAMPLE 42",
        )[0]
    assert projected.projection_method == "text_match"
    assert segments == []
    assert "SAMPLE-42" not in caplog.text
