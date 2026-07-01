"""Synthetic, model-free tests for the insurance-at-de Presidio pattern pack."""

from __future__ import annotations

import re

import pytest

from app.services.pii_profiles import DOMAIN_SENSITIVE_TYPES
from app.services.pii_recognizers import (
    INSURANCE_AT_DE_RECOGNIZER_SPECS,
    PatternSpec,
    RecognizerSpec,
)

_SPECS_BY_TYPE = {spec.entity_type: spec for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS}


def _matching_patterns(entity_type: str, value: str) -> list[PatternSpec]:
    return [
        pattern
        for pattern in _SPECS_BY_TYPE[entity_type].patterns
        if re.search(pattern.regex, value)
    ]


@pytest.mark.parametrize(
    ("entity_type", "values"),
    [
        ("UID_AT", ("ATU12345678", "ATU 87654321", "ATU-11223344")),
        ("FN_AT", ("FN 604478 p", "FN: 111556 d", "FN 223344b")),
        (
            "SVNR_AT",
            (
                "SV-Nummer: 1234 120478",
                "SVNR: 2233-170390",
                "Sozialversicherungsnummer 4321 010190",
            ),
        ),
        (
            "TAX_ID_AT",
            (
                "Steuernummer: 12 345 6789",
                "Abgabenkonto: 123-4567-8901",
                "Steuerkonto 123456789",
            ),
        ),
        ("BIC", ("BKAUATWW", "OPSKATWW", "COBADEFFXXX")),
        (
            "PHONE_NUMBER",
            ("+43 664 123 45 67", "+49 89 55512345", "0664 1234567"),
        ),
        ("IBAN_CODE", ("AT12 3456 7890 1234 5678", "DE12 3456 7890 1234 5678 90")),
        (
            "CREDIT_CARD",
            ("Kreditkarte: 4111 1111 1111 1111", "Kartennummer 5500-0000-0000-0004"),
        ),
        ("URL", ("https://portal.example.at/fall", "www.example.de", "service.example.at")),
        (
            "LICENSE_PLATE_AT",
            ("Kennzeichen: W-KM 4892", "Kfz-Kennzeichen W 12345 A", "Kennzeichen M-AB 1234"),
        ),
        (
            "PASSPORT_NUMBER",
            ("Passnummer: P1234567", "Reisepass C4F8H2K9L", "Passport: A87654321"),
        ),
        (
            "ID_CARD_NUMBER",
            (
                "Ausweisnummer: AB1234567",
                "Personalausweis L01X00T47",
                "Identitätskarte: XY7654321",
            ),
        ),
        (
            "POLICY_NUMBER",
            (
                "POL-GEW-2019-003382",
                "POL/KFZ/2026/00871",
                "Polizzennummer: VX-2025-471",
            ),
        ),
        (
            "CLAIM_NUMBER",
            ("SB-2025-00471", "SCH/2026/8871", "Schadennummer: CLM-889921"),
        ),
        (
            "CONTRACT_NUMBER",
            ("VN-3381029", "VER/2025/778", "Vertragsnummer: KT-887721"),
        ),
        (
            "CASE_NUMBER",
            ("AKT-2025-471-W", "AZ/88/2026", "Aktenzeichen: GZ-4711-25"),
        ),
        (
            "FILE_REFERENCE",
            ("REF-2026-0088", "GZ/471/2026", "Ablagereferenz: ABL-77881"),
        ),
        (
            "REPORT_NUMBER",
            ("BER-2026-119", "REP/AT/8871", "Berichtsnummer: RPT-10092"),
        ),
        (
            "ASSESSMENT_NUMBER",
            ("GUT-2025-0917", "GUT/AT/2026/18", "Gutachtennummer: BW-8821"),
        ),
        (
            "INVOICE_NUMBER",
            ("RE/2025/00325", "RG-2026-8871", "Rechnungsnummer: INV-90118"),
        ),
        (
            "OFFER_NUMBER",
            ("ANG/2026/0088", "Angebotsnummer: AN2607003", "Angebotsnummer: OFF-77882"),
        ),
        (
            "CUSTOMER_NUMBER",
            ("KD-10482", "KDN/2026/887", "Kundennummer: CUS-90018"),
        ),
        (
            "PROJECT_ID",
            ("PRJ-2026-441", "PROJ/AT/887", "Projekt-ID: PX-10991"),
        ),
        (
            "TRANSACTION_ID",
            (
                "TXN-20250409-8874421",
                "TX/2026/8891",
                "Transaktions-ID: TRX-11882",
            ),
        ),
        (
            "USER_ID",
            ("USER-AT-8871", "USR/2026/441", "Benutzerkennung: s.kowalski@wb2025"),
        ),
    ],
)
def test_each_entity_type_has_multiple_synthetic_matches(
    entity_type: str, values: tuple[str, ...]
) -> None:
    assert len(values) >= 2
    assert all(_matching_patterns(entity_type, value) for value in values)


