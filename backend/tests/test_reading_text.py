"""Contract and golden tests for OCR/Text L10.5 canonical reading text."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import TextContent, TextPageResult
from app.services.reading_text import (
    ReadingCell,
    ReadingRow,
    build_reading_text,
)

_EXPECTED_QUOTE = """KOSTENVORANSCHLAG
Bausanierung \N{EN DASH} Testdokument (fiktive Daten)

AUFTRAGNEHMER
Sanierungsbau Perchtoldsdorf GmbH
Lindenstraße 42
2380 Perchtoldsdorf, Österreich
Tel: +43 660 1234567
office@sanierungsbau-perchtoldsdorf.at
UID: ATU12345678
FN 987654 t
Raiffeisenbank Perchtoldsdorf
IBAN: AT61 3200 0000 1234 5678
BIC: RLNWATWWXXX

AUFTRAGGEBER
Herr Dipl.-Ing. Franz Hubermayr
Anna Hubermayr (geb. Steininger)
Rosengasse 7/12
2340 Mödling, Österreich
Tel: +43 699 8765432
franz.hubermayr@gmx.at
Geburtsdatum: 14.03.1978
SV-Nummer: 1234 140378

ANGEBOT
Angebot Nr.: KV-2026-0417
Datum: 01.07.2026
Bauvorhaben: Generalsanierung Einfamilienhaus, Rosengasse 7, 2340 Mödling

LEISTUNGEN
Pos. | Leistung | Menge | Einheit | Einzelpreis | Gesamt
1 | Abbrucharbeiten Innenwände | 45 | m² | € 38,00 | € 1.710,00
2 | Fassadendämmung (WDVS, 16 cm) | 180 | m² | € 92,00 | € 16.560,00
3 | Fenstertausch (Kunststoff, 3-fach) | 12 | Stk | € 780,00 | € 9.360,00
4 | Estrich verlegen | 120 | m² | € 34,00 | € 4.080,00
5 | Elektroinstallation erneuern | 1 | pausch. | € 8.900,00 | € 8.900,00
6 | Sanitärinstallation Bad | 1 | pausch. | € 6.400,00 | € 6.400,00
7 | Malerarbeiten innen | 210 | m² | € 12,00 | € 2.520,00

SUMMEN
Zwischensumme netto: € 49.530,00
USt 20 %: € 9.906,00
Gesamtbetrag brutto: € 59.436,00

Zahlungsbedingungen: 30 % Anzahlung bei Auftragserteilung, Restzahlung nach \
Fertigstellung, zahlbar innerhalb 14 Tagen ohne Abzug.

Sachbearbeiter: Bmst. Ing. Wolfgang Reithofer, Tel. +43 664 5551234

