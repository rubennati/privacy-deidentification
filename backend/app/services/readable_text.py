"""Deterministic OCR L8 readable-text normalization.

Produces an additive human-readable rendering from the legacy technical raw OCR/Text output without
changing raw text or claiming any offset/lineage mapping. The algorithm is intentionally small and
conservative: line ending normalization, whitespace cleanup, paragraph joining, simple
line-break hyphen repair, and optional visible page boundaries between canonical pages.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_SPACE_RUN_RE = re.compile(r"[ \t]+")
_DEHYPHENATE_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}-$")
_WORD_START_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]")
_READABLE_PAGE_MARKER = "----- page {page_number} -----"


def build_readable_text(text: str, pages: Sequence[str] | None = None) -> str | None:
    """Return a readable normalization, or ``None`` when no useful text exists.

    ``text`` is the technical raw document text and remains unchanged elsewhere. When ``pages`` are
    available, each page is normalized independently and later pages receive a visible separator so
    human readers do not lose the original page transitions.
    """

    if pages:
        normalized_pages = [_normalize_block(page) for page in pages]
        if not any(normalized_pages):
            return None
        if len(normalized_pages) == 1:
            return normalized_pages[0]
        blocks: list[str] = []
        first_page = normalized_pages[0]
        if first_page:
            blocks.append(first_page)
        for page_number, page_text in enumerate(normalized_pages[1:], start=2):
            blocks.append(_READABLE_PAGE_MARKER.format(page_number=page_number))
            if page_text:
                blocks.append(page_text)
        combined = "\n\n".join(blocks)
        return combined or None
    return _normalize_block(text)


def _normalize_block(text: str) -> str | None:
    if not text:
        return None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = _normalize_line(line)
        if stripped == "":
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)

    if not paragraphs:
        return None
    rendered = "\n\n".join(_join_paragraph(paragraph) for paragraph in paragraphs if paragraph)
    return rendered or None


def _normalize_line(line: str) -> str:
    return _SPACE_RUN_RE.sub(" ", line.strip())


def _join_paragraph(lines: Sequence[str]) -> str:
    combined = lines[0]
    for line in lines[1:]:
        if _should_dehyphenate(combined, line):
            combined = combined[:-1] + line
        else:
            combined = f"{combined} {line}"
    return combined


def _should_dehyphenate(previous: str, current: str) -> bool:
    return bool(_DEHYPHENATE_RE.search(previous) and _WORD_START_RE.match(current))
