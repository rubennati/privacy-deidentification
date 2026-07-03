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


def test_flat_list_with_an_invoice_style_label_is_not_split_into_a_metadata_section() -> None:
    """A generic label like 'Rechnungsnummer:' appearing mid-list must not, on its own, carve the
    remaining rows into a separate metadata block. Without a party heading or an offer-specific
    marker (Angebot/Bauvorhaben/Projekt), a flat, evenly spaced list of one-line facts is not a
    quote/invoice header and must stay a single, consistently rendered block."""
    lines = [
        "Fact one: Alpha",
        "Fact two: Beta",
        "Fact three: Gamma",
        "Rechnungsnummer: RE-0000001",
        "Fact five: Delta",
    ]
    rows = [_row(0.10 + index * 0.018, (0.07, line)) for index, line in enumerate(lines)]
    raw = "\n".join(lines)

    result = build_reading_text(raw, [_page(raw)], None, [], None, positioned_rows=rows)

    assert result is not None
    assert result.text == raw
    assert result.status == "heuristic"
    assert "document_sections" not in result.flags


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