Dieses Angebot ist freibleibend und 30 Tage gültig."""


def _page(raw: str) -> TextPageResult:
    return TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=raw,
        text_char_count=len(raw),
    )


def _numbered_page(raw: str, page_number: int) -> TextPageResult:
    page = _page(raw)
    return page.model_copy(update={"page_number": page_number})


def _row(y: float, *cells: tuple[float, str]) -> ReadingRow:
    return ReadingRow(
        page_number=1,
        y0=y,
        y1=y + 0.012,
        cells=tuple(
            ReadingCell(text=text, x0=x, x1=min(0.99, x + max(0.04, len(text) * 0.006)))
            for x, text in cells
        ),
    )


def _quote_rows() -> list[ReadingRow]:
    rows = [
        _row(0.030, (0.07, "KOSTENVORANSCHLAG")),
        _row(0.052, (0.07, "Bausanierung \N{EN DASH} Testdokument (fiktive Daten)")),
        _row(0.100, (0.07, "AUFTRAGNEHMER"), (0.54, "AUFTRAGGEBER")),
    ]
    left = [
        "Sanierungsbau Perchtoldsdorf GmbH",
        "Lindenstraße 42",
        "2380 Perchtoldsdorf, Österreich",
        "Tel: +43 660 1234567",
        "office@sanierungsbau-perchtoldsdorf.at",
        "UID: ATU12345678",
        "FN 987654 t",
        "Raiffeisenbank Perchtoldsdorf",
        "IBAN: AT61 3200 0000 1234 5678",
        "BIC: RLNWATWWXXX",
    ]
    right = [
        "Herr Dipl.-Ing. Franz Hubermayr",
        "Anna Hubermayr (geb. Steininger)",
        "Rosengasse 7/12",
        "2340 Mödling, Österreich",
        "Tel: +43 699 8765432",
        "franz.hubermayr@gmx.at",
        "Geburtsdatum: 14.03.1978",
        "SV-Nummer: 1234 140378",
    ]
    for index, left_text in enumerate(left):
        cells = [(0.07, left_text)]
        if index < len(right):
            cells.append((0.54, right[index]))
        rows.append(_row(0.125 + index * 0.018, *cells))
    rows.extend(
        [
            _row(
                0.330,
                (0.07, "Angebot Nr.: KV-2026-0417"),
                (0.54, "Datum: 01.07.2026"),
            ),
            _row(
                0.352,
                (
                    0.07,
                    "Bauvorhaben: Generalsanierung Einfamilienhaus, Rosengasse 7, 2340 Mödling",
                ),
            ),
        ]
    )
    columns = (0.07, 0.15, 0.55, 0.65, 0.75, 0.88)
    table = [
        ("Pos.", "Leistung", "Menge", "Einheit", "Einzelpreis", "Gesamt"),
        ("1", "Abbrucharbeiten Innenwände", "45", "m²", "€ 38,00", "€ 1.710,00"),
        ("2", "Fassadendämmung (WDVS, 16 cm)", "180", "m²", "€ 92,00", "€ 16.560,00"),
        ("3", "Fenstertausch (Kunststoff, 3-fach)", "12", "Stk", "€ 780,00", "€ 9.360,00"),
        ("4", "Estrich verlegen", "120", "m²", "€ 34,00", "€ 4.080,00"),
        ("5", "Elektroinstallation erneuern", "1", "pausch.", "€ 8.900,00", "€ 8.900,00"),
        ("6", "Sanitärinstallation Bad", "1", "pausch.", "€ 6.400,00", "€ 6.400,00"),
        ("7", "Malerarbeiten innen", "210", "m²", "€ 12,00", "€ 2.520,00"),
    ]
    for index, values in enumerate(table):
        rows.append(_row(0.400 + index * 0.018, *tuple(zip(columns, values, strict=True))))
    rows.extend(
        [
            _row(0.565, (0.54, "Zwischensumme netto:"), (0.88, "€ 49.530,00")),
            _row(0.583, (0.54, "USt 20 %:"), (0.88, "€ 9.906,00")),
            _row(0.601, (0.54, "Gesamtbetrag brutto:"), (0.88, "€ 59.436,00")),
            _row(
                0.640,
                (
                    0.07,
                    "Zahlungsbedingungen: 30 % Anzahlung bei Auftragserteilung, Restzahlung nach",
                ),
            ),
            _row(0.658, (0.07, "Fertigstellung, zahlbar innerhalb 14 Tagen ohne Abzug.")),
            _row(
                0.700,
                (0.07, "Sachbearbeiter: Bmst. Ing. Wolfgang Reithofer, Tel. +43 664 5551234"),
            ),
            _row(0.745, (0.07, "Dieses Angebot ist freibleibend und 30 Tage gültig.")),
        ]
    )
    return rows


def test_quote_fixture_matches_the_canonical_reading_text_exactly() -> None:
    rows = _quote_rows()
    # Synthetic pypdf-like technical extraction: rows are stable but paired columns are interleaved.
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)
    raw_before = raw

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == _EXPECTED_QUOTE
    assert result.status == "heuristic"
    assert "two_column_grouping" in result.flags
    assert "table_row_reconstruction" in result.flags
    assert "document_sections" in result.flags
    assert "conservative_line_joining" in result.flags
    assert raw.startswith("KOSTENVORANSCHLAG\nBausanierung")
    assert "AUFTRAGNEHMER AUFTRAGGEBER" in raw
    assert raw == raw_before


def test_ambiguous_layout_falls_back_to_raw_order_without_rewriting_values() -> None:
    raw = "Alpha 123\nBeta € 45,67"

    result = build_reading_text(raw, [_page(raw)], None, [], None)

    assert result is not None
    assert result.text == raw
    assert result.status == "fallback"
    assert result.flags == ("raw_order_fallback",)


def test_partial_positioned_input_cannot_drop_raw_data() -> None:
    raw = "Alpha 123\nBeta 456"
    partial_rows = [_row(0.1, (0.1, "Alpha 123"))]

    result = build_reading_text(
        raw, [_page(raw)], None, [], None, positioned_rows=partial_rows
    )

    assert result is not None
    assert result.text == raw
    assert result.status == "fallback"


@pytest.mark.parametrize("generic_label", ["Rechnungsnummer", "IBAN", "UID", "Schadennummer"])
def test_flat_list_with_generic_label_is_not_split_into_a_metadata_section(
    generic_label: str,
) -> None:
    """A generic label appearing mid-list must not, on its own, carve the
    remaining rows into a separate metadata block. Without a party heading or an offer-specific
    marker (Angebot/Bauvorhaben/Projekt), a flat, evenly spaced list of one-line facts is not a
    quote/invoice header and must stay a single, consistently rendered block."""
    lines = [
        "Fact one: Alpha",
        "Fact two: Beta",
        "Fact three: Gamma",
        f"{generic_label}: synthetic-value",
        "Fact five: Delta",
    ]
    rows = [_row(0.10 + index * 0.018, (0.07, line)) for index, line in enumerate(lines)]
    raw = "\n".join(lines)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert result.status == "heuristic"
    assert "document_sections" not in result.flags


def test_generic_three_column_table_stays_row_wise_and_keeps_continuation_with_row() -> None:
    rows = [
        _row(0.10, (0.07, "KOSTEN")),
        _row(0.14, (0.07, "Pos."), (0.16, "Beschreibung"), (0.82, "Betrag EUR")),
        _row(0.17, (0.07, "1"), (0.16, "Arbeitsleistung"), (0.84, "10,00")),
        _row(0.19, (0.16, "mit kurzer Fortsetzung")),
        _row(0.22, (0.07, "2"), (0.16, "Material"), (0.84, "20,00")),
        _row(0.26, (0.62, "Gesamtbetrag:"), (0.84, "30,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == """KOSTEN

