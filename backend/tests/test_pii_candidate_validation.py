"""Synthetic, model-free tests for Engine-5 candidate validation.

Every candidate text here is a synthetic placeholder (no real personal data). Values mirror the
shapes described in ADR-0013, not any real corpus content.
"""

from __future__ import annotations

import pytest

from app.services.pii_adapters import DetectedEntity
from app.services.pii_candidate_validation import (
    SCORE_DOWN_CAP,
    ValidationDecision,
    validate_candidate,
    validate_candidates,
)


def _decide(
    entity_type: str, text: str, before: str = "", after: str = "", score: float = 0.85
) -> ValidationDecision:
    return validate_candidate(entity_type, text, before, after, score)


# --- PERSON --------------------------------------------------------------------------------


def test_person_function_word_only_is_dropped() -> None:
    decision = _decide("PERSON", "Für")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("FUNCTION_WORD_ONLY",)


def test_person_with_title_context_is_kept() -> None:
    decision = _decide("PERSON", "Max Mustermann", before="Herr ")

    assert decision.verdict == "KEEP"
    assert decision.reasons == ()


def test_person_two_token_capitalized_name_is_kept_without_context() -> None:
    decision = _decide("PERSON", "Max Mustermann")

    assert decision.verdict == "KEEP"


def test_person_single_generic_lowercase_word_is_dropped() -> None:
    decision = _decide("PERSON", "beispiel")

    assert decision.verdict in ("DROP", "SCORE_DOWN")
    assert decision.reasons == ("NER_SINGLE_COMMON_WORD",)


def test_person_numeric_only_is_dropped() -> None:
    decision = _decide("PERSON", "12345")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("NUMERIC_ONLY_FOR_NER",)


def test_person_single_capitalized_word_without_context_is_scored_down() -> None:
    decision = _decide("PERSON", "Musterhaft", score=0.85)

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("MISSING_REQUIRED_CONTEXT",)
    assert decision.adjusted_score <= SCORE_DOWN_CAP


# --- ORGANIZATION ----------------------------------------------------------------------------


def test_organization_generic_document_word_is_dropped() -> None:
    decision = _decide("ORGANIZATION", "Rechnung")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("GENERIC_DOCUMENT_WORD",)


def test_organization_with_company_suffix_is_kept() -> None:
    decision = _decide("ORGANIZATION", "Muster GmbH")

    assert decision.verdict == "KEEP"


def test_organization_generic_word_without_context_is_dropped_or_scored_down() -> None:
    decision = _decide("ORGANIZATION", "Versicherung")

    assert decision.verdict in ("DROP", "SCORE_DOWN")


def test_organization_without_signal_is_scored_down() -> None:
    decision = _decide("ORGANIZATION", "Musterwerk")

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("ORG_WITHOUT_ORG_SIGNAL",)


# --- LOCATION --------------------------------------------------------------------------------


def test_location_generic_word_is_dropped() -> None:
    decision = _decide("LOCATION", "Leistung")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("GENERIC_DOCUMENT_WORD",)


def test_location_with_place_signal_is_kept_or_scored_down() -> None:
    decision = _decide("LOCATION", "Wien")

    assert decision.verdict in ("KEEP", "SCORE_DOWN")


def test_location_numeric_only_is_dropped() -> None:
    decision = _decide("LOCATION", "12345")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("NUMERIC_ONLY_FOR_NER",)


def test_location_without_signal_is_scored_down() -> None:
    decision = _decide("LOCATION", "Musterhausen")

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("LOCATION_WITHOUT_LOCATION_SIGNAL",)


# --- DATE_TIME -------------------------------------------------------------------------------


def test_date_year_only_without_context_is_dropped_or_scored_down() -> None:
    decision = _decide("DATE_TIME", "2025")

    assert decision.verdict in ("DROP", "SCORE_DOWN")


def test_date_birth_date_with_context_is_kept() -> None:
    decision = _decide("DATE_TIME", "12.04.1980", before="Geburtsdatum: ")

    assert decision.verdict == "KEEP"


def test_date_invoice_date_is_kept() -> None:
    decision = _decide("DATE_TIME", "01.02.2025", before="Rechnungsdatum: ")

    assert decision.verdict == "KEEP"


def test_date_shaped_value_is_kept_even_without_context() -> None:
    decision = _decide("DATE_TIME", "01.02.2025")

    assert decision.verdict == "KEEP"


# --- BIC ---------------------------------------------------------------------------------------


def test_bic_without_financial_context_is_scored_down() -> None:
    decision = _decide("BIC", "ABCDEFGH")

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("BIC_WITHOUT_FINANCIAL_CONTEXT",)


