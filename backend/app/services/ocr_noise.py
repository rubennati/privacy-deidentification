"""Deterministic OCR/Text L15 noise / token artifact evidence.

This module answers, for every OCR/Text artifact, *which spans look like OCR noise* — glyph
artifacts, suspicious token shapes, plausible O/0, I/l/1, and rn/m character confusions, and broken
spacing (words split into single letters or joined together) — from shape alone. It is additive,
metrics-only **evidence**, not correction: it never rewrites, removes, or reorders any text, and it
never stores raw token text. Every finding is located by an offset range into the immutable
technical raw text, tagged with a stable ``reason_code`` and small integer ``details``.

Scope (L15): deterministic shape/noise signals only. No dictionary/lexicon lookup, no
spell-checking, no autocorrect, no second OCR engine, and no local LLM — those remain later,
additive *evidence, not truth* sources (see ADR-0026). This module answers "where does this look
like noise" — never "what is the correct text."

False-positive guards are conservative by design: tokens that look like structured identifiers
(letters/digits joined by ``-``, ``_``, ``.``, ``/``, or ``:`` into homogeneous segments, e.g.
invoice/policy numbers) or IBAN-shaped strings are exempted from shape/confusion checks, and runs of
common divider/bullet/leader characters (``-_=+|.*~`` and a few Unicode bullet marks) are treated as
intentional structure rather than noise, even when long.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise

from app.schemas import (
    QualityEvidenceItem,
    QualityEvidenceStatus,
    QualityEvidenceType,
    QualityOffsetRange,
    QualityPageZone,
    TextPageResult,
)

_TOKEN_RE = re.compile(r"\S+")

# Characters that commonly form intentional dividers, bullets, table borders, or leader dots. A run
# made up only of these characters is treated as structure, never as noise, regardless of length.
_STRUCTURAL_RUN_CHARS = frozenset("-+|_=.*~•◦‣▪·:")

# Rare standalone punctuation that is not ordinary sentence punctuation, currency, section, or math
# notation and is very unlikely to appear alone as a real token in prose, legal references, prices,
# or structured identifiers.
_RARE_STANDALONE_CHARS = frozenset("¬¦¤`^~")

# Unicode categories that signal a scanner/rendering artifact rather than real content: private-use,
# unassigned, and surrogate codepoints.
_ARTIFACT_UNICODE_CATEGORIES = frozenset({"Co", "Cn", "Cs"})
_REPLACEMENT_CHAR = "�"
_BOX_DRAWING_RANGE = (0x2500, 0x259F)

_SYMBOL_RUN_MIN = 5
_SYMBOL_RUN_LARGE = 12
# A run is only noise once at least this many characters fall outside the structural allowlist —
# one incidental character (e.g. a stray closing bracket landing right next to a long intentional
# underscore blank-line/signature field) must not disqualify the whole run from being structure.
_NON_STRUCTURAL_MIN = 3

_SHAPE_MIN_LENGTH = 4
_HIGH_SYMBOL_RATIO_THRESHOLD = 0.5
_LOW_LETTER_RATIO_THRESHOLD = 0.3

_CONFUSION_MIN_LENGTH = 3
_RN_M_MAX_LENGTH = 6
# Genuine confusion requires letters and digits to actually alternate (e.g. "1o2O3l"); a token
# split into several same-class segments by symbols (e.g. a hyphenated compound word) has zero
# alternations and must never count, regardless of how many segments it has.
_MIXED_ALNUM_ALTERNATION_MIN = 3
_O_ZERO_LETTERS = frozenset({"o", "O"})
_I_L_ONE_LETTERS = frozenset({"i", "I", "l"})

_SPACING_RUN_MIN = 2
_SPACING_RUN_HIGH_MIN = 5

_JOINED_TOKEN_MIN_LENGTH = 10
_JOINED_SEGMENT_MIN_LENGTH = 4

# Trailing punctuation attached to a token from surrounding sentence context (a comma, closing
# quote/bracket, or sentence-final mark right after a word) rather than part of the token's own
# shape. Deliberately excludes ``.`` — a period is often load-bearing inside an abbreviation or
# identifier (``Nr.``, ``z.B.``, ``u.s.w.``) and must not be stripped.
_TRAILING_STRIP_CHARS = frozenset(",;:!?)]}\"'”’")  # noqa: RUF001 -- closing quote marks

# Separators that split a token into a "structured identifier" (invoice/policy numbers, filenames,
# dates) when every resulting segment is homogeneously alphabetic or numeric.
_SEPARATOR_CHARS = "-_./:"
_SEPARATOR_RUN_RE = re.compile(f"[{re.escape(_SEPARATOR_CHARS)}]+")
_IBAN_LIKE_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")

# (id_kind, type, status, reason_code) — the shape of one per-token finding.
_TokenFinding = tuple[str, QualityEvidenceType, QualityEvidenceStatus, str]


def build_ocr_noise_evidence(
    *,
    text: str,
    pages: Sequence[TextPageResult],
    page_zones: Mapping[int, QualityPageZone] | None = None,
) -> list[QualityEvidenceItem]:
    """Build additive OCR/Text L15 noise/token artifact evidence for one artifact.

    Scans technical raw per-page text (never reading text, structured content, or any
    reconstruction) for deterministic shape-based noise signals and always appends one
    document-level ``ocr_noise_summary`` item, even when no noise is found — so every artifact can
    be audited. ``page_zones`` is an optional page-number -> zone map reusing the existing L14 page
    zone classification; when absent, noise items simply carry no zone tag.
    """

    zones = page_zones or {}
    items: list[QualityEvidenceItem] = []
    for page_number, page_text, base_offset in _iter_pages(text, pages):
        if not page_text:
            continue
        zone = zones.get(page_number) if page_number is not None else None
        prefix = str(page_number) if page_number is not None else "doc"
        items.extend(_scan_page(page_text, page_number, base_offset, zone, prefix))
    items.append(_noise_summary_item(text, items))
    return items


def _iter_pages(
    text: str, pages: Sequence[TextPageResult]
) -> list[tuple[int | None, str, int]]:
    """Yield (page_number, page_text, base_offset) triples for scanning.

    ``base_offset`` mirrors how ``text`` is assembled elsewhere (``"\\n\\n".join(page.text ...)``),
    so a page-local match position plus its base offset lands on the same technical raw text offset
    that ``text_geometry``/``reading_text_map`` already use. Pageless artifacts (DOCX) scan ``text``
    directly as a single unpaged unit.
    """

    if not pages:
        return [(None, text, 0)]
    entries: list[tuple[int | None, str, int]] = []
    base = 0
    for page in pages:
        entries.append((page.page_number, page.text, base))
        base += len(page.text) + 2
    return entries


def _scan_page(
    page_text: str,
    page_number: int | None,
    base_offset: int,
    zone: QualityPageZone | None,
    id_prefix: str,
) -> list[QualityEvidenceItem]:
    counter = 0

    def next_id(kind: str) -> str:
        nonlocal counter
        counter += 1
        return f"noise-{id_prefix}-{kind}-{counter:03d}"

    args = (page_text, page_number, base_offset, zone, next_id)
    return [
        *_symbol_run_items(*args),
        *_token_scan_items(*args),
        *_spacing_run_items(*args),
    ]


def _symbol_run_items(
    page_text: str,
    page_number: int | None,
    base_offset: int,
    zone: QualityPageZone | None,
    next_id: Callable[[str], str],
) -> list[QualityEvidenceItem]:
    items: list[QualityEvidenceItem] = []
    for start, end, run_text in _symbol_runs(page_text):
        length = end - start
        if length < _SYMBOL_RUN_MIN:
            continue
        non_structural = [ch for ch in run_text if ch not in _STRUCTURAL_RUN_CHARS]
        if len(non_structural) < _NON_STRUCTURAL_MIN:
            continue
        homogeneous = len(set(run_text)) == 1
        reason = "repeated_punctuation" if homogeneous else "symbol_run"
        evidence_type: QualityEvidenceType = (
            "non_text_artifact" if length >= _SYMBOL_RUN_LARGE else "low_information_symbol_run"
        )
        items.append(
            QualityEvidenceItem(
                evidence_id=next_id("run"),
                level="span",
                type=evidence_type,
                status="partial",
                reason_code=reason,
                page_number=page_number,
                raw_text_range=_range(base_offset, start, end),
                page_zone=zone,
                flags=["ocr_noise"],
                details={"run_length": length},
            )
        )
    return items


def _strip_trailing_punctuation(token: str) -> str:
    """Drop trailing punctuation attached from sentence context (comma, closing quote/bracket,
    sentence-final mark), so a normal word or abbreviation followed by such punctuation is
    analyzed on its own shape rather than the shape plus incidental context."""

    stripped = token
    while len(stripped) > 1 and stripped[-1] in _TRAILING_STRIP_CHARS:
        stripped = stripped[:-1]
    return stripped


def _token_findings(token: str) -> list[_TokenFinding]:
    """(id_kind, type, status, reason_code) tuples for every signal this token triggers."""

    findings: list[_TokenFinding] = []
    analyzed = _strip_trailing_punctuation(token)

    glyph_reason = _glyph_artifact_reason(token)
    if glyph_reason is not None:
        glyph_status: QualityEvidenceStatus = (
            "confident" if glyph_reason == "unsupported_glyph_cluster" else "low_confidence"
        )
        findings.append(("glyph", "glyph_artifact", glyph_status, glyph_reason))

    shape_reason = _shape_reason(analyzed)
    if shape_reason is not None:
        findings.append(("shape", "suspicious_token_shape", "partial", shape_reason))

    confusion_reason = _confusion_reason(analyzed)
    if confusion_reason is not None:
        confusion_status: QualityEvidenceStatus = (
            "partial" if confusion_reason == "mixed_alnum_confusion" else "low_confidence"
        )
        findings.append(("confusion", "character_confusion", confusion_status, confusion_reason))

    joined_reason = _joined_word_reason(analyzed)
    if joined_reason is not None:
        findings.append(("joined", "joined_word_candidate", "low_confidence", joined_reason))

    return findings


def _token_scan_items(
    page_text: str,
    page_number: int | None,
    base_offset: int,
    zone: QualityPageZone | None,
    next_id: Callable[[str], str],
) -> list[QualityEvidenceItem]:
    items: list[QualityEvidenceItem] = []
    for match in _TOKEN_RE.finditer(page_text):
        token = match.group()
        for kind, type_, status, reason in _token_findings(token):
            items.append(
                _token_item(
                    next_id(kind), type_, status, reason,
                    page_number, base_offset, match.start(), match.end(), zone, len(token),
                )
            )
    return items


def _spacing_run_items(
    page_text: str,
    page_number: int | None,
    base_offset: int,
    zone: QualityPageZone | None,
    next_id: Callable[[str], str],
) -> list[QualityEvidenceItem]:
    items: list[QualityEvidenceItem] = []
    for start, end, token_count in _spacing_runs(page_text):
        spacing_type: QualityEvidenceType
        spacing_status: QualityEvidenceStatus
        if token_count >= _SPACING_RUN_HIGH_MIN:
            spacing_type, reason, spacing_status = (
                "split_word_candidate", "excessive_single_char_tokens", "partial",
            )
        else:
            spacing_type, reason, spacing_status = (
                "suspicious_spacing", "suspicious_split_spacing", "low_confidence",
            )
        items.append(
            QualityEvidenceItem(
                evidence_id=next_id("spacing"),
                level="span",
                type=spacing_type,
                status=spacing_status,
                reason_code=reason,
                page_number=page_number,
                raw_text_range=_range(base_offset, start, end),
                page_zone=zone,
                flags=["ocr_noise"],
                details={"token_count": token_count},
            )
        )
    return items


def _range(base_offset: int, start: int, end: int) -> QualityOffsetRange:
    return QualityOffsetRange(start=base_offset + start, end=base_offset + end)


def _token_item(
    evidence_id: str,
    type_: QualityEvidenceType,
    status: QualityEvidenceStatus,
    reason: str,
    page_number: int | None,
    base_offset: int,
    start: int,
    end: int,
    zone: QualityPageZone | None,
    token_length: int,
) -> QualityEvidenceItem:
    return QualityEvidenceItem(
        evidence_id=evidence_id,
        level="span",
        type=type_,
        status=status,
        reason_code=reason,
        page_number=page_number,
        raw_text_range=_range(base_offset, start, end),
        page_zone=zone,
        flags=["ocr_noise"],
        details={"token_length": token_length},
    )


def _symbol_runs(page_text: str) -> list[tuple[int, int, str]]:
    """Maximal runs of consecutive non-alphanumeric, non-whitespace characters."""

    runs: list[tuple[int, int, str]] = []
    start: int | None = None
    for index, ch in enumerate(page_text):
        is_symbol = not ch.isalnum() and not ch.isspace()
        if is_symbol:
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index, page_text[start:index]))
            start = None
    if start is not None:
        runs.append((start, len(page_text), page_text[start:]))
    return runs


def _glyph_artifact_reason(token: str) -> str | None:
    if _REPLACEMENT_CHAR in token:
        return "unsupported_glyph_cluster"
    for ch in token:
        code_point = ord(ch)
        if _BOX_DRAWING_RANGE[0] <= code_point <= _BOX_DRAWING_RANGE[1]:
            return "unsupported_glyph_cluster"
        if unicodedata.category(ch) in _ARTIFACT_UNICODE_CATEGORIES:
            return "unsupported_glyph_cluster"
    if len(token) == 1 and token in _RARE_STANDALONE_CHARS:
        return "isolated_glyph_like_token"
    return None


def _is_structured_identifier(token: str) -> bool:
    """A token split by ``-_./:`` into 2+ segments that are each purely alphabetic or numeric.

    Covers invoice/policy numbers, dates, and filenames (e.g. ``INV-2024-00123``,
    ``Report_2024_Final.pdf``) so they are exempt from shape and confusion checks below.
    """

    if not any(ch in _SEPARATOR_CHARS for ch in token):
        return False
    segments = [segment for segment in _SEPARATOR_RUN_RE.split(token) if segment]
    if len(segments) < 2:
        return False
    return all(segment.isalpha() or segment.isdigit() for segment in segments)


def _is_exempt_identifier(token: str) -> bool:
    return bool(_IBAN_LIKE_RE.match(token)) or _is_structured_identifier(token)


def _has_dominant_structural_run(token: str) -> bool:
    """True if a long, (near-)purely structural run is embedded in this token.

    A short label or number glued — with no separating whitespace — to a long intentional
    underline/blank-field or divider run (e.g. a form field name immediately followed by
    underscores) must not have that filler drag the *whole token's* symbol ratio over threshold;
    the standalone symbol-run scanner already evaluates such runs on their own conservative merits.
    """

    for start, end, run_text in _symbol_runs(token):
        if end - start < _SYMBOL_RUN_MIN:
            continue
        non_structural = [ch for ch in run_text if ch not in _STRUCTURAL_RUN_CHARS]
        if len(non_structural) < _NON_STRUCTURAL_MIN:
            return True
    return False


def _shape_reason(token: str) -> str | None:
    length = len(token)
    if length < _SHAPE_MIN_LENGTH or _is_exempt_identifier(token):
        return None
    non_alnum = [ch for ch in token if not ch.isalnum()]
    if non_alnum and all(ch in _STRUCTURAL_RUN_CHARS for ch in non_alnum):
        return None
    if _has_dominant_structural_run(token):
        return None
    if len(non_alnum) / length > _HIGH_SYMBOL_RATIO_THRESHOLD:
        return "high_symbol_ratio"
    letters = sum(1 for ch in token if ch.isalpha())
    if letters and (letters / length) < _LOW_LETTER_RATIO_THRESHOLD:
        return "low_letter_ratio"
    return None


def _letter_digit_alternation_count(token: str) -> int:
    """Count alternations between a letter-run and a digit-run, ignoring symbol-only breaks.

    Two consecutive runs of the *same* class never count — e.g. a hyphenated German compound word
    split into several letter-only segments (``Bau-Sach-Verstaendigen``) has zero alternations and
    must never be treated as character confusion, no matter how many segments it has. Genuine
    confusion looks like ``1o2O3l`` — letters and digits actually mixing back and forth.

    Uses ``isdecimal()`` rather than ``isdigit()`` for the "digit" class: ``isdigit()`` also
    returns ``True`` for superscript/subscript numerals (e.g. ``²``/``³`` in ``m²``/``m³`` unit
    suffixes, very common in German technical/expert-report measurements), which would otherwise
    over-flag a plain measurement like ``15,5m²``.
    """

    run_classes: list[str] = []
    previous_class: str | None = None
    for ch in token:
        if ch.isalpha():
            current_class = "letter"
        elif ch.isdecimal():
            current_class = "digit"
        else:
            previous_class = None
            continue
        if current_class != previous_class:
            run_classes.append(current_class)
        previous_class = current_class
    return sum(1 for a, b in pairwise(run_classes) if a != b)


def _confusion_reason(token: str) -> str | None:
    if _is_exempt_identifier(token):
        return None
    length = len(token)
    has_digit = any(ch.isdecimal() for ch in token)
    letters_used = {ch for ch in token if ch.isalpha()}
    if has_digit and letters_used and length >= _CONFUSION_MIN_LENGTH:
        if letters_used <= _O_ZERO_LETTERS:
            return "o_zero_confusion"
        if letters_used <= _I_L_ONE_LETTERS:
            return "i_l_one_confusion"
    if has_digit and length <= _RN_M_MAX_LENGTH and "rn" in token.lower():
        return "rn_m_confusion"
    if _letter_digit_alternation_count(token) >= _MIXED_ALNUM_ALTERNATION_MIN:
        return "mixed_alnum_confusion"
    return None


def _joined_word_reason(token: str) -> str | None:
    """A long, letters-only token with exactly one internal lower->upper transition.

    E.g. ``invoiceTotal`` — a conservative shape signal for two words an OCR pass may have joined
    without a space. Requires both sides of the transition to look like real word-length fragments,
    and skips filenames/IDs (which contain digits or separators) automatically.
    """

    if len(token) < _JOINED_TOKEN_MIN_LENGTH or not token.isalpha():
        return None
    transitions = [
        index
        for index in range(1, len(token))
        if token[index - 1].islower() and token[index].isupper()
    ]
    if len(transitions) != 1:
        return None
    split_at = transitions[0]
    if split_at < _JOINED_SEGMENT_MIN_LENGTH or len(token) - split_at < _JOINED_SEGMENT_MIN_LENGTH:
        return None
    return "suspicious_joined_token"


def _spacing_runs(page_text: str) -> list[tuple[int, int, int]]:
    """Maximal runs of consecutive single-letter tokens on the same line.

    A run of 2+ single-character alphabetic tokens in a row is a strong shape signal that spacing
    was broken (a word recognized letter by letter). Symbol/digit single-char tokens (bullets,
    section-reference numbers) never count, and a line break always ends a run.
    """

    matches = list(_TOKEN_RE.finditer(page_text))
    runs: list[tuple[int, int, int]] = []
    run_start: int | None = None

    def close_run(end_index: int) -> None:
        nonlocal run_start
        if run_start is not None:
            count = end_index - run_start
            if count >= _SPACING_RUN_MIN:
                runs.append((matches[run_start].start(), matches[end_index - 1].end(), count))
        run_start = None

    for index, match in enumerate(matches):
        token = match.group()
        is_single_letter = len(token) == 1 and token.isalpha()
        same_line_as_previous = (
            index == 0 or "\n" not in page_text[matches[index - 1].end():match.start()]
        )
        if is_single_letter and same_line_as_previous:
            if run_start is None:
                run_start = index
        elif is_single_letter:
            close_run(index)
            run_start = index
        else:
            close_run(index)
    close_run(len(matches))
    return runs


def _merge_spans(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _noise_summary_item(text: str, items: Sequence[QualityEvidenceItem]) -> QualityEvidenceItem:
    if not text.strip():
        return QualityEvidenceItem(
            evidence_id="noise-summary",
            level="document",
            type="ocr_noise_summary",
            status="not_applicable",
            reason_code="ocr_noise_summary_not_applicable",
        )
    if not items:
        return QualityEvidenceItem(
            evidence_id="noise-summary",
            level="document",
            type="ocr_noise_summary",
            status="confident",
            reason_code="ocr_noise_summary_clean",
            confidence=0.0,
            details={"total_suspicious_spans": 0},
        )

    reason_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    zone_counts: dict[str, int] = {}
    covered: list[tuple[int, int]] = []
    for item in items:
        reason_counts[item.reason_code] = reason_counts.get(item.reason_code, 0) + 1
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
        zone_key = item.page_zone or "unknown"
        zone_counts[zone_key] = zone_counts.get(zone_key, 0) + 1
        if item.raw_text_range is not None:
            covered.append((item.raw_text_range.start, item.raw_text_range.end))

    non_whitespace = sum(1 for ch in text if not ch.isspace())
    covered_chars = sum(end - start for start, end in _merge_spans(covered))
    density = min(1.0, round(covered_chars / non_whitespace, 6)) if non_whitespace else 0.0
    strongest_reason = max(reason_counts.items(), key=lambda pair: pair[1])[0]

    details: dict[str, int] = {"total_suspicious_spans": len(items)}
    details.update({f"reason_{code}": count for code, count in sorted(reason_counts.items())})
    details.update({f"status_{status}": count for status, count in sorted(status_counts.items())})
    details.update({f"zone_{zone}": count for zone, count in sorted(zone_counts.items())})

    return QualityEvidenceItem(
        evidence_id="noise-summary",
        level="document",
        type="ocr_noise_summary",
        status="partial",
        reason_code="ocr_noise_summary_flagged",
        confidence=density,
        details=details,
        flags=sorted({"ocr_noise", strongest_reason}),
    )
