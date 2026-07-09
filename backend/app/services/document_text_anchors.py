"""Text Anchor Graph v1 builder (ADR-0031 Phase B).

The anchor graph is an OCR/Text-owned identity layer derived from the OCR Output Contract v1
``DocumentTextPackageV1``. It creates stable, deterministic anchors over technical raw text first,
then attaches canonical reading-text ranges only through the existing offset-only
``reading_text_map``. Layout text is attached in v1 only when it is byte-aligned with raw text; any
other layout text remains a single-source view instead of being guessed into raw identity.

Anchor metadata is deliberately text-free. Token strings are used only transiently inside this
builder to classify spans and detect repeated-token ambiguity; they are never returned, logged, or
stored in the graph.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schemas import (
    DocumentTextAnchorGraphSummary,
    DocumentTextAnchorGraphV1,
    DocumentTextAnchorGraphValidation,
    DocumentTextAnchorKind,
    DocumentTextAnchorRange,
    DocumentTextAnchorRangeRole,
    DocumentTextAnchorSource,
    DocumentTextAnchorSourceName,
    DocumentTextAnchorStatus,
    DocumentTextAnchorV1,
    DocumentTextAnchorWarning,
    DocumentTextPackageV1,
    DocumentTextSourceV1,
    ReadingTextMapSegment,
)

_GRAPH_VERSION = "1.0"
_SOURCE_ORDER: tuple[DocumentTextAnchorSourceName, ...] = (
    "technical_raw_text",
    "canonical_reading_text",
    "layout_text",
)
_WARNING_ORDER: tuple[DocumentTextAnchorWarning, ...] = (
    "missing_raw_text",
    "missing_canonical_reading_text",
    "missing_layout_text",
    "missing_reading_text_map",
    "partial_lineage",
    "ambiguous_repeated_token",
    "unmapped_raw_tokens",
    "unmapped_canonical_tokens",
    "invalid_range",
    "overlapping_anchor_ranges",
    "unsupported_source",
)
_SOURCE_PRIORITY: dict[DocumentTextAnchorSourceName, int] = {
    source_name: index for index, source_name in enumerate(_SOURCE_ORDER)
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s()./\-]{5,}\d")
_IDENTIFIER_WITH_SEPARATOR_RE = re.compile(r"[A-Za-z0-9]+(?:[._:/\-][A-Za-z0-9]+)+")
_IDENTIFIER_ALNUM_RE = re.compile(r"(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{5,}")
_NUMBER_RE = re.compile(r"\d+(?:[.,:/\-]\d+)*")
_WORD_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
_SYMBOL_RE = re.compile(r"\S")
_TOKEN_PATTERNS: tuple[tuple[DocumentTextAnchorKind, re.Pattern[str]], ...] = (
    ("email", _EMAIL_RE),
    ("phone", _PHONE_RE),
    ("identifier", _IDENTIFIER_WITH_SEPARATOR_RE),
    ("identifier", _IDENTIFIER_ALNUM_RE),
    ("number", _NUMBER_RE),
    ("word", _WORD_RE),
    ("symbol", _SYMBOL_RE),
)


@dataclass(frozen=True)
class _TokenSpan:
    start: int
    end: int
    value: str
    kind: DocumentTextAnchorKind
    token_class: str
    normalized_shape: str


@dataclass(frozen=True)
class _CanonicalProjection:
    start: int
    end: int
    mapping_status: DocumentTextAnchorStatus
    range_role: DocumentTextAnchorRangeRole
    confidence: float


class TextAnchorLineageBuilder:
    """Build a deterministic text-free Text Anchor Graph v1 from a text package."""

    def build(self, package: DocumentTextPackageV1) -> DocumentTextAnchorGraphV1:
        raw_source = _source(package, "technical_raw_text")
        canonical_source = _source(package, "canonical_reading_text")
        layout_source = _source(package, "layout_text")

        raw_text = raw_source.text or ""
        canonical_text = canonical_source.text if canonical_source.available else None
        layout_text = layout_source.text if layout_source.available else None
        raw_tokens = _tokenize(raw_text)
        canonical_tokens = _tokenize(canonical_text or "")

        raw_value_counts = Counter(token.value for token in raw_tokens)
        canonical_value_counts = Counter(token.value for token in canonical_tokens)
        covered_canonical_ranges: list[tuple[int, int]] = []
        anchors: list[DocumentTextAnchorV1] = []
        unmapped_raw_token_count = 0
        repeated_token_ambiguity_count = 0

        raw_has_text = bool(raw_text.strip())
        canonical_available = canonical_text is not None
        layout_available = layout_text is not None
        layout_byte_aligned = layout_available and layout_text == raw_text and raw_has_text

        for token in raw_tokens:
            anchor, canonical_range = self._raw_anchor(
                package,
                token,
                package.reading_text_map,
                canonical_available=canonical_available,
                layout_byte_aligned=layout_byte_aligned,
                raw_value_count=raw_value_counts[token.value],
                canonical_value_count=canonical_value_counts[token.value],
            )
            if canonical_available and canonical_range is None:
                unmapped_raw_token_count += 1
            if "ambiguous_repeated_token" in anchor.warnings:
                repeated_token_ambiguity_count += 1
            if canonical_range is not None:
                covered_canonical_ranges.append((canonical_range.start, canonical_range.end))
            anchors.append(anchor)

        if canonical_available:
            anchors.extend(
                self._single_source_anchors(
                    package,
                    canonical_tokens,
                    source_name="canonical_reading_text",
                    source_status="inserted",
                    covered_ranges=covered_canonical_ranges,
                    flag="canonical_only",
                    warning="unmapped_canonical_tokens",
                )
            )

        if layout_available and not layout_byte_aligned:
            anchors.extend(
                self._single_source_anchors(
                    package,
                    _tokenize(layout_text or ""),
                    source_name="layout_text",
                    source_status="single_source",
                    covered_ranges=[],
                    flag="layout_only",
                    warning="unsupported_source",
                )
            )

        anchors.sort(key=_anchor_sort_key)
        source_lengths = _source_lengths(raw_source, canonical_source, layout_source)
        warnings, blockers = _diagnostics(
            raw_has_text=raw_has_text,
            canonical_available=canonical_available,
            layout_available=layout_available,
            reading_text_map=package.reading_text_map,
            unmapped_raw_token_count=unmapped_raw_token_count,
            unmapped_canonical_token_count=sum(
                _anchor_has_source(anchor, "canonical_reading_text")
                and not _anchor_has_source(anchor, "technical_raw_text")
                for anchor in anchors
            ),
            repeated_token_ambiguity_count=repeated_token_ambiguity_count,
            layout_unsupported=layout_available and not layout_byte_aligned,
            anchors=anchors,
            source_lengths=source_lengths,
        )
        validation = _validation(warnings, blockers, anchors, source_lengths)
        summary = _summary(
            anchors,
            unmapped_raw_token_count=unmapped_raw_token_count,
            unmapped_canonical_token_count=sum(
                _anchor_has_source(anchor, "canonical_reading_text")
                and not _anchor_has_source(anchor, "technical_raw_text")
                for anchor in anchors
            ),
            repeated_token_ambiguity_count=repeated_token_ambiguity_count,
        )
        sources = _sources(
            raw_source=raw_source,
            canonical_source=canonical_source,
            layout_source=layout_source,
            anchors=anchors,
        )

        return DocumentTextAnchorGraphV1(
            graph_version=_GRAPH_VERSION,
            document_id=package.document_id,
            text_artifact_id=package.text_artifact_id,
            source_artifact_id=package.text_artifact_id,
            package_id=package.package_id,
            package_contract_version=package.contract_version,
            created_at=package.created_at,
            sources=sources,
            anchors=anchors,
            summary=summary,
            validation=validation,
            warnings=list(warnings),
        )

    def _raw_anchor(
        self,
        package: DocumentTextPackageV1,
        token: _TokenSpan,
        reading_text_map: Sequence[ReadingTextMapSegment],
        *,
        canonical_available: bool,
        layout_byte_aligned: bool,
        raw_value_count: int,
        canonical_value_count: int,
    ) -> tuple[DocumentTextAnchorV1, DocumentTextAnchorRange | None]:
        source_ranges = [
            DocumentTextAnchorRange(
                source_name="technical_raw_text",
                start=token.start,
                end=token.end,
                range_role="primary",
                mapping_status="exact",
                confidence=1.0,
            )
        ]
        flags = ["raw_primary"]
        warnings: list[DocumentTextAnchorWarning] = []
        status: DocumentTextAnchorStatus = "single_source"
        confidence = 1.0

        canonical_range = None
        if canonical_available:
            projection = _project_raw_token(token, reading_text_map)
            if projection is not None:
                canonical_range = DocumentTextAnchorRange(
                    source_name="canonical_reading_text",
                    start=projection.start,
                    end=projection.end,
                    range_role=projection.range_role,
                    mapping_status=projection.mapping_status,
                    confidence=projection.confidence,
                )
                source_ranges.append(canonical_range)
                flags.append("canonical_mapped")
                status = projection.mapping_status
                confidence = projection.confidence
            elif canonical_value_count > 0 and (
                raw_value_count != 1 or canonical_value_count != 1
            ):
                status = "ambiguous"
                warnings.append("ambiguous_repeated_token")
                flags.append("canonical_ambiguous")
            else:
                status = "missing"
                flags.append("canonical_missing")

        if layout_byte_aligned:
            source_ranges.append(
                DocumentTextAnchorRange(
                    source_name="layout_text",
                    start=token.start,
                    end=token.end,
                    range_role="projected",
                    mapping_status="exact",
                    confidence=1.0,
                )
            )
            flags.append("layout_mapped")
            if status == "single_source":
                status = "exact"

        return (
            DocumentTextAnchorV1(
                anchor_id=_anchor_id(
                    package.document_id,
                    "technical_raw_text",
                    token.start,
                    token.end,
                    token.kind,
                ),
                anchor_kind=token.kind,
                anchor_status=status,
                source_ranges=source_ranges,
                page_number=_page_number(source_ranges),
                normalized_shape=token.normalized_shape,
                token_class=token.token_class,
                confidence=confidence,
                flags=flags,
                warnings=warnings,
            ),
            canonical_range,
        )

    def _single_source_anchors(
        self,
        package: DocumentTextPackageV1,
        tokens: Sequence[_TokenSpan],
        *,
        source_name: DocumentTextAnchorSourceName,
        source_status: DocumentTextAnchorStatus,
        covered_ranges: Sequence[tuple[int, int]],
        flag: str,
        warning: DocumentTextAnchorWarning,
    ) -> list[DocumentTextAnchorV1]:
        anchors: list[DocumentTextAnchorV1] = []
        for token in tokens:
            if _is_covered(token.start, token.end, covered_ranges):
                continue
            anchors.append(
                DocumentTextAnchorV1(
                    anchor_id=_anchor_id(
                        package.document_id, source_name, token.start, token.end, token.kind
                    ),
                    anchor_kind=token.kind,
                    anchor_status=source_status,
                    source_ranges=[
                        DocumentTextAnchorRange(
                            source_name=source_name,
                            start=token.start,
                            end=token.end,
                            range_role="derived",
                            mapping_status=source_status,
                            confidence=1.0,
                        )
                    ],
                    normalized_shape=token.normalized_shape,
                    token_class=token.token_class,
                    confidence=1.0,
                    flags=[flag],
                    warnings=[warning],
                )
            )
        return anchors


def build_document_text_anchor_graph(
    package: DocumentTextPackageV1,
) -> DocumentTextAnchorGraphV1:
    """Build Text Anchor Graph v1 for one Document Text Package."""
    return TextAnchorLineageBuilder().build(package)


def _source(package: DocumentTextPackageV1, name: str) -> DocumentTextSourceV1:
    return next(source for source in package.text_sources if source.name == name)


def _tokenize(text: str) -> list[_TokenSpan]:
    tokens: list[_TokenSpan] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        match = _match_token(text, index)
        if match is None:  # pragma: no cover - _SYMBOL_RE is a total fallback for non-whitespace
            index += 1
            continue
        kind, start, end = match
        value = text[start:end]
        tokens.append(
            _TokenSpan(
                start=start,
                end=end,
                value=value,
                kind=kind,
                token_class=_token_class(kind),
                normalized_shape=_normalized_shape(kind, value),
            )
        )
        index = end
    return tokens


def _match_token(text: str, index: int) -> tuple[DocumentTextAnchorKind, int, int] | None:
    for kind, pattern in _TOKEN_PATTERNS:
        match = pattern.match(text, index)
        if match is None:
            continue
        value = match.group()
        if kind == "phone" and not _is_phone_like(value):
            continue
        if kind == "identifier" and not _is_identifier_like(value):
            continue
        return kind, match.start(), match.end()
    return None


def _is_phone_like(value: str) -> bool:
    digit_count = sum(character.isdigit() for character in value)
    has_phone_separator = value.startswith("+") or any(
        character in value for character in " ()./-"
    )
    return digit_count >= 7 and has_phone_separator


def _is_identifier_like(value: str) -> bool:
    alnum = [character for character in value if character.isalnum()]
    return (
        len(alnum) >= 5
        and any(character.isalpha() for character in alnum)
        and any(character.isdigit() for character in alnum)
    )


def _token_class(kind: DocumentTextAnchorKind) -> str:
    return {
        "word": "alpha",
        "number": "digit",
        "email": "email_like",
        "phone": "phone_like",
        "identifier": "identifier_like",
        "symbol": "symbol",
    }[kind]


def _normalized_shape(kind: DocumentTextAnchorKind, value: str) -> str:
    if kind in ("email", "phone", "identifier"):
        return _token_class(kind)
    has_alpha = any(character.isalpha() for character in value)
    has_digit = any(character.isdigit() for character in value)
    has_symbol = any(not character.isalnum() and not character.isspace() for character in value)
    if has_alpha and not has_digit and not has_symbol:
        return "alpha"
    if has_digit and not has_alpha and not has_symbol:
        return "digit"
    if has_symbol and not has_alpha and not has_digit:
        return "symbol"
    return "mixed"


def _project_raw_token(
    token: _TokenSpan, segments: Sequence[ReadingTextMapSegment]
) -> _CanonicalProjection | None:
    relevant = sorted(
        (
            segment
            for segment in segments
            if segment.raw_start < token.end and token.start < segment.raw_end
        ),
        key=lambda segment: (segment.raw_start, segment.raw_end),
    )
    if not relevant:
        return None

    reading_start = min(segment.reading_start for segment in relevant)
    reading_end = max(segment.reading_end for segment in relevant)
    if reading_end <= reading_start:
        return None

    full_coverage = _segments_cover_range(token.start, token.end, relevant)
    if not full_coverage or any(segment.mapping_status == "partial" for segment in relevant):
        return _CanonicalProjection(
            start=reading_start,
            end=reading_end,
            mapping_status="partial",
            range_role="approximate",
            confidence=0.5,
        )

    if len(relevant) == 1:
        segment = relevant[0]
        if segment.mapping_status == "exact" and (
            segment.raw_end - segment.raw_start
            == segment.reading_end - segment.reading_start
        ):
            return _CanonicalProjection(
                start=segment.reading_start + token.start - segment.raw_start,
                end=segment.reading_start + token.end - segment.raw_start,
                mapping_status="exact",
                range_role="projected",
                confidence=1.0,
            )

    if all(segment.mapping_status == "exact" for segment in relevant) and (
        reading_end - reading_start == token.end - token.start
    ):
        return _CanonicalProjection(
            start=reading_start,
            end=reading_end,
            mapping_status="exact",
            range_role="projected",
            confidence=1.0,
        )
    return _CanonicalProjection(
        start=reading_start,
        end=reading_end,
        mapping_status="normalized",
        range_role="projected",
        confidence=0.9,
    )


def _segments_cover_range(
    start: int, end: int, segments: Sequence[ReadingTextMapSegment]
) -> bool:
    cursor = start
    for segment in segments:
        if segment.raw_start > cursor:
            return False
        if segment.raw_end > cursor:
            cursor = min(segment.raw_end, end)
        if cursor >= end:
            return True
    return cursor >= end


def _is_covered(start: int, end: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(range_start <= start and end <= range_end for range_start, range_end in ranges)


def _anchor_id(
    document_id: str,
    source_name: DocumentTextAnchorSourceName,
    start: int,
    end: int,
    kind: DocumentTextAnchorKind,
) -> str:
    digest_input = f"{document_id}\x00{source_name}\x00{start}\x00{end}\x00{kind}".encode()
    return hashlib.sha256(digest_input).hexdigest()[:32]


def _page_number(ranges: Sequence[DocumentTextAnchorRange]) -> int | None:
    # v1 package sources do not carry page segmentation. Keep the optional page field empty until a
    # future package/anchor version exposes page-safe token lineage.
    return None


def _diagnostics(
    *,
    raw_has_text: bool,
    canonical_available: bool,
    layout_available: bool,
    reading_text_map: Sequence[ReadingTextMapSegment],
    unmapped_raw_token_count: int,
    unmapped_canonical_token_count: int,
    repeated_token_ambiguity_count: int,
    layout_unsupported: bool,
    anchors: Sequence[DocumentTextAnchorV1],
    source_lengths: dict[DocumentTextAnchorSourceName, int],
) -> tuple[list[DocumentTextAnchorWarning], list[DocumentTextAnchorWarning]]:
    blockers = _blockers(raw_has_text, anchors, source_lengths)
    warnings = [
        *_availability_warnings(
            canonical_available, layout_available, reading_text_map
        ),
        *_lineage_warnings(
            unmapped_raw_token_count,
            unmapped_canonical_token_count,
            repeated_token_ambiguity_count,
        ),
        *_integrity_warnings(anchors, layout_unsupported),
    ]
    return _ordered_codes(warnings), _ordered_codes(blockers)


def _blockers(
    raw_has_text: bool,
    anchors: Sequence[DocumentTextAnchorV1],
    source_lengths: dict[DocumentTextAnchorSourceName, int],
) -> list[DocumentTextAnchorWarning]:
    blockers: list[DocumentTextAnchorWarning] = []
    if not raw_has_text:
        blockers.append("missing_raw_text")
    if _invalid_range_count(anchors, source_lengths):
        blockers.append("invalid_range")
    return blockers


def _availability_warnings(
    canonical_available: bool,
    layout_available: bool,
    reading_text_map: Sequence[ReadingTextMapSegment],
) -> list[DocumentTextAnchorWarning]:
    warnings: list[DocumentTextAnchorWarning] = []
    if not canonical_available:
        warnings.append("missing_canonical_reading_text")
    if not layout_available:
        warnings.append("missing_layout_text")
    if canonical_available and not reading_text_map:
        warnings.append("missing_reading_text_map")
    return warnings


def _lineage_warnings(
    unmapped_raw_token_count: int,
    unmapped_canonical_token_count: int,
    repeated_token_ambiguity_count: int,
) -> list[DocumentTextAnchorWarning]:
    warnings: list[DocumentTextAnchorWarning] = []
    if unmapped_raw_token_count or unmapped_canonical_token_count:
        warnings.append("partial_lineage")
    if repeated_token_ambiguity_count:
        warnings.append("ambiguous_repeated_token")
    if unmapped_raw_token_count:
        warnings.append("unmapped_raw_tokens")
    if unmapped_canonical_token_count:
        warnings.append("unmapped_canonical_tokens")
    return warnings


def _integrity_warnings(
    anchors: Sequence[DocumentTextAnchorV1], layout_unsupported: bool
) -> list[DocumentTextAnchorWarning]:
    warnings: list[DocumentTextAnchorWarning] = []
    if _overlap_count(anchors):
        warnings.append("overlapping_anchor_ranges")
    if layout_unsupported:
        warnings.append("unsupported_source")
    return warnings


def _validation(
    warnings: Sequence[DocumentTextAnchorWarning],
    blockers: Sequence[DocumentTextAnchorWarning],
    anchors: Sequence[DocumentTextAnchorV1],
    source_lengths: dict[DocumentTextAnchorSourceName, int],
) -> DocumentTextAnchorGraphValidation:
    status = "invalid" if blockers else "degraded" if warnings else "valid"
    return DocumentTextAnchorGraphValidation(
        status=status,
        warning_count=len(warnings),
        blocker_count=len(blockers),
        invalid_range_count=_invalid_range_count(anchors, source_lengths),
        overlapping_anchor_range_count=_overlap_count(anchors),
        warnings=list(warnings),
        blockers=list(blockers),
    )


def _summary(
    anchors: Sequence[DocumentTextAnchorV1],
    *,
    unmapped_raw_token_count: int,
    unmapped_canonical_token_count: int,
    repeated_token_ambiguity_count: int,
) -> DocumentTextAnchorGraphSummary:
    raw_count = sum(_anchor_has_source(anchor, "technical_raw_text") for anchor in anchors)
    canonical_count = sum(
        _anchor_has_source(anchor, "canonical_reading_text") for anchor in anchors
    )
    layout_count = sum(_anchor_has_source(anchor, "layout_text") for anchor in anchors)
    raw_with_canonical = sum(
        _anchor_has_source(anchor, "technical_raw_text")
        and _anchor_has_source(anchor, "canonical_reading_text")
        for anchor in anchors
    )
    raw_with_layout = sum(
        _anchor_has_source(anchor, "technical_raw_text")
        and _anchor_has_source(anchor, "layout_text")
        for anchor in anchors
    )
    raw_only = sum(
        _anchor_has_source(anchor, "technical_raw_text")
        and not _anchor_has_source(anchor, "canonical_reading_text")
        and not _anchor_has_source(anchor, "layout_text")
        for anchor in anchors
    )
    canonical_only = sum(
        _anchor_has_source(anchor, "canonical_reading_text")
        and not _anchor_has_source(anchor, "technical_raw_text")
        for anchor in anchors
    )
    ambiguous_count = sum(anchor.anchor_status == "ambiguous" for anchor in anchors)
    single_source_count = sum(anchor.anchor_status == "single_source" for anchor in anchors)
    return DocumentTextAnchorGraphSummary(
        total_anchors=len(anchors),
        anchors_with_raw_range=raw_count,
        anchors_with_canonical_range=canonical_count,
        anchors_with_layout_range=layout_count,
        raw_anchor_count=raw_count,
        canonical_anchor_count=canonical_count,
        layout_anchor_count=layout_count,
        anchors_with_raw_and_canonical=raw_with_canonical,
        anchors_with_raw_only=raw_only,
        anchors_with_canonical_only=canonical_only,
        anchors_with_layout=layout_count,
        exact_count=sum(anchor.anchor_status == "exact" for anchor in anchors),
        projected_count=sum(anchor.anchor_status == "projected" for anchor in anchors),
        partial_count=sum(anchor.anchor_status == "partial" for anchor in anchors),
        missing_count=sum(anchor.anchor_status == "missing" for anchor in anchors),
        ambiguous_count=ambiguous_count,
        single_source_count=single_source_count,
        ambiguous_anchor_count=ambiguous_count,
        single_source_anchor_count=single_source_count,
        unmapped_raw_token_count=unmapped_raw_token_count,
        unmapped_canonical_token_count=unmapped_canonical_token_count,
        canonical_unmapped_count=unmapped_canonical_token_count,
        layout_unmapped_count=raw_count - raw_with_layout,
        repeated_token_ambiguity_count=repeated_token_ambiguity_count,
        evidence_only_possible_count=sum(
            not _anchor_has_source(anchor, "technical_raw_text") for anchor in anchors
        ),
        raw_to_canonical_coverage_ratio=_ratio(raw_with_canonical, raw_count),
        raw_to_layout_coverage_ratio=_ratio(raw_with_layout, raw_count),
    )


def _sources(
    *,
    raw_source: DocumentTextSourceV1,
    canonical_source: DocumentTextSourceV1,
    layout_source: DocumentTextSourceV1,
    anchors: Sequence[DocumentTextAnchorV1],
) -> list[DocumentTextAnchorSource]:
    source_by_name = {
        "technical_raw_text": raw_source,
        "canonical_reading_text": canonical_source,
        "layout_text": layout_source,
    }
    result: list[DocumentTextAnchorSource] = []
    for source_name in _SOURCE_ORDER:
        source = source_by_name[source_name]
        result.append(
            DocumentTextAnchorSource(
                source_name=source_name,
                available=source.available,
                text_char_count=source.text_char_count,
                range_count=sum(
                    sum(
                        anchor_range.source_name == source_name
                        for anchor_range in anchor.source_ranges
                    )
                    for anchor in anchors
                ),
                mapped_anchor_count=sum(
                    _anchor_has_source(anchor, source_name) for anchor in anchors
                ),
            )
        )
    return result


def _source_lengths(
    *sources: DocumentTextSourceV1,
) -> dict[DocumentTextAnchorSourceName, int]:
    return {
        source.name: source.text_char_count or 0
        for source in sources
        if source.name in _SOURCE_ORDER
    }


def _anchor_has_source(anchor: DocumentTextAnchorV1, source_name: str) -> bool:
    return any(source_range.source_name == source_name for source_range in anchor.source_ranges)


def _invalid_range_count(
    anchors: Sequence[DocumentTextAnchorV1],
    source_lengths: dict[DocumentTextAnchorSourceName, int],
) -> int:
    count = 0
    for anchor in anchors:
        for source_range in anchor.source_ranges:
            if source_range.end > source_lengths.get(source_range.source_name, 0):
                count += 1
    return count


def _overlap_count(anchors: Sequence[DocumentTextAnchorV1]) -> int:
    count = 0
    for source_name in _SOURCE_ORDER:
        ranges = sorted(
            (
                source_range
                for anchor in anchors
                for source_range in anchor.source_ranges
                if source_range.source_name == source_name
            ),
            key=lambda source_range: (source_range.start, source_range.end),
        )
        previous_end = -1
        for source_range in ranges:
            if source_range.start < previous_end:
                count += 1
            previous_end = max(previous_end, source_range.end)
    return count


def _ordered_codes(
    codes: Iterable[DocumentTextAnchorWarning],
) -> list[DocumentTextAnchorWarning]:
    unique = set(codes)
    return [code for code in _WARNING_ORDER if code in unique]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _anchor_sort_key(
    anchor: DocumentTextAnchorV1,
) -> tuple[int, int, int, str]:
    first = min(
        anchor.source_ranges,
        key=lambda source_range: (
            _SOURCE_PRIORITY[source_range.source_name],
            source_range.start,
            source_range.end,
        ),
    )
    return (
        _SOURCE_PRIORITY[first.source_name],
        first.start,
        first.end,
        anchor.anchor_id,
    )