Pos. | Beschreibung | Betrag EUR
1 | Arbeitsleistung mit kurzer Fortsetzung | 10,00
2 | Material | 20,00

SUMMEN
Gesamtbetrag: 30,00"""
    assert "table_row_reconstruction" in result.flags
    assert "document_sections" in result.flags


def test_aligned_label_value_facts_are_not_misclassified_as_a_table() -> None:
    rows = [
        _row(0.10, (0.07, "Position:"), (0.35, "Technik")),
        _row(0.13, (0.07, "Beschreibung:"), (0.35, "Kurzer Befund")),
        _row(0.16, (0.07, "Betrag:"), (0.35, "30,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert "table_row_reconstruction" not in result.flags
    assert "document_sections" not in result.flags


def test_right_aligned_table_values_follow_cell_order_not_nearest_header() -> None:
    rows = [
        _row(0.10, (0.07, "Position"), (0.40, "Neuwert"), (0.70, "Zeitwert")),
        _row(0.13, (0.07, "Arbeit"), (0.59, "100,00"), (0.86, "80,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Position | Neuwert | Zeitwert\nArbeit | 100,00 | 80,00"


def test_invoice_recipient_and_details_columns_stay_separate() -> None:
    rows = [
        _row(0.10, (0.07, "RECHNUNG AN"), (0.54, "RECHNUNGSDETAILS")),
        _row(0.13, (0.07, "Frau Beispiel"), (0.54, "Rechnungsnr.: INV-1")),
        _row(0.15, (0.07, "Beispielweg 1"), (0.54, "Rechnungsdatum: 01.01.2026")),
        _row(0.21, (0.07, "RECHNUNG")),
        _row(0.24, (0.07, "Betreff: Reparatur")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == """RECHNUNG AN
