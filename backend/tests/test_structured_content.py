"""OCR/Text L11 schema and deterministic structure-extraction tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    StructuredBounds,
    StructuredContent,
    StructuredContentSummary,
    StructuredPageContent,
    StructuredSpan,
    StructuredTable,
    StructuredTableCell,
    TextContent,
    TextPageResult,
)
from app.services.structured_content import build_structured_content


def _page(text: str) -> TextPageResult:
    return TextPageResult(
        page_number=1,
        source="pdf_text_layer",
        has_text_layer=True,
        ocr_used=False,
        text=text,
        text_char_count=len(text),
    )


def _content(text: str, structured: StructuredContent | None) -> TextContent:
    return TextContent(
        document_id="d" * 32,
        input_artifact_id="a" * 32,
        input_audit_artifact_id="b" * 32,
        source="pdf_text_layer",
        text=text,
        text_char_count=len(text),
        pages=[_page(text)],
        structured_content_version="1" if structured is not None else None,
        structured_content=structured,
    )


def test_structured_content_is_optional_and_legacy_compatible() -> None:
    content = _content("Legacy", None)

    assert content.structured_content_version is None
    assert content.structured_content is None


def test_structured_content_version_is_validated() -> None:
    structured = StructuredContent(
        pages=[],
        summary=StructuredContentSummary(
            page_count=0, table_count=0, field_count=0, section_count=0
        ),
        flags=["empty"],
    )

    with pytest.raises(ValidationError, match="version must be present together"):
        TextContent.model_validate(
            {
                **_content("Legacy", None).model_dump(),
                "structured_content": structured.model_dump(),
            }
        )


def test_invalid_spans_indexes_and_bounds_are_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        StructuredSpan(canonical_start=2, canonical_end=2, page_start=2, page_end=2)
    with pytest.raises(ValidationError, match="positive width"):
        StructuredBounds(
            x0=2, y0=0, x1=2, y1=1, coordinate_unit="pdf_points"
        )
    with pytest.raises(ValidationError, match="column index/span"):
        StructuredTable(
            table_id="table-p1-1",
            page_number=1,
            row_count=1,
            column_count=1,
            cells=[
                StructuredTableCell(
                    row_index=0,
                    column_index=1,
                    span=StructuredSpan(
                        canonical_start=0,
                        canonical_end=1,
                        page_start=0,
                        page_end=1,
                    ),
                )
            ],
            source="canonical_text",
            confidence=0.5,
        )


def test_flagged_empty_partial_structures_are_allowed() -> None:
    table = StructuredTable(
        table_id="table-p1-1",
        page_number=1,
        row_count=0,
        column_count=0,
        source="canonical_text",
        confidence=0.2,
        flags=["partial_table"],
    )
    content = StructuredContent(
        pages=[
            StructuredPageContent(
                page_number=1,
                tables=[table],
                source="canonical_text",
                confidence=0.2,
                quality_flags=["partial_structure"],
            )
        ],
        summary=StructuredContentSummary(
            page_count=1, table_count=1, field_count=0, section_count=0
        ),
        flags=["partial_structure"],
    )

    assert content.pages[0].tables[0].cells == []


@pytest.mark.parametrize(
    ("text", "label", "hint"),
    [
        ("Name: Max Mustermann", "Name", "person_name"),
        ("IBAN: DE01 2345 6789 0123 4567 89", "IBAN", "iban"),
        ("Vertragsnummer: AB-12345", "Vertragsnummer", "contract_id"),
    ],
)
def test_inline_fields_are_span_backed(text: str, label: str, hint: str) -> None:
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    field = structured.pages[0].fields[0]
    assert field.label == label
    assert field.field_type_hint == hint
    assert text[field.label_span.canonical_start : field.label_span.canonical_end] == label
    assert text[field.value_span.canonical_start : field.value_span.canonical_end]
    assert "value" not in field.model_dump()


def test_next_line_field_is_conservative_and_ambiguous_lines_are_ignored() -> None:
    text = "Kundennummer\nKD-9981\nThis is - ordinary prose"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    assert [field.label for field in structured.pages[0].fields] == ["Kundennummer"]
    assert structured.pages[0].fields[0].flags == ["value_on_next_line"]


def test_multiline_value_on_next_line_is_attached() -> None:
    """OCR/Text L13: a value below its label may itself span multiple following lines."""
    text = "Anschrift\nMusterstraße 1\n1010 Wien"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    field = structured.pages[0].fields[0]
    assert field.label == "Anschrift"
    assert "multiline_value" in field.flags
    assert (
        text[field.value_span.canonical_start : field.value_span.canonical_end]
        == "Musterstraße 1\n1010 Wien"
    )


def test_multiline_inline_value_continuation_is_attached() -> None:
    """OCR/Text L13: an inline label/value line may still wrap onto a following plain line."""
    text = "Adresse: Musterstraße 1\n1010 Wien"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    field = structured.pages[0].fields[0]
    assert field.label == "Adresse"
    assert "multiline_value" in field.flags
    assert (
        text[field.value_span.canonical_start : field.value_span.canonical_end]
        == "Musterstraße 1\n1010 Wien"
    )


def test_multiline_value_continuation_stops_before_the_next_field() -> None:
    """Must-not-trigger: a following line that is itself a recognizable field must not be
    absorbed into the previous field's value."""
    text = "Anschrift\nMusterstraße 1\nTelefon: +43 1 2345678"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    labels = [field.label for field in structured.pages[0].fields]
    assert labels == ["Anschrift", "Telefon"]
    anschrift = structured.pages[0].fields[0]
    assert "multiline_value" not in anschrift.flags
    assert (
        text[anschrift.value_span.canonical_start : anschrift.value_span.canonical_end]
        == "Musterstraße 1"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Name | Betrag\nAnna | 10\nBob | 20",
        "Name  Betrag\nAnna  10\nBob   20",
    ],
)
def test_simple_tables_reference_canonical_spans(text: str) -> None:
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    table = structured.pages[0].tables[0]
    assert (table.row_count, table.column_count) == (3, 2)
    assert table.cells[0].role == "header"
    for cell in table.cells:
        assert text[cell.span.canonical_start : cell.span.canonical_end].strip()


def test_inconsistent_table_is_partial_and_flagged() -> None:
    text = "A | B\n1 | 2 | extra\n3 | 4"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    table = structured.pages[0].tables[0]
    assert table.column_count == 3
    assert table.confidence < 0.7
    assert table.flags == ["partial_table", "inconsistent_column_count"]


def test_heading_followed_by_fields_creates_valid_section() -> None:
    text = "VERTRAGSDATEN\nName: Max Mustermann\nDatum: 03.07.2026"
    structured = build_structured_content(text, [_page(text)], [], None)

    assert structured is not None
    section = structured.pages[0].sections[0]
    assert section.heading == "VERTRAGSDATEN"
    assert len(section.field_ids) == 2
    assert section.span.canonical_start == 0
    assert section.span.canonical_end <= len(text)


def test_extraction_keeps_canonical_and_page_text_byte_identical() -> None:
    text = "Name: Max Mustermann\nIBAN: DE01 2345 6789 0123 4567 89"
    page = _page(text)
    before = page.model_dump()

    structured = build_structured_content(text, [page], [], None)
    content = _content(text, structured)

    assert content.text == text
    assert content.text_char_count == len(text)
    assert content.pages[0].model_dump() == before
