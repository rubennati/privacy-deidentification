"""Heuristic text-layer quality assessment for a single extracted page.

The audit and OCR/Text stations previously treated *any* non-empty PDF text layer as usable.
Some PDFs ship a formally present but semantically broken/encoded text layer: many characters,
almost no letters, and mostly digits/symbols/control characters. Extracting that layer yields
garbage that pollutes downstream PII detection, while OCR on the same page produces usable text.

This module scores the *character/token plausibility* of extracted page text using robust,
dependency-free heuristics (no ML, no dictionary) and maps the score to a routing decision. It
deliberately does not judge layout/reading order — bad layout alone must not trigger OCR.

Design notes / conservatism (calibrated against the local corpus):
- The decisive signal for a broken/encoded layer is the near-total *absence of real words*: broken
  pages extract as thousands of digit/symbol tokens with ``letter_ratio ≈ 0`` and *no* word tokens.
  Legitimate documents — including number-heavy invoices/tables — always carry label words and keep
  ``letter_ratio`` well above the broken threshold (≥ ~0.64 for the most numeric real page).
- A high digit ratio alone must never mean "broken": a hard fail requires *almost no letters* (or
  no real words) together with symbol/digit dominance. Thresholds are conservative and unit-tested.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

TextQualityStatus = Literal[
    "GOOD_TEXT_LAYER",
    "LOW_CONFIDENCE_TEXT_LAYER",
    "BROKEN_TEXT_LAYER",
    "EMPTY_TEXT_LAYER",
]
RecommendedTextSource = Literal["text_layer", "ocr"]

GOOD_TEXT_LAYER: TextQualityStatus = "GOOD_TEXT_LAYER"
LOW_CONFIDENCE_TEXT_LAYER: TextQualityStatus = "LOW_CONFIDENCE_TEXT_LAYER"
BROKEN_TEXT_LAYER: TextQualityStatus = "BROKEN_TEXT_LAYER"
EMPTY_TEXT_LAYER: TextQualityStatus = "EMPTY_TEXT_LAYER"

# --- Tuning thresholds (conservative; covered by unit tests) --------------------------------
# Below this many non-whitespace characters a page has too little evidence to be called broken;
# it is treated as sparse (low confidence) instead so we never OCR a short-but-plausible page.
_MIN_CHARS_FOR_BROKEN = 50
# A page shorter than this (or with fewer words) is plausible but sparse: keep its text layer,
# but flag it as low confidence rather than good.
_SPARSE_MIN_CHARS = 45
_SPARSE_MIN_WORDS = 8
# Hard-fail character signals. Real documents (even dense number tables) keep letter_ratio far
# above these; the broken corpus pages extract at letter_ratio 0.00.
_LOW_LETTER_RATIO = 0.15
_MODERATE_LETTER_RATIO = 0.35
_HIGH_SYMBOL_DIGIT_RATIO = 0.50
_LOW_WORD_RATIO = 0.30
# Control/replacement/private-use characters are never legitimate body text in this corpus.
_CONTROL_RATIO_BROKEN = 0.10
_CONTROL_MIN_CHARS = 20
# Score band for GOOD.
_GOOD_MIN_SCORE = 80

_VOWELS = frozenset("aeiouyäöüàáâãèéêëìíîïòóôõùúû")
_NUMBER_CHARS = frozenset("0123456789.,:/- ")
_WORD_LETTER_RATIO = 0.7


@dataclass(frozen=True)
class TextQualityAssessment:
    """Immutable, routing-oriented verdict for one extracted page's text."""

    status: TextQualityStatus
    score: int
    recommended_text_source: RecommendedTextSource
    needs_ocr: bool
    reasons: list[str] = field(default_factory=list)


def assess_text_quality(text: str) -> TextQualityAssessment:
    """Classify one page's extracted text into a quality status and routing decision.

    Returns a stable, side-effect-free assessment. Only aggregate metrics drive the result; the
    input text itself is never stored by callers.
    """
    if not text.strip():
        return TextQualityAssessment(
            status=EMPTY_TEXT_LAYER,
            score=0,
            recommended_text_source="ocr",
            needs_ocr=True,
            reasons=["empty_text_layer"],
        )

    metrics = _metrics(text)
    score = _quality_score(metrics)
    reasons: list[str] = []

    if _detect_broken(metrics, reasons):
        return TextQualityAssessment(
            status=BROKEN_TEXT_LAYER,
            score=score,
            recommended_text_source="ocr",
            needs_ocr=True,
            reasons=reasons,
        )

    if len(text.strip()) < _SPARSE_MIN_CHARS or metrics.word_count < _SPARSE_MIN_WORDS:
        reasons.append("sparse_text")
        return TextQualityAssessment(
            status=LOW_CONFIDENCE_TEXT_LAYER,
            score=score,
            recommended_text_source="text_layer",
            needs_ocr=False,
            reasons=reasons,
        )

    if score >= _GOOD_MIN_SCORE:
        return TextQualityAssessment(
            status=GOOD_TEXT_LAYER,
            score=score,
            recommended_text_source="text_layer",
            needs_ocr=False,
            reasons=reasons,
        )

    reasons.append("mixed_quality_signals")
    return TextQualityAssessment(
        status=LOW_CONFIDENCE_TEXT_LAYER,
        score=score,
        recommended_text_source="text_layer",
        needs_ocr=False,
        reasons=reasons,
    )