Frau Beispiel
Beispielweg 1

RECHNUNGSDETAILS
Rechnungsnr.: INV-1
Rechnungsdatum: 01.01.2026

RECHNUNG
Betreff: Reparatur"""
    assert "two_column_grouping" in result.flags


def test_paragraph_joining_does_not_absorb_unrelated_label_value_line() -> None:
    rows = [
        _row(
            0.10,
            (0.07, "Pos."),
            (0.18, "Leistung"),
            (0.55, "Menge"),
            (0.68, "Einheit"),
            (0.82, "Gesamt"),
        ),
        _row(
            0.13,
            (0.07, "1"),
            (0.18, "Arbeit"),
            (0.55, "1"),
            (0.68, "Std"),
            (0.82, "30,00"),
        ),
        _row(0.17, (0.55, "Gesamtbetrag:"), (0.82, "30,00")),
        _row(0.21, (0.07, "Zahlungsbedingungen: zahlbar binnen 14 Tagen")),
        _row(0.24, (0.07, "IBAN: XX00 0000 0000 0000")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Zahlungsbedingungen: zahlbar binnen 14 Tagen\n\nIBAN:" in result.text


def test_repeated_page_headers_and_footers_do_not_enter_middle_of_content() -> None:
    page_lines = [
        [
            "REPORT HEADER",
            "First body",
            "First detail A",
            "First detail B",
            "First detail C",
            "First detail D",
            "Example Company legal footer",
            "Page 1/3",
        ],
        [
            "REPORT HEADER",
            "Second body",
            "Second detail A",
            "__________ Second detail B",
            "Second detail C",
            "Second detail D",
            "Example Company legal footer",
            "Page 2/3",
        ],
        [
            "REPORT HEADER",
            "Third body",
            "Third detail A",
            "Third detail B",
            "Third detail C",
            "Third detail D",
            "Example Company legal footer",
            "Page 3/3",
        ],
    ]
    pages = [_numbered_page("\n".join(lines), index) for index, lines in enumerate(page_lines, 1)]
    rows = [
        _row(0.05, (0.07, line)).__class__(
            page_number=page_number,
            y0=0.05 + line_index * 0.10,
            y1=0.062 + line_index * 0.10,
            cells=_row(0.05, (0.07, line)).cells,
        )
        for page_number, lines in enumerate(page_lines, 1)
        for line_index, line in enumerate(lines)
    ]
    raw = "\n\n".join(page.text for page in pages)

    result = build_reading_text(raw, pages, None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text.count("REPORT HEADER") == 1
    assert result.text.count("Example Company legal footer") == 1
    assert "Page 1/3" not in result.text
    assert "Page 2/3" not in result.text
    assert "Page 3/3" not in result.text
    assert "__________" not in result.text
    assert result.text.index("REPORT HEADER") < result.text.index("First body")
    assert result.text.index("Example Company legal footer") > result.text.index("Third body")
    assert "repeated_page_margins_filtered" in result.flags


def _content(**fields: object) -> dict[str, object]:
    text = "Raw text"
    return {
        "document_id": "d" * 32,
        "input_artifact_id": "a" * 32,
        "input_audit_artifact_id": "b" * 32,
        "source": "docx_text",
        "text": text,
        "text_char_count": len(text),
        **fields,
    }


def test_legacy_artifact_without_reading_text_fields_loads() -> None:
    content = TextContent.model_validate(_content())

    assert content.reading_text is None
    assert content.reading_text_version is None
    assert content.reading_text_status is None
    assert content.reading_text_flags == []


@pytest.mark.parametrize(
    "fields",
    [
        {"reading_text": "Useful", "reading_text_status": "heuristic"},
        {"reading_text_version": "1", "reading_text_status": "heuristic"},
        {"reading_text_version": "1", "reading_text": "Useful"},
        {"reading_text_flags": ["raw_order_fallback"]},
        {
            "reading_text_version": "1",
            "reading_text": "   ",
            "reading_text_status": "fallback",
        },
    ],
)
def test_reading_text_contract_rejects_inconsistent_fields(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TextContent.model_validate(_content(**fields))
