"""Unit tests for OCR/Text L15 noise/token artifact evidence.

All data here is synthetic. These tests exercise the deterministic ``build_ocr_noise_evidence``
builder directly, and its integration into ``build_quality_evidence`` — no private corpus, no OCR
runtime, and no raw document text in any assertion or evidence payload.
"""

from __future__ import annotations

import pytest

from app.schemas import TextContent, TextPageResult
from app.services.ocr_noise import build_ocr_noise_evidence
from app.services.ocr_quality import build_quality_evidence
from app.services.reading_text import ReadingTextResult


def _page(text: str, *, page_number: int = 1) -> TextPageResult:
    return TextPageResult(
        page_number=page_number,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=text,
        text_char_count=len(text),
    )


def _reading(text: str, *flags: str, status: str = "heuristic") -> ReadingTextResult:
    return ReadingTextResult(text=text, status=status, flags=tuple(flags))  # type: ignore[arg-type]


def _summary_item(items: list) -> object:
    return next(item for item in items if item.type == "ocr_noise_summary")


# --- Noise evidence builder: positive detections -------------------------------------------------


def test_repeated_symbol_run_detected() -> None:
    text = "Result !@#$%& code"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.type == "low_information_symbol_run"]
    assert len(matches) == 1
    assert matches[0].reason_code == "symbol_run"
    assert matches[0].details["run_length"] == 6
    assert matches[0].raw_text_range is not None
    span = matches[0].raw_text_range
    assert text[span.start:span.end] == "!@#$%&"


def test_isolated_glyph_like_token_detected() -> None:
    text = "Note ¬ artifact"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "isolated_glyph_like_token"]
    assert len(matches) == 1
    assert matches[0].type == "glyph_artifact"
    assert matches[0].status == "low_confidence"


def test_unsupported_glyph_cluster_detected() -> None:
    text = "Broken � render"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "unsupported_glyph_cluster"]
    assert len(matches) == 1
    assert matches[0].type == "glyph_artifact"
    assert matches[0].status == "confident"


def test_low_information_symbol_cluster_detected() -> None:
    # A long, heterogeneous non-structural run — a bigger garbage block, not a short border/rule.
    junk = "!@#$%^&<>?~\\[]"
    assert len(junk) >= 12
    text = f"Scan output {junk} end"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.type == "non_text_artifact"]
    assert len(matches) == 1
    assert matches[0].reason_code == "symbol_run"
    assert matches[0].details["run_length"] == len(junk)


def test_mixed_alnum_suspicious_token_detected() -> None:
    text = "value a$$$$$ shown"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "high_symbol_ratio"]
    assert len(matches) == 1
    assert matches[0].type == "suspicious_token_shape"


def test_low_letter_ratio_token_detected() -> None:
    text = "code x123456789 field"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "low_letter_ratio"]
    assert len(matches) == 1
    assert matches[0].type == "suspicious_token_shape"


def test_mixed_alnum_confusion_detected() -> None:
    text = "code 1o2O3l4I5 here"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "mixed_alnum_confusion"]
    assert len(matches) == 1
    assert matches[0].type == "character_confusion"
    assert matches[0].status == "partial"


def test_o_zero_confusion_candidate_detected() -> None:
    text = "code 1O0O1 here"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "o_zero_confusion"]
    assert len(matches) == 1
    assert matches[0].type == "character_confusion"
    assert matches[0].status == "low_confidence"


def test_i_l_one_confusion_candidate_detected() -> None:
    text = "code l1l1I here"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "i_l_one_confusion"]
    assert len(matches) == 1
    assert matches[0].type == "character_confusion"


def test_rn_m_confusion_candidate_detected() -> None:
    text = "value 12rn3 unit"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "rn_m_confusion"]
    assert len(matches) == 1
    assert matches[0].type == "character_confusion"


def test_suspicious_split_spacing_candidate_detected() -> None:
    text = "T h i s is broken"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "suspicious_split_spacing"]
    assert len(matches) == 1
    assert matches[0].type == "suspicious_spacing"
    assert matches[0].status == "low_confidence"
    assert matches[0].details["token_count"] == 4


def test_excessive_single_char_tokens_detected() -> None:
    text = "T h i s i s broken"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "excessive_single_char_tokens"]
    assert len(matches) == 1
    assert matches[0].type == "split_word_candidate"
    assert matches[0].status == "partial"
    assert matches[0].details["token_count"] == 6


def test_joined_word_candidate_detected() -> None:
    text = "field invoiceTotal shown"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    matches = [item for item in items if item.reason_code == "suspicious_joined_token"]
    assert len(matches) == 1
    assert matches[0].type == "joined_word_candidate"
    assert matches[0].status == "low_confidence"