@pytest.mark.parametrize(
    ("entity_type", "text"),
    [
        ("PHONE_NUMBER", "Nettobetrag 1.234,56 EUR"),
        ("PHONE_NUMBER", "AT12 3456 7890 1234 5678"),
        ("LICENSE_PLATE_AT", "Position 12-345, Menge 2"),
        ("CASE_NUMBER", "Das Geschäftsjahr ist 2025."),
        ("INVOICE_NUMBER", "Position 10, Artikel 4711, Menge 3"),
        ("TAX_ID_AT", "ATU12345678"),
    ],
)
def test_high_confidence_patterns_reject_known_conflicts(
    entity_type: str, text: str
) -> None:
    high_confidence_matches = [
        pattern
        for pattern in _matching_patterns(entity_type, text)
        if pattern.score >= 0.5
    ]

    assert high_confidence_matches == []


def test_svnr_requires_an_adjacent_label() -> None:
    assert _matching_patterns("SVNR_AT", "1234 120478") == []

    matches = _matching_patterns("SVNR_AT", "SV-Nummer: 1234 120478")
    assert matches
    assert min(pattern.score for pattern in matches) >= 0.5
    assert "sozialversicherungsnummer" in _SPECS_BY_TYPE["SVNR_AT"].context


def test_generic_domain_ids_require_an_adjacent_label() -> None:
    contextual_values = {
        "POLICY_NUMBER": ("VX-2025-471", "Polizzennummer: VX-2025-471"),
        "CLAIM_NUMBER": ("CLM-889921", "Schadennummer: CLM-889921"),
        "INVOICE_NUMBER": ("INV-90118", "Rechnungsnummer: INV-90118"),
        "USER_ID": ("s.kowalski@wb2025", "Benutzerkennung: s.kowalski@wb2025"),
    }

    for entity_type, (bare_value, labelled_value) in contextual_values.items():
        assert _matching_patterns(entity_type, bare_value) == []
        matches = _matching_patterns(entity_type, labelled_value)
        assert matches
        assert min(pattern.score for pattern in matches) >= 0.5
        assert _SPECS_BY_TYPE[entity_type].context


@pytest.mark.parametrize(
    ("entity_type", "text"),
    [
        # An e-mail's domain must not double-count as a bare URL (cross-type overlap).
        ("URL", "max@example.at"),
        ("URL", "Kontakt anna.huber@versicherung.at"),
        # A BIC value carries no licence-plate label, so it must not surface as a plate.
        ("LICENSE_PLATE_AT", "BKAUATWW"),
        # A Firmenbuchnummer must not be read as a case number.
        ("CASE_NUMBER", "FN 604478 p"),
        # A UID is not a tax id (no adjacent tax label, letters present).
        ("TAX_ID_AT", "ATU12345678"),
        # Bare prefix+digits without a label stays out of the offer recognizer.
        ("OFFER_NUMBER", "AN2607003"),
        ("OFFER_NUMBER", "Position an 12 Stück, Menge 2607003"),
        # Unlabelled number runs are not SVNR / tax / generic domain ids.
        ("SVNR_AT", "1234 120478"),
        ("TAX_ID_AT", "123456789"),
        ("POLICY_NUMBER", "2025"),
        ("CUSTOMER_NUMBER", "4711"),
    ],
)
def test_values_without_their_own_context_do_not_leak_across_types(
    entity_type: str, text: str
) -> None:
    high_confidence_matches = [
        pattern
        for pattern in _matching_patterns(entity_type, text)
        if pattern.score >= 0.5
    ]

    assert high_confidence_matches == []


def test_genuine_bare_domain_still_matches_as_url() -> None:
    matches = _matching_patterns("URL", "Besuchen Sie service.example.at heute")

    assert matches
    assert max(pattern.score for pattern in matches) >= 0.5


def test_all_recognizer_names_and_pattern_names_are_unique() -> None:
    recognizer_names = [spec.name for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS]
    pattern_names = [
        pattern.name
        for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS
        for pattern in spec.patterns
    ]

    assert len(recognizer_names) == len(set(recognizer_names))
    assert len(pattern_names) == len(set(pattern_names))


def test_all_domain_recognizers_have_context() -> None:
    domain_specs: list[RecognizerSpec] = [
        spec
        for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS
        if spec.entity_type
        not in {"PHONE_NUMBER", "UID_AT", "FN_AT", "BIC", "IBAN_CODE", "URL"}
    ]

    assert domain_specs
    assert all(spec.context for spec in domain_specs)


def test_every_profile_domain_type_has_a_registered_recognizer() -> None:
    registered_types = {
        spec.entity_type for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS
    }

    assert set(DOMAIN_SENSITIVE_TYPES).issubset(registered_types)
