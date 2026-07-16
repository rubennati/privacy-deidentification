"""Detect significant embedded images on PDF text-layer pages (mixed-page OCR routing).

A page whose text layer is usable can still hide sensitive content inside an *embedded image* —
the classic case is a Word document with a pasted scan (invoice, ID card) exported as PDF. The
per-page quality routing only judges the extracted text, so such a page keeps its text layer and
the scan is never OCR'd: its PII is invisible to detection. This module provides the two pure
helpers the OCR/Text station uses to close that recall gap:

- :func:`count_significant_images` decides whether a page carries an image large enough to
  plausibly hold document content (scan, photo of a document), reading only the page's XObject
  dictionaries — image data is **never decoded**, so malformed or exotic encodings cannot break
  extraction.
- :func:`build_ocr_supplement` reduces a full-page OCR pass to the lines the text layer does not
  already contain, so the supplement adds the image's text without duplicating the typed text.

Recall-first tradeoffs, chosen deliberately (recall >> precision): a decorative image above the
size thresholds triggers one extra OCR pass whose output is mostly deduplicated away or empty —
harmless. Known limitations (documented, acceptable for v1): inline images (``BI``/``ID``/``EI``
operators) and images nested inside Form XObjects are not counted, and an image that is present in
the page resources but never drawn still counts.
"""

from __future__ import annotations

from pypdf._page import PageObject

# An embedded image is "significant" when it is plausibly a scanned document rather than a logo or
# icon. Thresholds are intrinsic pixel dimensions from the XObject dictionary (placement size is
# not available without interpreting the content stream): even a low-resolution scan of a receipt
# is several hundred pixels on each side, while logos and icons stay small in at least one
# dimension. A letterhead banner (e.g. 1000x250) counts — letterheads carry addresses and phone
# numbers, and recall wins over the cost of one extra OCR pass.
SIGNIFICANT_IMAGE_MIN_DIMENSION = 200
SIGNIFICANT_IMAGE_MIN_PIXELS = 100_000


def count_significant_images(page: PageObject) -> int:
    """Count embedded images on ``page`` that are large enough to hold document content.

    Reads only ``/Resources -> /XObject`` entries with ``/Subtype /Image`` and their declared
    ``/Width``/``/Height``; the image streams themselves are never decoded. Malformed entries are
    skipped rather than raised so a single broken XObject cannot fail the page.
    """
    resources = page.get("/Resources")
    if resources is None:
        return 0
    xobjects = resources.get_object().get("/XObject") if resources is not None else None
    if xobjects is None:
        return 0
    count = 0
    for xobject in xobjects.get_object().values():
        try:
            candidate = xobject.get_object()
            if candidate.get("/Subtype") != "/Image":
                continue
            width = int(candidate.get("/Width", 0))
            height = int(candidate.get("/Height", 0))
        except Exception:  # one malformed XObject must not fail the page
            continue
        if min(width, height) < SIGNIFICANT_IMAGE_MIN_DIMENSION:
            continue
        if width * height < SIGNIFICANT_IMAGE_MIN_PIXELS:
            continue
        count += 1
    return count


def build_ocr_supplement(extracted_text: str, ocr_text: str) -> str:
    """Return the OCR lines that the extracted text layer does not already contain.

    A full-page OCR pass re-reads the typed text alongside the embedded image, so the raw OCR
    output would duplicate the whole page. Lines whose whitespace/case-normalized form already
    appears in the extracted text are dropped; the remainder — the image-only content — keeps its
    original order and text. Dropping an exact-duplicate line never loses recall: the identical
    value is already present (and detected) in the text layer. Lines the OCR merely re-wraps
    differently survive dedup and appear twice; that is accepted noise, not a recall problem.
    """
    known = {_normalize_line(line) for line in extracted_text.splitlines()}
    known.discard("")
    supplement_lines = []
    for line in ocr_text.splitlines():
        normalized = _normalize_line(line)
        if not normalized or normalized in known:
            continue
        supplement_lines.append(line)
    return "\n".join(supplement_lines)


def _normalize_line(line: str) -> str:
    """Collapse whitespace and case so typography differences do not defeat dedup."""
    return " ".join(line.split()).casefold()
