from __future__ import annotations

from app.services.readable_text import build_readable_text


def test_build_readable_text_joins_simple_paragraph_lines() -> None:
    assert build_readable_text("First line\nsecond line") == "First line second line"


def test_build_readable_text_repairs_simple_hyphenation() -> None:
    assert build_readable_text("Daten-\nschutz") == "Datenschutz"


def test_build_readable_text_preserves_blank_line_paragraph_boundaries() -> None:
    assert build_readable_text("Alpha\nBeta\n\nGamma") == "Alpha Beta\n\nGamma"


def test_build_readable_text_normalizes_multiline_pages_with_markers() -> None:
    assert build_readable_text(
        "ignored",
        ["First\npage", "Second\r\npage"],
    ) == "First page\n\n----- page 2 -----\n\nSecond page"


def test_build_readable_text_returns_none_for_empty_text() -> None:
    assert build_readable_text("") is None
    assert build_readable_text(" \n\t\r\n") is None
