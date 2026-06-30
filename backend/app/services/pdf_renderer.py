"""Replaceable PDF page rendering boundary for OCR input."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from pdf2image import convert_from_path


class PdfRenderer(Protocol):
    """Render one 1-based PDF page to a raster image."""

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path: ...


class Pdf2ImageRenderer:
    """Render individual pages through pdf2image/Poppler."""

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        rendered = convert_from_path(
            pdf_path,
            first_page=page_number,
            last_page=page_number,
            fmt="png",
            output_folder=output_dir,
            output_file=f"page-{page_number}",
            single_file=True,
            paths_only=True,
            thread_count=1,
            timeout=60,
        )
        if len(rendered) != 1:
            raise RuntimeError("PDF renderer returned an unexpected number of pages")
        return Path(cast(str | Path, rendered[0]))


@lru_cache
def get_pdf_renderer() -> PdfRenderer:
    """Provide the production PDF renderer to FastAPI."""
    return Pdf2ImageRenderer()
