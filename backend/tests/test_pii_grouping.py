"""Unit tests for conservative PII entity grouping (PII L11)."""

from __future__ import annotations

from uuid import uuid4

from app.schemas import PiiEntity
from app.services.pii_grouping import group_pii_entities

_CURSOR = {"value": 0}


def _entity(entity_type: str, text: str, *, score: float = 0.9, gap: int = 5) -> PiiEntity:
    """Build one internally-valid, non-overlapping entity at the next free offset."""
    start = _CURSOR["value"]
    end = start + len(text)
    _CURSOR["value"] = end + gap
    return PiiEntity(
        id=uuid4().hex,
        entity_type=entity_type,
        text=text,
        start_offset=start,
        end_offset=end,
        score=score,
        recognizer="TestRecognizer",
    )


def setup_function() -> None:
    _CURSOR["value"] = 0


def test_same_email_groups_together() -> None:
    entities = [
        _entity("EMAIL_ADDRESS", "Max@Example.AT"),
        _entity("EMAIL_ADDRESS", "max@example.at"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 1
    assert groups[0].occurrence_count == 2
    assert set(groups[0].occurrence_ids) == {e.id for e in entities}


def test_same_iban_with_different_spacing_groups_together() -> None:
    entities = [
        _entity("IBAN_CODE", "AT61 1904 3002 3457 3201"),
        _entity("IBAN_CODE", "AT611904300234573201"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 1
    assert groups[0].occurrence_count == 2


def test_same_phone_with_different_formatting_groups_together() -> None:
    entities = [
        _entity("PHONE_NUMBER", "+43 (1) 234-5678"),
        _entity("PHONE_NUMBER", "+43123 45678"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 1
    assert groups[0].occurrence_count == 2


def test_same_id_like_value_with_spacing_differences_groups_together() -> None:
    entities = [
        _entity("POLICY_NUMBER", "POL 2026 00871"),
        _entity("POLICY_NUMBER", "POL202600871"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 1
    assert groups[0].occurrence_count == 2


def test_same_exact_normalized_organization_groups_together_only_when_exact() -> None:
    entities = [
        _entity("ORGANIZATION", "Muster GmbH"),
        _entity("ORGANIZATION", "Muster GmbH"),
        _entity("ORGANIZATION", "Muster  GmbH"),  # extra internal whitespace still normalizes exact
        _entity("ORGANIZATION", "Muster AG"),  # different value: separate group
    ]

    groups = group_pii_entities(entities)

    counts = sorted(group.occurrence_count for group in groups)
    assert counts == [1, 3]


def test_different_entity_types_do_not_group_together() -> None:
    entities = [
        _entity("PERSON", "Wien"),
        _entity("LOCATION", "Wien"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 2
    assert {group.entity_type for group in groups} == {"PERSON", "LOCATION"}


def test_fuzzy_names_do_not_group() -> None:
    entities = [
        _entity("PERSON", "Max Mustermann"),
        _entity("PERSON", "Max Mustermann-Schmidt"),
        _entity("PERSON", "M. Mustermann"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 3


def test_duplicate_occurrences_stay_separate_occurrences_but_same_group() -> None:
    entities = [
        _entity("EMAIL_ADDRESS", "max@example.at"),
        _entity("EMAIL_ADDRESS", "max@example.at"),
        _entity("EMAIL_ADDRESS", "max@example.at"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 1
    assert groups[0].occurrence_count == 3
    assert len(set(groups[0].occurrence_ids)) == 3


def test_ambiguous_values_are_not_incorrectly_merged_across_types() -> None:
    # "1234" could plausibly appear as very different entity types; grouping must never merge
    # across types even when the normalized text happens to collide.
    entities = [
        _entity("USER_ID", "1234"),
        _entity("CASE_NUMBER", "1234"),
    ]

    groups = group_pii_entities(entities)

    assert len(groups) == 2
    assert {group.entity_type for group in groups} == {"USER_ID", "CASE_NUMBER"}


def test_normalized_fingerprint_does_not_expose_raw_sensitive_value() -> None:
    secret = "verysecret.person@example.at"
    entities = [_entity("EMAIL_ADDRESS", secret)]

    groups = group_pii_entities(entities)

    assert secret not in groups[0].normalized_fingerprint
    assert secret.lower() not in groups[0].normalized_fingerprint
    # A hex sha256 digest, not a derivative of the raw text.
    assert len(groups[0].normalized_fingerprint) == 64
    assert all(char in "0123456789abcdef" for char in groups[0].normalized_fingerprint)


def test_entity_group_id_is_deterministic_across_calls() -> None:
    entities = [_entity("EMAIL_ADDRESS", "max@example.at")]

    first = group_pii_entities(entities)
    second = group_pii_entities(entities)

    assert first[0].entity_group_id == second[0].entity_group_id


def test_projection_summary_counts_by_status() -> None:
    exact = _entity("EMAIL_ADDRESS", "max@example.at")
    exact = exact.model_copy(
        update={
            "projection_status": "exact",
            "projection_method": "offset_map",
            "reading_start_offset": 0,
            "reading_end_offset": len(exact.text),
        }
    )
    partial = _entity("EMAIL_ADDRESS", "max@example.at").model_copy(
        update={"projection_status": "partial"}
    )
    unmapped = _entity("EMAIL_ADDRESS", "max@example.at")

    groups = group_pii_entities([exact, partial, unmapped])

    assert len(groups) == 1
    summary = groups[0].projection_summary
    assert (summary.exact_count, summary.partial_count, summary.unmapped_count) == (1, 1, 1)


def test_groups_are_sorted_by_first_occurrence_offset() -> None:
    entities = [
        _entity("LOCATION", "Wien"),
        _entity("PERSON", "Max Mustermann"),
    ]

    groups = group_pii_entities(entities)

    assert [group.entity_type for group in groups] == ["LOCATION", "PERSON"]