@dataclass(frozen=True)
class _Metrics:
    non_whitespace: int
    word_count: int
    letter_ratio: float
    digit_ratio: float
    punctuation_ratio: float
    control_ratio: float
    word_ratio: float
    number_ratio: float


def _metrics(text: str) -> _Metrics:
    letters = digits = spaces = punctuation = control = 0
    for char in text:
        if char.isspace():
            spaces += 1
            continue
        category = unicodedata.category(char)
        if char.isalpha():
            letters += 1
        elif char.isdigit():
            digits += 1
        # Category C* covers control, format, surrogate, private-use, and unassigned code points.
        # U+FFFD (replacement) is category So, so add it explicitly.
        if category[0] == "C" or char == "�":
            control += 1
        elif category[0] in ("P", "S"):
            punctuation += 1

    tokens = text.split()
    word_count = len(tokens)
    words = numbers = 0
    for token in tokens:
        core = _strip_non_alphanumeric_boundaries(token)
        if _is_word_token(core):
            words += 1
        elif _is_number_like(core):
            numbers += 1

    non_whitespace = max(len(text) - spaces, 1)
    return _Metrics(
        non_whitespace=non_whitespace,
        word_count=word_count,
        letter_ratio=letters / non_whitespace,
        digit_ratio=digits / non_whitespace,
        punctuation_ratio=punctuation / non_whitespace,
        control_ratio=control / non_whitespace,
        word_ratio=words / word_count if word_count else 0.0,
        number_ratio=numbers / word_count if word_count else 0.0,
    )


def _detect_broken(metrics: _Metrics, reasons: list[str]) -> bool:
    """Append reason codes and return whether the page's text layer is broken/encoded."""
    broken = False

    if (
        metrics.control_ratio >= _CONTROL_RATIO_BROKEN
        and metrics.non_whitespace >= _CONTROL_MIN_CHARS
    ):
        reasons.append("high_control_char_ratio")
        broken = True

    if metrics.non_whitespace >= _MIN_CHARS_FOR_BROKEN:
        low_letter = metrics.letter_ratio < _LOW_LETTER_RATIO
        moderate_letter = metrics.letter_ratio < _MODERATE_LETTER_RATIO
        high_symbol_digit = (
            metrics.digit_ratio + metrics.punctuation_ratio
        ) > _HIGH_SYMBOL_DIGIT_RATIO
        few_words = metrics.word_ratio < _LOW_WORD_RATIO
        if low_letter:
            reasons.append("very_low_letter_ratio")
        if high_symbol_digit:
            reasons.append("high_symbol_or_digit_ratio")
        if few_words:
            reasons.append("few_word_tokens")
        # Broken/encoded-layer signature: symbol/digit dominated with either almost no letters at
        # all, or some letters but essentially no real words amid the noise. A number-heavy but
        # legitimate table keeps its label words, so its letter_ratio stays well above the bar.
        if high_symbol_digit and (low_letter or (moderate_letter and few_words)):
            broken = True

    return broken


def _quality_score(metrics: _Metrics) -> int:
    # Usable content = real words plus numbers, but numbers only count once *some* words are
    # present: a real table/invoice carries label words, whereas a wordless digit/symbol dump is
    # the broken-layer signature and must score ~0. Letters saturate at 0.5 so number-heavy but
    # legitimate pages are not penalized for their digits.
    letter_component = min(metrics.letter_ratio / 0.5, 1.0)
    number_credit = metrics.number_ratio if metrics.word_ratio >= 0.1 else 0.0
    usable = min(1.0, metrics.word_ratio + number_credit)
    quality = 0.5 * letter_component + 0.5 * usable
    quality -= min(metrics.control_ratio * 2.0, 0.5)
    quality = max(0.0, min(1.0, quality))
    return round(quality * 100)


def _is_word_token(core: str) -> bool:
    # Word-like: mostly letters (tolerating internal hyphens/apostrophes as in compound German
    # words) with at least one vowel. Random symbol/letter mixes fall below the letter ratio.
    if len(core) < 2:
        return False
    letters = sum(1 for char in core if char.isalpha())
    return (
        letters >= 2
        and letters / len(core) >= _WORD_LETTER_RATIO
        and any(char.lower() in _VOWELS for char in core)
    )


def _strip_non_alphanumeric_boundaries(token: str) -> str:
    start = 0
    end = len(token)
    while start < end and not token[start].isalnum():
        start += 1
    while end > start and not token[end - 1].isalnum():
        end -= 1
    return token[start:end]


def _is_number_like(core: str) -> bool:
    if not core or not core[0].isdigit():
        return False
    if any(char not in _NUMBER_CHARS for char in core):
        return False
    return any(char.isdigit() for char in core)