def test_bic_with_bank_context_is_kept() -> None:
    decision = _decide("BIC", "ABCDEFGH", before="BIC: ")

    assert decision.verdict == "KEEP"


# --- Moderate domain identifiers ----------------------------------------------------------------


def test_case_number_without_label_context_is_scored_down() -> None:
    decision = _decide("CASE_NUMBER", "AKT-2025-471-W")

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("MISSING_REQUIRED_CONTEXT",)


def test_case_number_with_label_context_is_kept() -> None:
    decision = _decide("CASE_NUMBER", "AKT-2025-471-W", before="Aktenzeichen: ")

    assert decision.verdict == "KEEP"


# --- Light types: validation runs but is a pass-through ------------------------------------------


@pytest.mark.parametrize(
    "entity_type",
    [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "IP_ADDRESS", "URL",
        "UID_AT", "FN_AT", "SVNR_AT", "TAX_ID_AT", "CLAIM_NUMBER", "POLICY_NUMBER",
        "CONTRACT_NUMBER", "INVOICE_NUMBER", "TRANSACTION_ID", "LICENSE_PLATE_AT",
        "PASSPORT_NUMBER", "ID_CARD_NUMBER",
    ],
)
def test_light_types_are_kept_without_context(entity_type: str) -> None:
    decision = _decide(entity_type, "ANYVALUE123")

    assert decision.verdict == "KEEP"
    assert decision.reasons == ()


# --- Privacy: reasons and summaries never carry raw candidate text -------------------------------


def test_reasons_never_contain_the_candidate_text() -> None:
    secret = "VerySecretPersonName"
    decision = _decide("PERSON", secret)

    assert all(secret not in reason for reason in decision.reasons)


def test_validate_candidates_summary_contains_no_raw_values() -> None:
    secret_person = "VerySecretPersonName"
    entities = [
        (DetectedEntity("PERSON", 0, len(secret_person), 0.85, "SpacyRecognizer"), 0, None),
    ]
    page_texts = {None: secret_person}

    validated, summary = validate_candidates(
        entities, page_texts, score_threshold=0.5, enabled=True
    )

    assert validated == []
    assert summary.score_down == 1
    assert summary.dropped == 0
    assert secret_person not in str(summary.score_down_by_reason)
    assert secret_person not in str(summary.dropped_by_reason)


# --- Orchestration: threshold interaction --------------------------------------------------------


def test_score_down_candidate_below_threshold_is_excluded_but_counted() -> None:
    text = "Musterhaft"
    entities = [(DetectedEntity("PERSON", 0, len(text), 0.85, "SpacyRecognizer"), 0, None)]

    validated, summary = validate_candidates(
        entities, {None: text}, score_threshold=0.5, enabled=True
    )

    assert validated == []
    assert summary.kept == 0
    assert summary.score_down == 1
    assert summary.score_down_by_reason == {"MISSING_REQUIRED_CONTEXT": 1}


def test_score_down_candidate_above_lowered_threshold_is_kept() -> None:
    text = "Musterhaft"
    entities = [(DetectedEntity("PERSON", 0, len(text), 0.85, "SpacyRecognizer"), 0, None)]

    validated, summary = validate_candidates(
        entities, {None: text}, score_threshold=0.1, enabled=True
    )

    assert len(validated) == 1
    validated_entity, _, _ = validated[0]
    assert validated_entity.validation_status == "score_down"
    assert validated_entity.original_score == 0.85
    assert validated_entity.entity.score <= SCORE_DOWN_CAP
    assert summary.kept == 1
    assert summary.score_down == 1


def test_disabled_validation_is_a_full_passthrough() -> None:
    text = "Für"
    entities = [(DetectedEntity("PERSON", 0, len(text), 0.85, "SpacyRecognizer"), 0, None)]

    validated, summary = validate_candidates(
        entities, {None: text}, score_threshold=0.5, enabled=False
    )

    assert len(validated) == 1
    assert summary.enabled is False
    assert summary.dropped == 0
    assert summary.score_down == 0


def test_dropped_candidate_is_excluded_from_output() -> None:
    text = "Für"
    entities = [(DetectedEntity("PERSON", 0, len(text), 0.85, "SpacyRecognizer"), 0, None)]

    validated, summary = validate_candidates(
        entities, {None: text}, score_threshold=0.5, enabled=True
    )

    assert validated == []
    assert summary.dropped == 1
    assert summary.dropped_by_reason == {"FUNCTION_WORD_ONLY": 1}
