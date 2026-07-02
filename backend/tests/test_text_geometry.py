"""Unit tests for OCR/Text L10 line-level span geometry.

Covers schema validation, PDF text-layer and OCR polygon geometry builders, the assembled
``TextGeometry`` coverage/flags, and the internal ``resolve_span_geometry`` span lookup. No test
copies raw line text out of a geometry structure — geometry never carries it.
"""

from __future__ import annotations

from dataclasses import fields
from io import BytesIO

import pytest
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.schemas import (
    TextContent,
    TextGeometry,
    TextGeometryPage,
    TextLineGeometry,
)
from app.services.ocr_adapters import OcrExtractionResult, OcrLayoutLine
from app.services.text_geometry import (
    SpanLineBox,
    build_ocr_page_geometry,
    build_pdf_page_geometry,
    build_text_geometry,
    resolve_span_geometry,
)


def _pdf_page(runs: list[tuple[float, float, float, str]], width: int, height: int) -> object:
    """One synthetic page with text runs at absolute (x, y, font_size) positions."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=height)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    data = "".join(
        f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET\n" for x, y, size, text in runs
    )
    stream = DecodedStreamObject()
    stream.set_data(data.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return PdfReader(BytesIO(buffer.getvalue())).pages[0]


def _line(**overrides: object) -> TextLineGeometry:
    payload: dict[str, object] = {
        "line_index": 1,
        "canonical_start": 0,
        "canonical_end": 8,
        "page_start": 0,
        "page_end": 8,
        "x0": 10.0,
        "y0": 20.0,
        "x1": 90.0,
        "y1": 32.0,
        "source": "pdf_text_layer",
    }
    payload.update(overrides)
    return TextLineGeometry.model_validate(payload)


def _content_with_geometry(geometry: dict[str, object] | None, *, version: str | None) -> dict:
    return {
        "document_id": "d" * 32,
        "input_artifact_id": "a" * 32,
        "input_audit_artifact_id": "b" * 32,
        "source": "paddleocr",
        "text": "Line one\nLine two",
        "text_char_count": len("Line one\nLine two"),
        "pages": [
            {
                "page_number": 1,
                "source": "paddleocr",
                "has_text_layer": False,
                "ocr_used": True,
                "text": "Line one\nLine two",
                "text_char_count": len("Line one\nLine two"),
            }
        ],
        "text_geometry_version": version,
        "text_geometry": geometry,
    }


# --------------------------------------------------------------------------- schema


def test_geometry_field_is_optional_and_legacy_artifacts_load() -> None:
    content = TextContent.model_validate(_content_with_geometry(None, version=None))

    assert content.text_geometry is None
    assert content.text_geometry_version is None


def test_line_geometry_allows_degenerate_but_ordered_bounds() -> None:
    line = _line(x0=10.0, x1=10.0, y0=20.0, y1=20.0)

    assert (line.x0, line.x1, line.y0, line.y1) == (10.0, 10.0, 20.0, 20.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("x1", 9.0), ("y1", 19.0)],
)
def test_line_geometry_rejects_inverted_bounds(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _line(**{field: value})


def test_line_geometry_rejects_inverted_canonical_offsets() -> None:
    with pytest.raises(ValidationError):
        _line(canonical_start=8, canonical_end=0)


def test_line_geometry_rejects_inverted_page_offsets() -> None:
    with pytest.raises(ValidationError):
        _line(page_start=8, page_end=0)


def test_line_geometry_confidence_requires_ocr_source() -> None:
    with pytest.raises(ValidationError):
        _line(source="pdf_text_layer", confidence=0.9)


def test_page_geometry_requires_contiguous_line_indexes() -> None:
    with pytest.raises(ValidationError):
        TextGeometryPage.model_validate(
            {
                "page_number": 1,
                "page_width": 100.0,
                "page_height": 100.0,
                "coordinate_unit": "pdf_points",
                "source": "pdf_text_layer",
                "status": "complete",
                "lines": [_line(line_index=2).model_dump()],
            }
        )


def test_page_geometry_bounds_must_be_page_local() -> None:
    with pytest.raises(ValidationError):
        TextGeometryPage.model_validate(
            {
                "page_number": 1,
                "page_width": 50.0,
                "page_height": 50.0,
                "coordinate_unit": "pdf_points",
                "source": "pdf_text_layer",
                "status": "complete",
                "lines": [_line(x1=90.0).model_dump()],
            }
        )


def test_unsupported_page_must_not_carry_lines() -> None:
    with pytest.raises(ValidationError):
        TextGeometryPage.model_validate(
            {
                "page_number": 1,
                "page_width": 100.0,
                "page_height": 100.0,
                "coordinate_unit": "pdf_points",
                "source": "fallback",
                "status": "unsupported",
                "lines": [_line().model_dump()],
            }
        )


def test_geometry_pages_must_be_sorted_and_unique() -> None:
    with pytest.raises(ValidationError):
        TextGeometry.model_validate(
            {
                "coverage": 1.0,
                "flags": [],
                "pages": [
                    {
                        "page_number": 2,
                        "page_width": 100.0,
                        "page_height": 100.0,
                        "coordinate_unit": "pdf_points",
                        "source": "pdf_text_layer",
                        "status": "complete",
                        "lines": [_line().model_dump()],
                    },
                    {
                        "page_number": 1,
                        "page_width": 100.0,
                        "page_height": 100.0,
                        "coordinate_unit": "pdf_points",
                        "source": "pdf_text_layer",
                        "status": "complete",
                        "lines": [_line().model_dump()],
                    },
                ],
            }
        )


def test_content_requires_version_and_geometry_together() -> None:
    geometry = _valid_geometry_dict()
    with pytest.raises(ValidationError):
        TextContent.model_validate(_content_with_geometry(geometry, version=None))


def test_content_rejects_canonical_offsets_beyond_text() -> None:
    geometry = _valid_geometry_dict()
    geometry["pages"][0]["lines"][0]["canonical_end"] = 9999
    with pytest.raises(ValidationError):
        TextContent.model_validate(_content_with_geometry(geometry, version="1"))


def test_content_rejects_page_offsets_beyond_page_text() -> None:
    geometry = _valid_geometry_dict()
    geometry["pages"][0]["lines"][0]["page_end"] = 9999
    with pytest.raises(ValidationError):
        TextContent.model_validate(_content_with_geometry(geometry, version="1"))


def test_content_rejects_geometry_for_missing_page() -> None:
    geometry = _valid_geometry_dict()
    geometry["pages"][0]["page_number"] = 5
    with pytest.raises(ValidationError):
        TextContent.model_validate(_content_with_geometry(geometry, version="1"))


def _valid_geometry_dict() -> dict:
    return {
        "coverage": 1.0,
        "flags": ["ocr_geometry"],
        "pages": [
            {
                "page_number": 1,
                "page_width": 200.0,
                "page_height": 100.0,
                "coordinate_unit": "image_pixels",
                "source": "paddleocr",
                "status": "complete",
                "lines": [
                    {
                        "line_index": 1,
                        "canonical_start": 0,
                        "canonical_end": 8,
                        "page_start": 0,
                        "page_end": 8,
                        "x0": 10.0,
                        "y0": 10.0,
                        "x1": 190.0,
                        "y1": 40.0,
                        "source": "paddleocr",
                        "confidence": 0.9,
                    },
                    {
                        "line_index": 2,
                        "canonical_start": 9,
                        "canonical_end": 17,
                        "page_start": 9,
                        "page_end": 17,
                        "x0": 10.0,
                        "y0": 50.0,
                        "x1": 190.0,
                        "y1": 80.0,
                        "source": "paddleocr",
                        "confidence": 0.8,
                    },
                ],
            }
        ],
    }


# --------------------------------------------------------------------- PDF builder


def test_pdf_page_geometry_maps_lines_to_page_offsets() -> None:
    page = _pdf_page(
        [(40, 700, 12, "Line one alpha"), (40, 660, 12, "Line two beta")], 600, 800
    )
    page_text = page.extract_text() or ""

    geometry = build_pdf_page_geometry(page, 1, page_text, 0)

    assert geometry is not None
    assert geometry.coordinate_unit == "pdf_points"
    assert geometry.source == "pdf_text_layer"
    assert geometry.status == "complete"
    assert len(geometry.lines) == 2
    for line in geometry.lines:
        # Offsets index the canonical page text; base is 0 for a single page.
        assert line.canonical_start == line.page_start
        assert line.canonical_end == line.page_end
        assert page_text[line.page_start : line.page_end] in {"Line one alpha", "Line two beta"}
        assert 0.0 <= line.x0 <= line.x1 <= geometry.page_width
        assert 0.0 <= line.y0 <= line.y1 <= geometry.page_height
        assert line.confidence is None


def test_pdf_page_geometry_is_deterministic() -> None:
    page = _pdf_page([(40, 700, 12, "Alpha"), (40, 660, 12, "Beta")], 600, 800)
    page_text = page.extract_text() or ""

    first = build_pdf_page_geometry(page, 1, page_text, 0)
    second = build_pdf_page_geometry(page, 1, page_text, 0)

    assert first == second


def test_pdf_page_geometry_applies_canonical_base_offset() -> None:
    page = _pdf_page([(40, 700, 12, "Alpha")], 600, 800)
    page_text = page.extract_text() or ""

    geometry = build_pdf_page_geometry(page, 2, page_text, 100)

    assert geometry is not None
    line = geometry.lines[0]
    assert line.canonical_start == line.page_start + 100
    assert line.canonical_end == line.page_end + 100


def test_pdf_multi_column_layout_has_stable_ordering() -> None:
    # Two side-by-side runs on the same row: even when the page degrades to partial, the result
    # must be deterministic and never guess offsets.
    page = _pdf_page(
        [(40, 700, 10, "Left column"), (320, 700, 10, "Right column")], 600, 800
    )
    page_text = page.extract_text() or ""

    first = build_pdf_page_geometry(page, 1, page_text, 0)
    second = build_pdf_page_geometry(page, 1, page_text, 0)

    assert first == second
    assert first is not None
    assert first.status in {"complete", "partial", "unsupported"}
    indexes = [line.line_index for line in first.lines]
    assert indexes == list(range(1, len(indexes) + 1))


# --------------------------------------------------------------------- OCR builder


def _ocr_result(
    lines: tuple[OcrLayoutLine, ...], width: int | None, height: int | None
) -> OcrExtractionResult:
    text = "\n".join(line.text for line in lines)
    return OcrExtractionResult(
        text=text,
        confidence=0.9 if lines else None,
        layout_lines=lines,
        image_width=width,
        image_height=height,
    )


def test_ocr_page_geometry_from_polygons() -> None:
    lines = (
        OcrLayoutLine(
            text="Erste Zeile",
            polygon=((10.0, 20.0), (190.0, 20.0), (190.0, 50.0), (10.0, 50.0)),
            confidence=0.92,
        ),
        OcrLayoutLine(
            text="Zweite Zeile",
            polygon=((10.0, 60.0), (190.0, 60.0), (190.0, 90.0), (10.0, 90.0)),
            confidence=0.81,
        ),
    )
    result = _ocr_result(lines, 200, 100)

    geometry = build_ocr_page_geometry(result, 1, result.text, 0)

    assert geometry is not None
    assert geometry.coordinate_unit == "image_pixels"
    assert geometry.status == "complete"
    assert [line.confidence for line in geometry.lines] == [0.92, 0.81]
    assert geometry.lines[0].page_start == 0
    assert geometry.lines[0].page_end == len("Erste Zeile")
    assert geometry.lines[1].page_start == len("Erste Zeile") + 1


def test_ocr_page_geometry_without_polygons_is_unsupported() -> None:
    result = OcrExtractionResult(
        text="Recognized text", layout_lines=(), image_width=200, image_height=100
    )

    geometry = build_ocr_page_geometry(result, 1, result.text, 0)

    assert geometry is not None
    assert geometry.status == "unsupported"
    assert geometry.lines == []


def test_ocr_page_geometry_ignores_degenerate_polygon() -> None:
    lines = (
        OcrLayoutLine(
            text="Good line",
            polygon=((10.0, 20.0), (190.0, 20.0), (190.0, 50.0), (10.0, 50.0)),
            confidence=0.9,
        ),
        # A zero-height polygon must be dropped without breaking the page.
        OcrLayoutLine(
            text="Bad line",
            polygon=((10.0, 60.0), (190.0, 60.0), (190.0, 60.0), (10.0, 60.0)),
            confidence=0.5,
        ),
    )
    result = _ocr_result(lines, 200, 100)

    geometry = build_ocr_page_geometry(result, 1, result.text, 0)

    assert geometry is not None
    assert geometry.status == "partial"
    assert len(geometry.lines) == 1
    assert geometry.lines[0].page_start == 0


def test_ocr_page_geometry_without_image_size_returns_none() -> None:
    lines = (
        OcrLayoutLine(
            text="Line",
            polygon=((10.0, 20.0), (190.0, 20.0), (190.0, 50.0), (10.0, 50.0)),
            confidence=0.9,
        ),
    )
    result = _ocr_result(lines, None, None)

    assert build_ocr_page_geometry(result, 1, result.text, 0) is None


# ---------------------------------------------------------------- geometry assembly


def test_build_text_geometry_reports_coverage_and_flags() -> None:
    complete = TextGeometryPage.model_validate(
        {
            "page_number": 1,
            "page_width": 200.0,
            "page_height": 100.0,
            "coordinate_unit": "pdf_points",
            "source": "pdf_text_layer",
            "status": "complete",
            "lines": [_line(source="pdf_text_layer").model_dump()],
        }
    )
    unsupported = TextGeometryPage.model_validate(
        {
            "page_number": 2,
            "page_width": 200.0,
            "page_height": 100.0,
            "coordinate_unit": "image_pixels",
            "source": "paddleocr",
            "status": "unsupported",
            "lines": [],
        }
    )

    geometry = build_text_geometry([unsupported, complete], total_pages=2)

    assert geometry is not None
    assert geometry.coverage == 0.5
    assert [page.page_number for page in geometry.pages] == [1, 2]
    assert "mixed_geometry" in geometry.flags
    assert "partial_geometry" in geometry.flags


def test_build_text_geometry_empty_returns_none() -> None:
    assert build_text_geometry([], total_pages=3) is None


# -------------------------------------------------------------------- span lookup


def _span_geometry() -> TextGeometry:
    geometry = build_text_geometry(
        [
            TextGeometryPage.model_validate(
                {
                    "page_number": 1,
                    "page_width": 200.0,
                    "page_height": 100.0,
                    "coordinate_unit": "image_pixels",
                    "source": "paddleocr",
                    "status": "complete",
                    "lines": [
                        _line(
                            line_index=1,
                            canonical_start=0,
                            canonical_end=8,
                            page_start=0,
                            page_end=8,
                            source="paddleocr",
                            confidence=0.9,
                        ).model_dump(),
                        _line(
                            line_index=2,
                            canonical_start=9,
                            canonical_end=17,
                            page_start=9,
                            page_end=17,
                            source="paddleocr",
                            confidence=0.8,
                        ).model_dump(),
                    ],
                }
            )
        ],
        total_pages=1,
    )
    assert geometry is not None
    return geometry


def test_resolve_span_inside_one_line_returns_one_box() -> None:
    matches = resolve_span_geometry(_span_geometry(), 2, 5)

    assert len(matches) == 1
    assert matches[0].line_index == 1
    assert matches[0].coordinate_unit == "image_pixels"


def test_resolve_span_crossing_lines_returns_multiple_boxes() -> None:
    matches = resolve_span_geometry(_span_geometry(), 5, 12)

    assert [box.line_index for box in matches] == [1, 2]


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 5), (5, 5), (7, 3)],
)
def test_resolve_span_rejects_invalid_ranges(start: int, end: int) -> None:
    assert resolve_span_geometry(_span_geometry(), start, end) == []


def test_resolve_span_none_geometry_is_safe() -> None:
    assert resolve_span_geometry(None, 0, 5) == []


def test_span_line_box_carries_no_raw_text() -> None:
    field_names = {field.name for field in fields(SpanLineBox)}

    assert "text" not in field_names
