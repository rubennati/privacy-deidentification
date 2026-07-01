"""Unit tests for the dependency-free text-layer quality heuristic."""

from __future__ import annotations

import pytest

from app.services.text_quality import (
    BROKEN_TEXT_LAYER,
    EMPTY_TEXT_LAYER,
    GOOD_TEXT_LAYER,
    LOW_CONFIDENCE_TEXT_LAYER,
    assess_text_quality,
)

_GERMAN_PARAGRAPH = (
    "Sehr geehrte Damen und Herren, hiermit bestätigen wir den Eingang Ihrer Unterlagen "
    "und werden diese Angelegenheit zeitnah sorgfältig bearbeiten sowie Ihnen antworten."
)
_ENGLISH_PARAGRAPH = (
    "The quick brown fox jumps over the lazy dog while the bright sun slowly sets behind "
    "the distant green hills near the quiet winding river this evening."
)
# Words plus well-formed numbers/amounts — number-heavy but perfectly usable.
_INVOICE_TABLE = (
    "Rechnung Position Menge Einzelpreis Gesamtpreis Material 5 120,00 EUR Arbeitsstunden "
    "3 90,50 EUR Anfahrt 1 45,00 EUR Zwischensumme 255,50 EUR Umsatzsteuer 51,10 EUR "
    "Gesamtbetrag 306,60 EUR"
)
# Only digits/symbols, zero real words — the broken/encoded text-layer signature seen in the
# local corpus (S80286-GA / S80917-GA extract as thousands of wordless numeric tokens).
_WORDLESS_NUMERIC_BLOB = (
    "100,00 250,50 12,00 9,99 1.000,00 500,25 42,00 7,50 333,33 88,88 640,10 120,00 15,00 "
    "7,25 9,10 4,50 6,30 8,80 2,20 1,15 3,45 5,55 7,65 9,75 0,05 4,44 6,66 8,88 2,22 1,11"
)
# Many characters, no letters, interior symbols so tokens are neither words nor well-formed
# numbers — the broken/encoded text-layer signature.
_GARBAGE = (
    "1#2 3%4 5@6 7|8 9^0 2&3 4*5 6~7 8<9 0>1 2?3 4=5 6#7 8%9 0@1 2|3 4^5 6&7 8<1 0>2"
)
_CONTROL_HEAVY = ("�" * 40) + " abc def ghi"


def test_empty_string_is_empty_text_layer() -> None:
    assessment = assess_text_quality("")

    assert assessment.status == EMPTY_TEXT_LAYER
    assert assessment.score == 0
    assert assessment.needs_ocr is True
    assert assessment.recommended_text_source == "ocr"


def test_whitespace_only_is_empty_text_layer() -> None:
    assert assess_text_quality("   \n\t  ").status == EMPTY_TEXT_LAYER


def test_normal_german_text_is_good() -> None:
    assessment = assess_text_quality(_GERMAN_PARAGRAPH)

    assert assessment.status == GOOD_TEXT_LAYER
    assert assessment.score >= 80
    assert assessment.needs_ocr is False
    assert assessment.recommended_text_source == "text_layer"


def test_normal_english_text_is_good() -> None:
    assessment = assess_text_quality(_ENGLISH_PARAGRAPH)

    assert assessment.status == GOOD_TEXT_LAYER
    assert assessment.needs_ocr is False


def test_invoice_table_is_usable_not_broken() -> None:
    assessment = assess_text_quality(_INVOICE_TABLE)

    assert assessment.status in (GOOD_TEXT_LAYER, LOW_CONFIDENCE_TEXT_LAYER)
    assert assessment.status != BROKEN_TEXT_LAYER
    assert assessment.needs_ocr is False


def test_wordless_numeric_blob_is_broken() -> None:
    # A page with plenty of characters but *no real words* (only digits/symbols) is the broken
    # text-layer signature. A legitimate number-heavy table keeps its label words (see the invoice
    # test) and stays usable — a high digit ratio alone never triggers OCR.
    assessment = assess_text_quality(_WORDLESS_NUMERIC_BLOB)

    assert assessment.status == BROKEN_TEXT_LAYER
    assert assessment.needs_ocr is True
    assert "few_word_tokens" in assessment.reasons


def test_garbage_low_letter_ratio_is_broken() -> None:
    assessment = assess_text_quality(_GARBAGE)

    assert assessment.status == BROKEN_TEXT_LAYER
    assert assessment.score < 50
    assert assessment.needs_ocr is True
    assert assessment.recommended_text_source == "ocr"
    assert "very_low_letter_ratio" in assessment.reasons
    assert "few_word_tokens" in assessment.reasons


def test_control_and_replacement_heavy_text_is_broken() -> None:
    assessment = assess_text_quality(_CONTROL_HEAVY)

    assert assessment.status == BROKEN_TEXT_LAYER
    assert assessment.needs_ocr is True
    assert "high_control_char_ratio" in assessment.reasons


@pytest.mark.parametrize("text", ["Rechnung Nr. 12345", "Guten Tag zusammen", "Seite 1 von 3"])
def test_short_but_plausible_text_is_low_confidence(text: str) -> None:
    assessment = assess_text_quality(text)

    assert assessment.status == LOW_CONFIDENCE_TEXT_LAYER
    assert assessment.needs_ocr is False
    assert assessment.recommended_text_source == "text_layer"
    assert "sparse_text" in assessment.reasons


@pytest.mark.parametrize(
    ("status_source", "expect_ocr"),
    [
        (assess_text_quality(""), True),
        (assess_text_quality(_GARBAGE), True),
        (assess_text_quality(_WORDLESS_NUMERIC_BLOB), True),
        (assess_text_quality(_GERMAN_PARAGRAPH), False),
        (assess_text_quality(_INVOICE_TABLE), False),
    ],
)
def test_routing_fields_are_internally_consistent(status_source: object, expect_ocr: bool) -> None:
    assessment = status_source
    assert assessment.needs_ocr is expect_ocr  # type: ignore[attr-defined]
    expected_source = "ocr" if expect_ocr else "text_layer"
    assert assessment.recommended_text_source == expected_source  # type: ignore[attr-defined]