# --- Noise evidence builder: false-positive guards ------------------------------------------------


def test_normal_prose_produces_no_noise_evidence() -> None:
    text = (
        "Dies ist ein ganz normaler Vertragstext ohne besondere Auffaelligkeiten. "
        "Er beschreibt die Zusammenarbeit zwischen den Parteien in klarer, gut lesbarer Sprache."
    )
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert len(items) == 1  # only the always-present summary item
    summary = items[0]
    assert summary.type == "ocr_noise_summary"
    assert summary.reason_code == "ocr_noise_summary_clean"
    assert summary.details["total_suspicious_spans"] == 0


def test_invoice_number_is_not_over_flagged() -> None:
    text = "Rechnungsnummer INV-2024-00123 Betrag 199,99 EUR"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_policy_number_is_not_over_flagged() -> None:
    text = "Polizzennummer POL_2024_AB_9981 gueltig"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_legal_reference_is_not_over_flagged() -> None:
    text = "Gemaess Paragraph 2 Absatz 1 dieser Bestimmung gilt Folgendes."
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_legal_section_symbol_reference_is_not_over_flagged() -> None:
    text = "Gemaess § 2 Abs. 1 dieser Bestimmung gilt Folgendes."
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_bullet_list_is_not_over_flagged() -> None:
    text = "\n".join(
        [
            "- Erster Punkt der Liste",
            "- Zweiter Punkt der Liste",
            "- Dritter Punkt der Liste",
        ]
    )
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_table_row_is_not_over_flagged() -> None:
    text = "Pos | Menge | Preis\n1 | 2 | 19,99\n2 | 4 | 39,99"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_ascii_table_border_is_not_over_flagged() -> None:
    text = "+----+------+-------+\n| Pos | Menge | Preis |\n+----+------+-------+"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


@pytest.mark.parametrize(
    ("case", "text"),
    [
        ("iban", "IBAN AT611904300234573201 fuer die Ueberweisung angeben"),
        ("phone", "Telefon +43 660 1234567 ist erreichbar"),
        ("date", "Faelligkeitsdatum 01.02.2024 unbedingt beachten"),
        ("price", "Gesamtbetrag 1.234,56 EUR ist faellig"),
        ("percentage", "Anteil 12,5% des Gesamtbetrags"),
        ("acronym", "Firma GmbH sowie NATO Mitgliedstaaten"),
        ("filename", "Anhang Report_2024_Final.pdf beigefuegt"),
    ],
)
def test_false_positive_guard_categories(case: str, text: str) -> None:
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    summary = _summary_item(items)
    assert summary.reason_code == "ocr_noise_summary_clean", f"{case}: unexpected noise in {text!r}"


# --- Private-corpus-driven regression guards -------------------------------------------------
# These four cases were found by a privacy-safe (shape-signature-only, never raw-text) diagnostic
# pass against the local private corpus; each is a generic, non-corpus-specific document pattern,
# not a hard-coded private value.


def test_hyphenated_compound_word_is_not_confused() -> None:
    # A German compound word split by a non-ASCII dash (not the ASCII "-" the structured-identifier
    # exemption recognizes) must not be treated as letter/digit confusion: it is pure letters, split
    # only by symbols, with zero actual letter<->digit alternation.
    dash = "\u2013"  # en dash (not the ASCII "-" the structured-identifier exemption matches)
    text = f"Bericht Bau{dash}Sach{dash}Verstaendigen{dash}Gutachten heute"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_abbreviation_with_trailing_punctuation_is_not_over_flagged() -> None:
    # A short German abbreviation ("u.s.w." = "und so weiter") immediately followed by sentence
    # punctuation must be judged on its own shape, not the abbreviation plus the trailing comma.
    text = "Angebot enthaelt Material, Arbeitszeit, u.s.w., wie besprochen"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_label_glued_to_blank_field_is_not_over_flagged() -> None:
    # A form label glued (no separating space, a common PDF-extraction artifact) directly to a long
    # intentional blank-line/signature field must not have that filler drag the token's symbol
    # ratio over threshold.
    text = "Datum" + "_" * 40 + " Unterschrift"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


def test_incidental_character_near_structural_run_is_not_over_flagged() -> None:
    # A long intentional underscore blank-field with one incidental adjacent character (e.g. a
    # closing bracket from unrelated nearby layout) must not disqualify the whole run from being
    # recognized as structure.
    text = "Unterschrift " + "_" * 60 + ") weiterer Text"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)])
    assert _summary_item(items).reason_code == "ocr_noise_summary_clean"


