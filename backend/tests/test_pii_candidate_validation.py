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
from app.services.pii_validation_rules import is_in_header_block


def _decide(
    entity_type: str,
    text: str,
    before: str = "",
    after: str = "",
    score: float = 0.85,
    in_header_block: bool = False,
) -> ValidationDecision:
    return validate_candidate(entity_type, text, before, after, score, in_header_block)


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


def test_person_with_academic_title_suffix_is_kept() -> None:
    decision = _decide("PERSON", "Ruben Beispiel", after=", MSc")

    assert decision.verdict == "KEEP"


def test_person_with_dr_title_prefix_is_kept() -> None:
    decision = _decide("PERSON", "Max Mustermann", before="Dr. ")

    assert decision.verdict == "KEEP"


def test_person_with_mag_title_prefix_is_kept() -> None:
    decision = _decide("PERSON", "Maria Musterfrau", before="Mag. ")

    assert decision.verdict == "KEEP"


def test_person_after_ansprechpartner_label_is_kept() -> None:
    decision = _decide("PERSON", "Max Mustermann", before="Ihr Ansprechpartner ")

    assert decision.verdict == "KEEP"


def test_person_after_geschaeftsfuehrung_label_is_kept() -> None:
    decision = _decide("PERSON", "Maria Musterfrau", before="Geschäftsführung: ", after=", MSc")

    assert decision.verdict == "KEEP"


def test_person_after_kontaktperson_label_is_kept() -> None:
    decision = _decide("PERSON", "Anna Beispiel", before="Kontaktperson: ")

    assert decision.verdict == "KEEP"


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


def test_organization_followed_by_eu_suffix_is_kept() -> None:
    decision = _decide("ORGANIZATION", "Qi Garden", after=" e.U.")

    assert decision.verdict == "KEEP"


def test_organization_followed_by_gmbh_suffix_is_kept() -> None:
    decision = _decide("ORGANIZATION", "Muster", after=" GmbH")

    assert decision.verdict == "KEEP"


def test_organization_followed_by_kg_suffix_is_kept() -> None:
    decision = _decide("ORGANIZATION", "Beispiel", after=" KG")

    assert decision.verdict == "KEEP"


def test_organization_generic_word_far_from_unrelated_company_suffix_is_dropped() -> None:
    # "GmbH" belongs to a *different* organisation later in the sentence — it must not leak onto
    # this unrelated generic-document-word candidate.
    decision = _decide("ORGANIZATION", "Rechnung", after=" von Muster GmbH")

    assert decision.verdict == "DROP"
    assert decision.reasons == ("GENERIC_DOCUMENT_WORD",)


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


def test_location_city_after_postal_code_is_kept() -> None:
    decision = _decide("LOCATION", "Wien", before="1010 ")

    assert decision.verdict == "KEEP"


def test_location_country_austria_is_kept() -> None:
    decision = _decide("LOCATION", "Österreich")

    assert decision.verdict == "KEEP"


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


def test_date_house_number_after_full_street_name_is_suppressed() -> None:
    decision = _decide("DATE_TIME", "18/10/44", before="Obere Beispielstraße ")

    assert decision.verdict in ("DROP", "SCORE_DOWN")
    assert decision.reasons == ("ADDRESS_LINE_NUMERIC_CONTEXT",)


def test_date_house_number_after_musterstrasse_is_suppressed() -> None:
    decision = _decide("DATE_TIME", "12/3/7", before="Musterstraße ")

    assert decision.verdict in ("DROP", "SCORE_DOWN")
    assert decision.reasons == ("ADDRESS_LINE_NUMERIC_CONTEXT",)


def test_date_house_number_after_hauptplatz_is_suppressed() -> None:
    decision = _decide("DATE_TIME", "1/2", before="Hauptplatz ")

    assert decision.verdict in ("DROP", "SCORE_DOWN")
    assert decision.reasons == ("ADDRESS_LINE_NUMERIC_CONTEXT",)


def test_date_real_date_on_same_line_as_street_mention_is_not_address_suppressed() -> None:
    # The dot-formatted date shape does not match the slash-separated house-number pattern, so an
    # unrelated street mention earlier on the same line must not suppress a real date.
    decision = _decide(
        "DATE_TIME", "12.04.1980", before="wohnhaft in der Musterstraße, geboren am "
    )

    assert decision.verdict == "KEEP"


