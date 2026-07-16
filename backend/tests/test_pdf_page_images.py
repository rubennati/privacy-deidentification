"""Unit tests for significant-image detection and OCR supplement dedup (mixed pages)."""

from __future__ import annotations

from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import DictionaryObject, NameObject, NullObject, NumberObject

from app.services.pdf_page_images import (
    SIGNIFICANT_IMAGE_MIN_DIMENSION,
    SIGNIFICANT_IMAGE_MIN_PIXELS,
    build_ocr_supplement,
    count_significant_images,
)


def _image_xobject(width: int, height: int) -> DictionaryObject:
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
        }
    )


def _page_with_xobjects(*xobjects: DictionaryObject | NullObject) -> PageObject:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    entries = DictionaryObject(
        {NameObject(f"/Im{index}"): xobject for index, xobject in enumerate(xobjects)}
    )
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): entries})
    return page


class TestCountSignificantImages:
    def test_page_without_resources_counts_zero(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=200, height=200)
        if "/Resources" in page:
            del page[NameObject("/Resources")]
        assert count_significant_images(page) == 0

    def test_page_without_xobjects_counts_zero(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=200, height=200)
        page[NameObject("/Resources")] = DictionaryObject()
        assert count_significant_images(page) == 0

    def test_embedded_scan_counts(self) -> None:
        page = _page_with_xobjects(_image_xobject(800, 1100))
        assert count_significant_images(page) == 1

    def test_small_logo_does_not_count(self) -> None:
        page = _page_with_xobjects(_image_xobject(180, 60))
        assert count_significant_images(page) == 0

    def test_flat_banner_below_min_dimension_does_not_count(self) -> None:
        # 1000x150: large area, but too flat to be a document scan by our threshold.
        page = _page_with_xobjects(_image_xobject(1000, SIGNIFICANT_IMAGE_MIN_DIMENSION - 50))
        assert count_significant_images(page) == 0

    def test_letterhead_banner_counts(self) -> None:
        page = _page_with_xobjects(_image_xobject(1000, 250))
        assert count_significant_images(page) == 1

    def test_min_area_is_enforced(self) -> None:
        # Both dimensions pass, but the pixel area stays below the floor.
        width = SIGNIFICANT_IMAGE_MIN_DIMENSION
        height = SIGNIFICANT_IMAGE_MIN_PIXELS // width - 1
        assert height >= SIGNIFICANT_IMAGE_MIN_DIMENSION
        page = _page_with_xobjects(_image_xobject(width, height))
        assert count_significant_images(page) == 0

    def test_mixed_images_count_only_significant(self) -> None:
        page = _page_with_xobjects(
            _image_xobject(120, 40),  # icon
            _image_xobject(600, 800),  # scan
            _image_xobject(640, 480),  # photo
        )
        assert count_significant_images(page) == 2

    def test_non_image_xobject_is_ignored(self) -> None:
        form = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
            }
        )
        page = _page_with_xobjects(form, _image_xobject(600, 800))
        assert count_significant_images(page) == 1

    def test_malformed_xobject_is_skipped_not_raised(self) -> None:
        broken = DictionaryObject(
            {
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NameObject("/NotANumber"),
            }
        )
        page = _page_with_xobjects(broken, _image_xobject(600, 800))
        assert count_significant_images(page) == 1

    def test_missing_dimensions_do_not_count(self) -> None:
        no_size = DictionaryObject({NameObject("/Subtype"): NameObject("/Image")})
        page = _page_with_xobjects(no_size)
        assert count_significant_images(page) == 0


class TestBuildOcrSupplement:
    def test_lines_already_in_text_layer_are_dropped(self) -> None:
        extracted = "KOSTENVORANSCHLAG\nBausanierung 2026"
        ocr = (
            "KOSTENVORANSCHLAG\nBausanierung 2026\n"
            "Rechnung Nr. 4711\nIBAN AT61 1904 3002 3457 3201"
        )
        assert build_ocr_supplement(extracted, ocr) == (
            "Rechnung Nr. 4711\nIBAN AT61 1904 3002 3457 3201"
        )

    def test_whitespace_and_case_differences_still_dedup(self) -> None:
        extracted = "Kostenvoranschlag  Bausanierung"
        ocr = "KOSTENVORANSCHLAG BAUSANIERUNG\nNeue Zeile 12"
        assert build_ocr_supplement(extracted, ocr) == "Neue Zeile 12"

    def test_fully_duplicated_ocr_yields_empty_supplement(self) -> None:
        extracted = "Zeile eins\nZeile zwei"
        assert build_ocr_supplement(extracted, "Zeile eins\n\nZeile zwei\n") == ""

    def test_empty_ocr_yields_empty_supplement(self) -> None:
        assert build_ocr_supplement("Irgendein Text", "") == ""

    def test_supplement_preserves_order_and_original_text(self) -> None:
        extracted = "Kopfzeile"
        ocr = "Kopfzeile\nDr. Eva Muster\nSteuernummer 12 345/6789\nDr. Eva Muster"
        # Order kept; repeated new lines are kept once each occurrence (no aggressive dedup of
        # supplement-internal repeats — repeated occurrences are meaningful for review).
        assert build_ocr_supplement(extracted, ocr) == (
            "Dr. Eva Muster\nSteuernummer 12 345/6789\nDr. Eva Muster"
        )

    def test_blank_ocr_lines_are_dropped(self) -> None:
        assert build_ocr_supplement("", "\n\n  \nInhalt\n") == "Inhalt"