# --- Offsets, zones, and determinism ---------------------------------------------------------


def test_multi_page_offsets_are_correct() -> None:
    page1_text = "clean page one"
    page2_text = "junk !@#$%& here"
    pages = [_page(page1_text, page_number=1), _page(page2_text, page_number=2)]
    text = "\n\n".join(page.text for page in pages)
    items = build_ocr_noise_evidence(text=text, pages=pages)
    run_items = [item for item in items if item.type == "low_information_symbol_run"]
    assert len(run_items) == 1
    item = run_items[0]
    assert item.page_number == 2
    span = item.raw_text_range
    assert span is not None
    assert text[span.start:span.end] == "!@#$%&"


def test_page_zone_tag_is_applied_when_available() -> None:
    text = "junk !@#$%& here"
    items = build_ocr_noise_evidence(text=text, pages=[_page(text)], page_zones={1: "header"})
    run_item = next(item for item in items if item.type == "low_information_symbol_run")
    assert run_item.page_zone == "header"


def test_docx_pageless_text_is_scanned() -> None:
    text = "junk !@#$%& here"
    items = build_ocr_noise_evidence(text=text, pages=[])
    run_item = next(item for item in items if item.type == "low_information_symbol_run")
    assert run_item.page_number is None


def test_builder_does_not_mutate_inputs() -> None:
    text = "junk !@#$%& here"
    pages = [_page(text)]
    snapshot = list(pages)
    build_ocr_noise_evidence(text=text, pages=pages)
    assert pages == snapshot
    assert pages[0].text == text


def test_noise_builder_is_deterministic() -> None:
    text = "Result !@#$%& code with 1O0O1 and l1l1I plus T h i s spacing"
    pages = [_page(text)]
    first = build_ocr_noise_evidence(text=text, pages=pages)
    second = build_ocr_noise_evidence(text=text, pages=pages)
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]


def test_no_raw_text_in_noise_metadata() -> None:
    sensitive = "Franz Hubermayr 1O0O1 !@#$%& l1l1I rn7x T h i s"
    items = build_ocr_noise_evidence(text=sensitive, pages=[_page(sensitive)])
    dumped = "".join(item.model_dump_json() for item in items)
    for token in ("Franz", "Hubermayr", "1O0O1", "l1l1I", "!@#$%&", "rn7x"):
        assert token not in dumped


# --- Integration with quality_evidence ---------------------------------------------------------


def test_l15_evidence_appears_in_quality_evidence() -> None:
    text = "Result !@#$%& code"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    noise_types = {item.type for item in evidence.items}
    assert {"low_information_symbol_run", "ocr_noise_summary"} <= noise_types


def test_l15_evidence_appears_in_text_content() -> None:
    text = "Result !@#$%& code"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    content = TextContent(
        document_id="a" * 32,
        input_artifact_id="b" * 32,
        input_audit_artifact_id="c" * 32,
        source="pdf_text_layer",
        text=text,
        text_char_count=len(text),
        pages=[_page(text)],
        reading_text_version="1",
        reading_text=text,
        reading_text_status="heuristic",
        quality_evidence_version="1",
        quality_evidence=evidence,
    )
    assert content.quality_evidence is not None
    noise_types = {item.type for item in content.quality_evidence.items}
    assert {"low_information_symbol_run", "ocr_noise_summary"} <= noise_types


def test_summary_counts_include_noise_evidence() -> None:
    text = "Result !@#$%& code"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    assert evidence.summary.counts_by_type.get("low_information_symbol_run", 0) >= 1
    assert evidence.summary.counts_by_type.get("ocr_noise_summary", 0) == 1
    assert sum(evidence.summary.counts_by_status.values()) == len(evidence.items)


def test_noise_confidence_values_are_bounded() -> None:
    text = "Result !@#$%& code with 1O0O1 and l1l1I plus rn7x and T h i s spacing"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    for item in evidence.items:
        assert item.confidence is None or 0.0 <= item.confidence <= 1.0
    assert evidence.summary.overall_score is None or 0.0 <= evidence.summary.overall_score <= 1.0


def test_noise_reason_codes_are_stable() -> None:
    text = "Result !@#$%& code with 1O0O1 and l1l1I plus rn7x"
    evidence = build_quality_evidence(
        source="pdf_text_layer",
        text=text,
        pages=[_page(text)],
        reading=_reading(text, "geometry_ordering"),
        reading_text_map=[],
        text_geometry=None,
        structured_content=None,
    )
    reasons = {item.reason_code for item in evidence.items}
    assert {
        "symbol_run",
        "o_zero_confusion",
        "i_l_one_confusion",
        "rn_m_confusion",
    } <= reasons
