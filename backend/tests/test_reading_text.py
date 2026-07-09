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


def test_two_column_agb_prose_reads_left_column_then_right_column() -> None:
    rows = [
        _row(
            0.10,
            (0.07, "1. Allgemeines"),
            (0.54, "2. Datenschutz"),
        ),
        _row(
            0.12,
            (0.07, "Diese Bedingungen gelten fuer alle Leistungen dieses Vertrages und"),
            (0.54, "Personenbezogene Daten werden nur fuer die Abwicklung dieses"),
        ),
        _row(
            0.138,
            (0.07, "werden Bestandteil jeder Bestellung."),
            (0.54, "Auftrags verarbeitet."),
        ),
        _row(
            0.17,
            (0.07, "Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen."),
            (0.54, "Weitere Hinweise werden dem Kunden in Textform bereitgestellt."),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "1. Allgemeines\n"
        "Diese Bedingungen gelten fuer alle Leistungen dieses Vertrages und "
        "werden Bestandteil jeder Bestellung.\n"
        "Der Auftragnehmer informiert den Kunden rechtzeitig ueber Aenderungen.\n\n"
        "2. Datenschutz\n"
        "Personenbezogene Daten werden nur fuer die Abwicklung dieses Auftrags verarbeitet.\n"
        "Weitere Hinweise werden dem Kunden in Textform bereitgestellt."
    )
    assert "multi_column_reconstruction" in result.flags


def test_short_two_column_table_is_not_mistaken_for_prose_columns() -> None:
    rows = [
        _row(0.10, (0.07, "Name"), (0.54, "Betrag")),
        _row(0.13, (0.07, "Alpha"), (0.54, "10,00")),
        _row(0.16, (0.07, "Beta"), (0.54, "20,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert "multi_column_reconstruction" not in result.flags


def test_low_confidence_column_layout_falls_back_to_raw_order() -> None:
    rows = [
        _row(0.10, (0.07, "Linke kurze Notiz"), (0.54, "Rechte kurze Notiz")),
        _row(0.13, (0.07, "Nur eine Folgezeile")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert "multi_column_reconstruction" not in result.flags


def test_label_value_form_columns_are_not_split_into_labels_then_values() -> None:
    rows = [
        _row(0.10, (0.07, "Geburtsdatum:"), (0.37, "22.11.1985")),
        _row(0.13, (0.07, "Wohnadresse:"), (0.37, "Beispielstrasse 12/4, 1020 Wien")),
        _row(0.16, (0.07, "Mobilnummer:"), (0.37, "+43 676 444 55 66")),
        _row(0.19, (0.07, "E-Mail:"), (0.37, "person@example.test")),
        _row(0.22, (0.07, "Steuernummer (privat):"), (0.37, "12 345/67890")),
        _row(0.25, (0.07, "IP-Adresse (letzter Login):"), (0.37, "92.103.211.17")),
        _row(0.28, (0.07, "Benutzerkennung Portal:"), (0.37, "person.portal")),
        _row(
            0.34,
            (
                0.10,
                "Muster GmbH | FN 123456a | UID ATU12345678 | IBAN AT00 0000 0000 0000 0000",
            ),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "\n".join(" ".join(cell.text for cell in row.cells) for row in rows[:7])
        + "\n\n"
        + rows[7].cells[0].text
    )
    assert "Geburtsdatum: 22.11.1985" in result.text
    assert "Benutzerkennung Portal: person.portal" in result.text
    assert "multi_column_reconstruction" not in result.flags


def test_fused_table_header_uses_following_row_positions_without_fake_columns() -> None:
    rows = [
        _row(0.10, (0.07, "Pos. Beschreibung Betrag EUR")),
        _row(0.13, (0.07, "1"), (0.18, "Arbeitsleistung"), (0.82, "10,00")),
        _row(0.16, (0.07, "2"), (0.18, "Material"), (0.82, "20,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Pos. | Beschreibung | Betrag EUR\n"
        "1 | Arbeitsleistung | 10,00\n"
        "2 | Material | 20,00"
    )
    assert "dense_table_reconstruction" in result.flags
    assert "multi_column_reconstruction" not in result.flags


def test_generic_table_with_aligned_columns_and_no_known_header_is_reconstructed_row_wise() -> None:
    """OCR/Text L13: a table with no recognized header vocabulary is still detected from repeated
    row geometry alone — 3+ aligned columns repeated across 3+ rows."""
    rows = [
        _row(0.10, (0.07, "Datum"), (0.35, "Ort"), (0.65, "Ansprechpartner")),
        _row(0.13, (0.07, "01.01.2026"), (0.35, "Wien"), (0.65, "Frau Muster")),
        _row(0.16, (0.07, "02.01.2026"), (0.35, "Graz"), (0.65, "Herr Beispiel")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Datum | Ort | Ansprechpartner\n"
        "01.01.2026 | Wien | Frau Muster\n"
        "02.01.2026 | Graz | Herr Beispiel"
    )
    assert "generic_table_reconstruction" in result.flags
    assert "table_row_reconstruction" in result.flags


def test_generic_table_multiline_description_stays_attached_to_its_row() -> None:
    rows = [
        _row(0.10, (0.07, "Datum"), (0.35, "Beschreibung"), (0.75, "Betrag")),
        _row(0.13, (0.07, "01.01.2026"), (0.35, "Erste Position mit"), (0.75, "10,00")),
        _row(0.148, (0.35, "kurzer Fortsetzung")),
        _row(0.16, (0.07, "02.01.2026"), (0.35, "Zweite Position"), (0.75, "20,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Datum | Beschreibung | Betrag\n"
        "01.01.2026 | Erste Position mit kurzer Fortsetzung | 10,00\n"
        "02.01.2026 | Zweite Position | 20,00"
    )
    assert "generic_table_reconstruction" in result.flags


def test_generic_table_totals_row_stays_grouped_as_summen_block() -> None:
    rows = [
        _row(0.10, (0.07, "Datum"), (0.35, "Ort"), (0.65, "Betrag")),
        _row(0.13, (0.07, "01.01.2026"), (0.35, "Wien"), (0.65, "10,00")),
        _row(0.16, (0.07, "02.01.2026"), (0.35, "Graz"), (0.65, "20,00")),
        _row(0.20, (0.35, "Gesamtbetrag:"), (0.65, "30,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Datum | Ort | Betrag\n"
        "01.01.2026 | Wien | 10,00\n"
        "02.01.2026 | Graz | 20,00\n\n"
        "SUMMEN\n"
        "Gesamtbetrag: 30,00"
    )


def test_partially_fused_two_cell_table_header_uses_following_row_positions() -> None:
    """OCR/Text L13: a header fused into two cells (not just one) still reconstructs when the
    following rows provide safe column-position evidence for every recognized marker."""
    rows = [
        _row(0.10, (0.07, "Pos. Beschreibung"), (0.55, "Menge Gesamt")),
        _row(0.13, (0.07, "1"), (0.18, "Arbeit"), (0.55, "2"), (0.70, "20,00")),
        _row(0.16, (0.07, "2"), (0.18, "Material"), (0.55, "1"), (0.70, "10,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Pos. | Beschreibung | Menge | Gesamt\n"
        "1 | Arbeit | 2 | 20,00\n"
        "2 | Material | 1 | 10,00"
    )
    assert "dense_table_reconstruction" in result.flags


def test_short_geometric_run_below_minimum_rows_falls_back_safely() -> None:
    """Must-not-trigger: only 2 rows of aligned columns is below the L13 generic-table row
    minimum, so low confidence keeps the existing safe row order instead of guessing."""
    rows = [
        _row(0.10, (0.07, "A"), (0.35, "B"), (0.65, "C")),
        _row(0.13, (0.07, "1"), (0.35, "2"), (0.65, "3")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert "generic_table_reconstruction" not in result.flags


def test_three_column_prose_is_not_misclassified_as_a_generic_table() -> None:
    """Must-not-trigger: three columns of genuine prose keep taking the multi-column reading path
    instead of being swept into the new geometric table detector."""
    rows = [
        _row(
            0.10,
            (0.07, "1. Allgemeines regelt die grundlegenden Bedingungen dieses Vertrages"),
            (0.38, "2. Datenschutz behandelt den Umgang mit personenbezogenen Daten"),
            (0.69, "3. Haftung beschreibt die Grenzen der vertraglichen Verantwortung"),
        ),
        _row(
            0.12,
            (0.07, "und gilt fuer alle Leistungen die im Rahmen dieses Vertrages erbracht werden."),
            (
                0.38,
                "Personenbezogene Daten werden ausschliesslich zur Vertragsabwicklung verarbeitet.",
            ),
            (0.69, "Der Auftragnehmer haftet nur bei grober Fahrlaessigkeit oder Vorsatz."),
        ),
        _row(
            0.14,
            (0.07, "Aenderungen bedürfen der Schriftform und der Zustimmung beider Parteien."),
            (0.38, "Weitere Hinweise erhalten Sie in der separaten Datenschutzerklaerung."),
            (0.69, "Ausgenommen hiervon sind gesetzlich zwingende Haftungstatbestaende."),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "multi_column_reconstruction" in result.flags
    assert "generic_table_reconstruction" not in result.flags


def test_adjacent_label_value_pairing_joins_a_multiline_value() -> None:
    """OCR/Text L13: a label alone on its row pairs with a value that itself wraps across
    multiple following rows in the same column (e.g. a multiline address)."""
    rows = [
        _row(0.10, (0.07, "Anschrift:")),
        _row(0.118, (0.30, "Musterstraße 1")),
        _row(0.136, (0.30, "1010 Wien")),
        _row(0.16, (0.07, "Telefon:")),
        _row(0.178, (0.30, "+43 1 2345678")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == ("Anschrift: Musterstraße 1 1010 Wien\nTelefon: +43 1 2345678")
    assert "multiline_value_pairing" in result.flags


def test_adjacent_label_value_continuation_stops_before_the_next_label() -> None:
    """Must-not-trigger: a following row that is itself a new standalone label must not be
    absorbed as a value continuation."""
    rows = [
        _row(0.10, (0.07, "Kundennummer:")),
        _row(0.118, (0.25, "KD-9981")),
        _row(0.136, (0.07, "Aktenzeichen:")),
        _row(0.154, (0.25, "AZ-4471")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == ("Kundennummer: KD-9981\nAktenzeichen: AZ-4471")
    assert "multiline_value_pairing" not in result.flags


def test_adjacent_label_value_continuation_stops_before_an_inline_label_value_line() -> None:
    """Regression for a real corpus bug: an unrelated "Label: value" fact immediately following a
    paired value, in the same column, was being absorbed as a continuation of that value instead
    of staying its own line."""
    rows = [
        _row(0.10, (0.07, "Kundennummer:")),
        _row(0.118, (0.07, "KD-9981")),
        _row(0.136, (0.07, "Hinweis: Bitte Referenznummer angeben")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Kundennummer: KD-9981\nHinweis: Bitte Referenznummer angeben"
    assert "multiline_value_pairing" not in result.flags


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


def test_adjacent_label_value_pair_joins_only_when_geometry_is_safe() -> None:
    rows = [
        _row(0.10, (0.07, "Kundennummer:")),
        _row(0.118, (0.25, "KD-9981")),
        _row(0.16, (0.07, "Hinweis:")),
        _row(0.178, (0.07, "Dieser lange Satz bleibt als eigener Hinweistext erhalten.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Kundennummer: KD-9981" in result.text
    assert "Hinweis:\nDieser lange Satz bleibt" in result.text
    assert "label_value_pairing" in result.flags


def test_column_paired_label_value_form_renders_one_pair_per_line() -> None:
    rows = [
        _row(
            0.10,
            (0.07, "Datum:"),
            (0.22, "01.01.2026"),
            (0.54, "Aktenzeichen:"),
            (0.74, "AZ-42"),
        ),
    ]
    raw = "Datum: 01.01.2026 Aktenzeichen: AZ-42"

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Datum: 01.01.2026\nAktenzeichen: AZ-42"
    assert "label_value_pairing" in result.flags


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


def test_close_prose_rows_after_table_join_but_separate_paragraph_gap_remains() -> None:
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
        _row(0.17, (0.62, "Gesamtbetrag:"), (0.82, "30,00")),
        _row(0.21, (0.07, "ZAHLUNGSHINWEIS")),
        _row(
            0.25,
            (
                0.07,
                "Bitte begleichen Sie den offenen Betrag innerhalb der vereinbarten Frist auf das",
            ),
        ),
        _row(0.267, (0.07, "im Vertrag genannte Konto.")),
        _row(
            0.31,
            (0.07, "Alternativ kann die Zahlung nach vorheriger Abstimmung vor Ort erfolgen."),
        ),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    expected = (
        "Bitte begleichen Sie den offenen Betrag innerhalb der vereinbarten Frist auf das "
        "im Vertrag genannte Konto.\n\n"
        "Alternativ kann die Zahlung nach vorheriger Abstimmung vor Ort erfolgen."
    )
    assert expected in result.text


def test_close_post_table_label_value_rows_are_not_joined_as_prose() -> None:
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
        _row(0.17, (0.62, "Gesamtbetrag:"), (0.82, "30,00")),
        _row(0.21, (0.07, "Kundennummer: SAMPLE-1")),
        _row(0.227, (0.07, "IBAN: XX00 0000 0000 0000")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Kundennummer: SAMPLE-1\n\nIBAN: XX00 0000 0000 0000" in result.text


def test_positioned_fragments_glue_trailing_punctuation_without_a_space() -> None:
    rows = [
        _row(
            0.10,
            (0.07, "Ein Fließtext der lang genug ist um als Absatz erkannt zu werden"),
            (0.62, "."),
        ),
    ]
    raw = "Ein Fließtext der lang genug ist um als Absatz erkannt zu werden."

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw


def test_positioned_fragment_starting_with_punctuation_keeps_the_following_word_gap() -> None:
    rows = [
        _row(
            0.10,
            (0.07, "Firma unter example.com"),
            (0.50, ". Die Gesellschaft ist im Handelsregister eingetragen und aktiv"),
        ),
    ]
    raw = "Firma unter example.com. Die Gesellschaft ist im Handelsregister eingetragen und aktiv"

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw


def test_bullet_marker_fragment_becomes_a_markdown_list_item() -> None:
    rows = [
        _row(0.10, (0.07, "•"), (0.10, "Kurzer Listeneintrag ohne Fortsetzung")),
    ]
    raw = "• Kurzer Listeneintrag ohne Fortsetzung"

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "- Kurzer Listeneintrag ohne Fortsetzung"


def test_bullet_item_wrap_continuation_joins_until_sentence_end() -> None:
    rows = [
        _row(
            0.10, (0.07, "•"), (0.10, "Erste Position mit einer sehr langen Beschreibung die über")
        ),
        _row(0.118, (0.10, "zwei Zeilen umgebrochen wird.")),
        _row(0.140, (0.07, "EUR 123,45")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "- Erste Position mit einer sehr langen Beschreibung die über zwei Zeilen "
        "umgebrochen wird.\nEUR 123,45"
    )


def test_finished_bullet_does_not_absorb_the_next_unrelated_line() -> None:
    """Regression for a real corpus bug: a completed bullet item must not swallow an unrelated
    short line that merely sits close beneath it (e.g. a restated total amount)."""
    rows = [
        _row(0.10, (0.07, "•"), (0.10, "Position mit vollständigem Satz und klarem Ende.")),
        _row(0.118, (0.07, "EUR 99,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "- Position mit vollständigem Satz und klarem Ende.\nEUR 99,00"


def test_two_bullet_items_in_a_row_stay_separate() -> None:
    rows = [
        _row(0.10, (0.07, "•"), (0.10, "Erste Position ohne Punkt am Ende")),
        _row(0.118, (0.07, "•"), (0.10, "Zweite Position ohne Punkt am Ende")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "- Erste Position ohne Punkt am Ende\n- Zweite Position ohne Punkt am Ende"
    )


def test_long_prose_line_in_a_flat_block_joins_its_wrap_but_stops_at_sentence_end() -> None:
    rows = [
        _row(0.10, (0.07, "Dies ist ein langer Fließtextsatz der über zwei Zeilen umgebrochen")),
        _row(0.118, (0.07, "wird und dort endet.")),
        _row(0.140, (0.07, "Kurzer Folgesatz.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Dies ist ein langer Fließtextsatz der über zwei Zeilen umgebrochen wird und dort endet."
        "\nKurzer Folgesatz."
    )


def test_long_prose_line_wrap_repairs_a_line_break_hyphen() -> None:
    rows = [
        _row(0.10, (0.07, "Das Dach dieses langen Beispielsatzes ist als Flachdach ausge-")),
        _row(0.118, (0.07, "führt und stellt die Fortsetzung dar.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert (
        "Das Dach dieses langen Beispielsatzes ist als Flachdach ausgeführt und stellt die "
        "Fortsetzung dar."
    ) in result.text
    assert "ausge- führt" not in result.text
    assert "ausge-führt" not in result.text


def test_long_prose_line_wrap_does_not_dehyphenate_before_a_non_letter_continuation() -> None:
    """The hyphen repair must only fire for a genuine word-wrap (next line starts with a letter),
    never in front of a following number/code, where the hyphen is real content."""
    rows = [
        _row(
            0.10,
            (0.07, "Dies ist wirklich ein sehr langer Beispielsatz mit einer Positionsnummer-"),
        ),
        _row(0.118, (0.07, "12345 wird im naechsten Abschnitt erlaeutert und fortgesetzt.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Positionsnummer- 12345" in result.text


def test_long_prose_line_in_a_flat_block_does_not_absorb_a_label_value_line() -> None:
    rows = [
        _row(0.10, (0.07, "Dies ist ein sehr langer einleitender Satz ohne Punkt am Zeilenende")),
        _row(0.118, (0.07, "Kundennummer: SAMPLE-1")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Dies ist ein sehr langer einleitender Satz ohne Punkt am Zeilenende"
        "\nKundennummer: SAMPLE-1"
    )


def test_greeting_opener_becomes_its_own_paragraph_even_at_tight_line_spacing() -> None:
    """A generic German salutation opener ("Guten Tag," / "Sehr geehrte...") marks a reliable
    letter paragraph boundary on its own, independent of vertical spacing. Some correspondence
    documents have no reliable geometric gap between blocks, so this line-based signal is needed
    to separate the greeting from what precedes and follows it."""
    rows = [
        _row(0.10, (0.07, "Testobjekt: Musterstraße 1, 1010 Wien")),
        _row(0.118, (0.07, "Guten Tag,")),
        _row(0.136, (0.07, "das ist ein Testsatz zur Erläuterung.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Testobjekt: Musterstraße 1, 1010 Wien"
        "\n\nGuten Tag,"
        "\n\ndas ist ein Testsatz zur Erläuterung."
    )


def test_closing_sign_off_becomes_its_own_paragraph_even_at_tight_line_spacing() -> None:
    rows = [
        _row(0.10, (0.07, "Vielen Dank für Ihr Verständnis.")),
        _row(0.118, (0.07, "Freundliche Grüße")),
        _row(0.136, (0.07, "Das Team")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Vielen Dank für Ihr Verständnis."
        "\n\nFreundliche Grüße"
        "\n\nDas Team"
    )


def test_greeting_phrase_mid_sentence_does_not_split_the_paragraph() -> None:
    """The salutation regex is anchored to the start of the line: a line that merely mentions the
    phrase mid-sentence (not as its own greeting) must not be treated as a paragraph boundary."""
    rows = [
        _row(0.10, (0.07, "Diese sehr geehrte Persönlichkeit war beim Termin anwesend und hat")),
        _row(0.118, (0.07, "den Bericht unterschrieben.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Diese sehr geehrte Persönlichkeit war beim Termin anwesend und hat den Bericht "
        "unterschrieben."
    )


def test_closing_word_mid_sentence_does_not_split_the_paragraph() -> None:
    rows = [
        _row(0.10, (0.07, "Grüße aus der Bauleitung übermitteln wir mit diesem Schreiben")),
        _row(0.118, (0.07, "an alle Beteiligten.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Grüße aus der Bauleitung übermitteln wir mit diesem Schreiben an alle Beteiligten."
    )


def test_separator_rule_cell_does_not_block_table_header_detection() -> None:
    """Regression for a real corpus bug: a long underscore rule sharing a header's row (a common
    PDF pattern: a divider drawn just above a table) was being read as the header's first cell,
    which both hid the real leader text from the header-marker check and, before that check even
    ran, inflated the rendered line past the long-prose threshold and swallowed following rows."""
    long_rule = "_" * 40
    rows = [
        _row(
            0.10,
            (0.02, long_rule),
            (0.07, "Pos."),
            (0.16, "Beschreibung"),
            (0.82, "Betrag EUR"),
        ),
        _row(0.13, (0.07, "1"), (0.16, "Arbeitsleistung"), (0.84, "10,00")),
        _row(0.16, (0.07, "2"), (0.16, "Material"), (0.84, "20,00")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Pos. | Beschreibung | Betrag EUR" in result.text
    assert "1 | Arbeitsleistung | 10,00" in result.text
    assert "2 | Material | 20,00" in result.text
    assert long_rule not in result.text
    assert "table_row_reconstruction" in result.flags


def test_short_dash_run_is_not_mistaken_for_a_separator_rule() -> None:
    """Only a long (8+) separator run is stripped; a short dash sequence is ordinary content and
    must survive unchanged, e.g. as part of a code or reference number cell."""
    rows = [_row(0.10, (0.07, "Referenz:"), (0.30, "-------"))]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == "Referenz: -------"


def test_data_heavy_row_is_not_absorbed_as_a_prose_continuation() -> None:
    """Regression for a real corpus bug: a flattened cost/line-item row (several decimal amounts,
    no header the table detector could latch onto) that happens to be 60+ characters was
    misclassified as a wrapped prose sentence, so the continuation loop swallowed every following
    row in the same dense block into one unreadable line."""
    rows = [
        _row(
            0.10,
            (0.07, "Moebel vertragen, De- od. Neumontage von Moebeln 6,00 Std 67,50 405,00"),
        ),
        _row(0.118, (0.07, "Verputz abschlagen 2,00 m2 25,33 50,66")),
        _row(0.136, (0.07, "Gesamtbetrag 1.712,38")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Moebel vertragen, De- od. Neumontage von Moebeln 6,00 Std 67,50 405,00"
        "\nVerputz abschlagen 2,00 m2 25,33 50,66"
        "\nGesamtbetrag 1.712,38"
    )


def test_attachment_filename_list_is_not_absorbed_into_a_single_prose_line() -> None:
    """Regression for a real corpus bug: a long lead-in line (60+ characters, e.g. a heading fused
    with a repeated page header) was absorbing every following attachment/photo caption line as a
    prose wrap continuation, because filenames never end in sentence punctuation. The whole
    attachment list collapsed into one unreadable line instead of staying one entry per line."""
    rows = [
        _row(
            0.10,
            (0.07, "Beispiel Firma Musterstraße 1 Anhänge mit folgenden Bilddateien im Ordner"),
        ),
        _row(0.118, (0.07, "Bild Uebersicht / 20250708_090948.jpg")),
        _row(0.136, (0.07, "Bild Kueche / 20250708_091058.jpg")),
        _row(0.154, (0.07, "Bild Bad / 20250708_091111.jpg")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Beispiel Firma Musterstraße 1 Anhänge mit folgenden Bilddateien im Ordner"
        "\nBild Uebersicht / 20250708_090948.jpg"
        "\nBild Kueche / 20250708_091058.jpg"
        "\nBild Bad / 20250708_091111.jpg"
    )


def test_long_prose_line_mentioning_a_web_domain_still_joins_its_wrap() -> None:
    """Must-not-trigger for the filename guard: a line naming a website or email domain (a dot
    followed by letters that is not a tracked attachment file extension) is ordinary prose and
    must still merge with its wrapped continuation."""
    rows = [
        _row(
            0.10,
            (0.07, "Weitere Informationen erhalten Sie auf unserer Webseite www.beispielfirma.at"),
        ),
        _row(0.118, (0.07, "oder unter der angegebenen Telefonnummer.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Weitere Informationen erhalten Sie auf unserer Webseite www.beispielfirma.at "
        "oder unter der angegebenen Telefonnummer."
    )


def test_long_prose_line_with_a_single_amount_still_joins_its_wrap() -> None:
    """Must-not-trigger for the data-row guard: an ordinary sentence citing one amount is not a
    flattened table row and must still merge with its wrapped continuation, as before that guard
    existed."""
    rows = [
        _row(0.10, (0.07, "Wir bieten einen Ablösebetrag in Hoehe von EUR 1.234,56 an, sofern")),
        _row(0.118, (0.07, "Sie damit einverstanden sind.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Wir bieten einen Ablösebetrag in Hoehe von EUR 1.234,56 an, sofern "
        "Sie damit einverstanden sind."
    )


def test_long_prose_line_with_a_date_and_one_amount_still_joins_its_wrap() -> None:
    """Regression for a real corpus bug: a DD.MM.YYYY date (e.g. "13.06.2025") was itself matching
    the decimal-amount pattern, so a perfectly ordinary sentence naming one amount plus one date
    was counted as two amounts and wrongly treated as a flattened data row."""
    rows = [
        _row(
            0.10,
            (0.07, "Bitte ueberweisen Sie den Betrag von 2.238,00 EUR bis spaetestens 13.06.2025"),
        ),
        _row(0.118, (0.07, "auf unser Konto.")),
    ]
    raw = "\n".join(" ".join(cell.text for cell in row.cells) for row in rows)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == (
        "Bitte ueberweisen Sie den Betrag von 2.238,00 EUR bis spaetestens 13.06.2025 "
        "auf unser Konto."
    )


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


def _numbered_single_cell_rows(page_lines: list[list[str]]) -> list[ReadingRow]:
    return [
        ReadingRow(
            page_number=page_number,
            y0=0.05 + line_index * 0.10,
            y1=0.062 + line_index * 0.10,
            cells=(ReadingCell(text=line, x0=0.07, x1=0.07 + max(0.04, len(line) * 0.006)),),
        )
        for page_number, lines in enumerate(page_lines, 1)
        for line_index, line in enumerate(lines)
    ]


def test_repeated_case_number_header_keeps_one_occurrence_instead_of_vanishing() -> None:
    """Regression for a real corpus bug: a short, meaningful running header (a case number printed
    as "<case-number> Seite: N" on every page) was dropped entirely by the page-number-suffix
    cleanup on every page, including the one page where that same text is also the only place a
    required field value appears. Stripping just the "Seite: N" suffix and letting the existing
    cross-page dedup keep one occurrence recovers the value without reintroducing the running
    header everywhere else."""
    page_lines = [
        ["CASE-9001 Seite: 1", "First body"],
        ["CASE-9001 Seite: 2", "Second body"],
        ["CASE-9001 Seite: 3", "Third body"],
    ]
    pages = [_numbered_page("\n".join(lines), index) for index, lines in enumerate(page_lines, 1)]
    rows = _numbered_single_cell_rows(page_lines)
    raw = "\n\n".join(page.text for page in pages)

    result = build_reading_text(raw, pages, None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text.count("CASE-9001") == 1
    assert "Seite:" not in result.text
    assert "First body" in result.text
    assert "Second body" in result.text
    assert "Third body" in result.text


def test_bare_page_number_line_is_still_fully_dropped_on_every_page() -> None:
    page_lines = [
        ["Seite 1 von 3", "First body"],
        ["Seite 2 von 3", "Second body"],
        ["Seite 3 von 3", "Third body"],
    ]
    pages = [_numbered_page("\n".join(lines), index) for index, lines in enumerate(page_lines, 1)]
    rows = _numbered_single_cell_rows(page_lines)
    raw = "\n\n".join(page.text for page in pages)

    result = build_reading_text(raw, pages, None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Seite" not in result.text
    assert "First body" in result.text
    assert "Second body" in result.text
    assert "Third body" in result.text


def test_duplicated_bare_page_marker_fused_into_one_row_is_still_fully_dropped() -> None:
    """Regression for a real corpus bug: two copies of the exact same bare page-number marker
    (e.g. a running header duplicated by the source PDF) can land as two cells of the very same
    positioned row, rendering as "Seite 5 Seite 5". Stripping only the trailing copy left the
    other copy behind disguised as a "real" prefix; the cleanup must recognize that the leftover
    is itself still nothing but the same bare marker and drop it too."""
    page_lines = [
        ["Seite 1", "First body"],
        ["Seite 2", "Second body"],
        ["Seite 5 Seite 5", "Third body"],
    ]
    pages = [_numbered_page("\n".join(lines), index) for index, lines in enumerate(page_lines, 1)]
    rows = _numbered_single_cell_rows(page_lines)
    raw = "\n\n".join(page.text for page in pages)

    result = build_reading_text(raw, pages, None, [], None, positioned_rows=rows)

    assert result is not None
    assert "Seite" not in result.text
    assert "First body" in result.text
    assert "Second body" in result.text
    assert "Third body" in result.text


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