def test_date_postal_code_before_city_is_suppressed() -> None:
    decision = _decide("DATE_TIME", "1010", after=" Wien")

    assert decision.verdict in ("DROP", "SCORE_DOWN")
    assert decision.reasons == ("POSTAL_CODE_CONTEXT",)


def test_date_bare_year_mid_sentence_is_not_postal_code_suppressed() -> None:
    # A bare year with unrelated running text before it on the same line must not be misread as a
    # postal code, even though a capitalised word happens to follow it.
    decision = _decide("DATE_TIME", "2025", before="Geschaeftsjahr ", after=" ist wichtig")

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("DATE_YEAR_ONLY",)


# --- Header / address-block context -----------------------------------------------------------


def test_organization_generic_word_in_header_block_is_scored_down_not_dropped() -> None:
    decision = _decide("ORGANIZATION", "Kunde", in_header_block=True)

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("HEADER_BLOCK_CONTEXT",)


def test_organization_generic_word_outside_header_block_is_dropped() -> None:
    decision = _decide("ORGANIZATION", "Kunde", in_header_block=False)

    assert decision.verdict == "DROP"
    assert decision.reasons == ("GENERIC_DOCUMENT_WORD",)


def test_location_generic_word_in_header_block_is_scored_down_not_dropped() -> None:
    decision = _decide("LOCATION", "Leistung", in_header_block=True)

    assert decision.verdict == "SCORE_DOWN"
    assert decision.reasons == ("HEADER_BLOCK_CONTEXT",)


def test_is_in_header_block_true_near_top_of_multiline_document() -> None:
    text = "Muster GmbH\nMusterstraße 1\n1010 Wien"

    assert is_in_header_block(text, text.index("Wien")) is True


def test_is_in_header_block_false_after_document_title_line() -> None:
    text = "Muster GmbH\nAngebot\nAngebotsnummer AN123456"

    assert is_in_header_block(text, text.index("AN123456")) is False


def test_is_in_header_block_false_beyond_max_lines() -> None:
    text = "\n".join(f"Zeile {i}" for i in range(40)) + "\nKunde"

    assert is_in_header_block(text, text.index("Kunde")) is False


def test_is_in_header_block_false_for_single_line_text() -> None:
    text = "Rechnung von Muster GmbH"

    assert is_in_header_block(text, text.index("Muster")) is False


def test_header_block_end_to_end_keeps_layout_context_candidates() -> None:
    text = (
        "Muster GmbH\n"
        "+43 1 234567\n"
        "office@example.at\n"
        "www.example.at\n"
        "Musterstraße 12/3\n"
        "1010 Wien\n"
        "Österreich\n"
        "Angebot\n"
        "Angebotsnummer AN123456\n"
        "Ihr Ansprechpartner Max Mustermann"
    )

    def span(needle: str) -> tuple[int, int]:
        start = text.index(needle)
        return start, start + len(needle)

    entities = [
        (DetectedEntity("ORGANIZATION", *span("Muster GmbH"), 0.85, "SpacyRecognizer"), 0, None),
        (DetectedEntity("LOCATION", *span("Wien"), 0.85, "SpacyRecognizer"), 0, None),
        (DetectedEntity("LOCATION", *span("Österreich"), 0.85, "SpacyRecognizer"), 0, None),
        (DetectedEntity("DATE_TIME", *span("12/3"), 0.85, "SpacyRecognizer"), 0, None),
        (DetectedEntity("PERSON", *span("Max Mustermann"), 0.85, "SpacyRecognizer"), 0, None),
    ]

    validated, summary = validate_candidates(
        entities, {None: text}, score_threshold=0.5, enabled=True
    )

    kept_types = {
        item[0].entity.entity_type for item in validated if item[0].validation_status == "kept"
    }
    assert {"ORGANIZATION", "LOCATION", "PERSON"} <= kept_types
    date_survivors = [item for item in validated if item[0].entity.entity_type == "DATE_TIME"]
    assert date_survivors == []
    assert summary.score_down_by_reason.get("ADDRESS_LINE_NUMERIC_CONTEXT") == 1


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
