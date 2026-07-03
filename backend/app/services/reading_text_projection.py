"""Conservative offset-only reading lineage and raw-PII projection."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise

from app.schemas import PiiEntity, ReadingTextMapSegment, TextPageResult

_TOKEN_RE = re.compile(r"\S+")
_SYNTHETIC_HEADINGS = frozenset({"ANGEBOT", "LEISTUNGEN", "SUMMEN"})
_PHONE_FORMAT_RE = re.compile(r"^[+\d\s()./\-]+$")
_FORMAT_SEPARATOR_RE = r"[\s./:\-]*"
_ID_ENTITY_TYPES = frozenset(
    {
        "IBAN_CODE",
        "CREDIT_CARD",
        "UID_AT",
        "FN_AT",
        "SVNR_AT",
        "TAX_ID_AT",
        "ID_CARD_NUMBER",
        "LICENSE_PLATE_AT",
        "POLICY_NUMBER",
        "CLAIM_NUMBER",
        "CONTRACT_NUMBER",
        "OFFER_NUMBER",
        "INVOICE_NUMBER",
        "CUSTOMER_NUMBER",
        "TRANSACTION_ID",
        "CASE_NUMBER",
        "USER_ID",
    }
)


def build_reading_text_map(
    raw_text: str, reading_text: str, pages: Sequence[TextPageResult]
) -> list[ReadingTextMapSegment]:
    """Map only unambiguous source fragments; repeated fragments are never guessed."""
    if not raw_text or not reading_text:
        return []
    if raw_text == reading_text:
        return [
            ReadingTextMapSegment(
                reading_start=0,
                reading_end=len(reading_text),
                raw_start=0,
                raw_end=len(raw_text),
                page_number=_page_for_range(0, len(raw_text), pages),
                mapping_status="exact",
            )
        ]

    raw_tokens = _raw_token_spans(raw_text)
    reading_tokens = _reading_token_spans(reading_text)

    segments: list[ReadingTextMapSegment] = []
    for token, reading_spans in reading_tokens.items():
        raw_spans = raw_tokens.get(token, [])
        if len(reading_spans) != 1 or len(raw_spans) != 1:
            continue
        reading_start, reading_end = reading_spans[0]
        raw_start, raw_end = raw_spans[0]
        segments.append(
            ReadingTextMapSegment(
                reading_start=reading_start,
                reading_end=reading_end,
                raw_start=raw_start,
                raw_end=raw_end,
                page_number=_page_for_range(raw_start, raw_end, pages),
                mapping_status="exact",
            )
        )
    segments.sort(key=lambda segment: segment.reading_start)

    with_gaps: list[ReadingTextMapSegment] = []
    for segment in segments:
        if with_gaps:
            previous = with_gaps[-1]
            reading_gap = reading_text[previous.reading_end : segment.reading_start]
            raw_gap = (
                raw_text[previous.raw_end : segment.raw_start]
                if previous.raw_end <= segment.raw_start
                else ""
            )
            if reading_gap and raw_gap and reading_gap.isspace() and raw_gap.isspace():
                with_gaps.append(
                    ReadingTextMapSegment(
                        reading_start=previous.reading_end,
                        reading_end=segment.reading_start,
                        raw_start=previous.raw_end,
                        raw_end=segment.raw_start,
                        page_number=_page_for_range(previous.raw_end, segment.raw_start, pages),
                        mapping_status="normalized" if reading_gap != raw_gap else "exact",
                        flags=["whitespace_normalized"] if reading_gap != raw_gap else [],
                    )
                )
        with_gaps.append(segment)
    return with_gaps


def _raw_token_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for match in _TOKEN_RE.finditer(text):
        spans[match.group()].append(match.span())
    return spans


def _reading_token_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for match in _TOKEN_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line = text[line_start : len(text) if line_end < 0 else line_end].strip()
        if line not in _SYNTHETIC_HEADINGS:
            spans[match.group()].append(match.span())
    return spans


def project_pii_entities_to_reading_text(
    entities: Sequence[PiiEntity],
    segments: Sequence[ReadingTextMapSegment],
    *,
    reading_text: str | None = None,
) -> list[PiiEntity]:
    """Return copies with safe reading offsets; raw offsets and text remain untouched."""
    projected: list[PiiEntity] = []
    for entity in entities:
        map_projection = _project_entity(entity, segments)
        if map_projection.projection_status == "unmapped" and reading_text:
            projected.append(_project_entity_by_unique_text_match(entity, reading_text))
        else:
            projected.append(map_projection)
    return projected


def _project_entity(entity: PiiEntity, segments: Sequence[ReadingTextMapSegment]) -> PiiEntity:
    relevant = sorted(
        (
            segment
            for segment in segments
            if segment.raw_start < entity.end_offset
            and entity.start_offset < segment.raw_end
        ),
        key=lambda s: s.raw_start,
    )
    if not relevant:
        return entity.model_copy(update={"projection_status": "unmapped"})
    if any(segment.mapping_status == "partial" for segment in relevant):
        return entity.model_copy(update={"projection_status": "partial"})
    cursor = entity.start_offset
    for segment in relevant:
        if segment.raw_start > cursor:
            return entity.model_copy(update={"projection_status": "partial"})
        cursor = max(cursor, segment.raw_end)
    if cursor < entity.end_offset:
        return entity.model_copy(update={"projection_status": "partial"})

    reading_order = sorted(relevant, key=lambda s: s.reading_start)
    if any(
        left.reading_end != right.reading_start
        for left, right in pairwise(reading_order)
    ):
        return entity.model_copy(update={"projection_status": "partial"})
    start = _map_boundary(entity.start_offset, relevant[0], end=False)
    end = _map_boundary(entity.end_offset, relevant[-1], end=True)
    if start is None or end is None or end <= start:
        return entity.model_copy(update={"projection_status": "partial"})
    return entity.model_copy(
        update={
            "reading_start_offset": start,
            "reading_end_offset": end,
            "projection_status": "exact",
            "projection_method": "offset_map",
        }
    )


def _project_entity_by_unique_text_match(entity: PiiEntity, reading_text: str) -> PiiEntity:
    pattern = _fallback_pattern(entity)
    if pattern is None:
        return entity.model_copy(update={"projection_status": "unmapped"})
    matches = list(pattern.finditer(reading_text))
    if len(matches) != 1:
        return entity.model_copy(update={"projection_status": "unmapped"})
    match = matches[0]
    return entity.model_copy(
        update={
            "reading_start_offset": match.start(),
            "reading_end_offset": match.end(),
            "projection_status": "exact",
            "projection_method": "text_match",
        }
    )


def _fallback_pattern(entity: PiiEntity) -> re.Pattern[str] | None:
    if entity.entity_type == "PHONE_NUMBER":
        return _phone_pattern(entity.text)
    if entity.entity_type in _ID_ENTITY_TYPES:
        return _identifier_pattern(entity.text)
    return _whitespace_or_exact_pattern(entity.text)


def _phone_pattern(value: str) -> re.Pattern[str] | None:
    if not _PHONE_FORMAT_RE.fullmatch(value):
        return None
    normalized = "".join(
        character for character in value if character == "+" or character.isdigit()
    )
    if len([character for character in normalized if character.isdigit()]) < 7:
        return None
    body = _FORMAT_SEPARATOR_RE.join(re.escape(character) for character in normalized)
    return re.compile(rf"(?<!\d){body}(?!\d)")


def _identifier_pattern(value: str) -> re.Pattern[str] | None:
    normalized = "".join(character for character in value if character.isalnum())
    if len(normalized) < 5 or not any(character.isdigit() for character in normalized):
        return None
    body = _FORMAT_SEPARATOR_RE.join(re.escape(character) for character in normalized)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _whitespace_or_exact_pattern(value: str) -> re.Pattern[str] | None:
    chunks = value.split()
    if not chunks:
        return None
    body = r"\s+".join(re.escape(chunk) for chunk in chunks)
    prefix = r"(?<!\w)" if chunks[0][0].isalnum() else ""
    suffix = r"(?!\w)" if chunks[-1][-1].isalnum() else ""
    return re.compile(f"{prefix}{body}{suffix}")


def _map_boundary(offset: int, segment: ReadingTextMapSegment, *, end: bool) -> int | None:
    if offset == segment.raw_start:
        return segment.reading_start
    if offset == segment.raw_end:
        return segment.reading_end
    if segment.mapping_status == "exact" and (
        segment.raw_end - segment.raw_start == segment.reading_end - segment.reading_start
    ):
        return segment.reading_start + offset - segment.raw_start
    return None


def _page_for_range(start: int, end: int, pages: Sequence[TextPageResult]) -> int | None:
    base = 0
    for page in pages:
        page_end = base + len(page.text)
        if base <= start and end <= page_end:
            return page.page_number
        base = page_end + 2
    return None
