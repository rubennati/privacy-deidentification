"""Conservative, deterministic PII entity grouping (PII L11).

Groups repeated occurrences of the same entity type and normalized value within one PII result
into stable entity groups, so a reviewer can decide once per group instead of once per occurrence.
This is a pure, derived view over ``PiiContent.entities`` — detection is unchanged, nothing here is
persisted inside the immutable ``pii_result`` artifact, and grouping never drops or invents an
occurrence.

Grouping is intentionally conservative (see docs/engine/pii-engine-levels.md#level-11 and the
review-entity-decisions task): only same-type, same-normalized-value matches are grouped. There is
no fuzzy name matching, no semantic identity resolution across entity types, and no proximity-based
grouping.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.schemas import PiiEntity, PiiEntityGroup, PiiEntityGroupProjectionSummary

# Structured identifiers that are safe to normalize by removing internal whitespace only; case and
# internal punctuation (e.g. dashes in a license plate or policy number) are left untouched since
# they may be semantically significant and stripping them could over-group distinct values.
_ID_LIKE_TYPES = frozenset(
    {
        "CREDIT_CARD",
        "IP_ADDRESS",
        "UID_AT",
        "FN_AT",
        "SVNR_AT",
        "TAX_ID_AT",
        "BIC",
        "LICENSE_PLATE_AT",
        "PASSPORT_NUMBER",
        "ID_CARD_NUMBER",
        "POLICY_NUMBER",
        "CLAIM_NUMBER",
        "CONTRACT_NUMBER",
        "CASE_NUMBER",
        "FILE_REFERENCE",
        "REPORT_NUMBER",
        "ASSESSMENT_NUMBER",
        "INVOICE_NUMBER",
        "OFFER_NUMBER",
        "CUSTOMER_NUMBER",
        "PROJECT_ID",
        "TRANSACTION_ID",
        "USER_ID",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_PHONE_KEEP_RE = re.compile(r"[^\d+]")


def _normalize_value(entity_type: str, text: str) -> str:
    """Return the conservative normalized form used for grouping one entity's value.

    Falls back to exact whitespace-normalized text for every type without a dedicated rule
    (organization/name/address/location/date/url/…): never fuzzy, never case-folded.
    """
    nfc = unicodedata.normalize("NFC", text).strip()
    if entity_type == "EMAIL_ADDRESS":
        return nfc.lower()
    if entity_type == "IBAN_CODE":
        return _WHITESPACE_RE.sub("", nfc).upper()
    if entity_type == "PHONE_NUMBER":
        return _PHONE_KEEP_RE.sub("", nfc)
    if entity_type in _ID_LIKE_TYPES:
        return _WHITESPACE_RE.sub("", nfc)
    return _WHITESPACE_RE.sub(" ", nfc)


def _fingerprint(entity_type: str, normalized_value: str) -> str:
    """A stable SHA-256 hex digest identifying one (type, normalized value) pair.

    Used both as the group's privacy-safe ``normalized_fingerprint`` and (truncated) as its
    ``entity_group_id`` — the raw normalized value itself is never stored.
    """
    digest_input = f"{entity_type}\x00{normalized_value}".encode()
    return hashlib.sha256(digest_input).hexdigest()


def group_pii_entities(entities: list[PiiEntity]) -> list[PiiEntityGroup]:
    """Group occurrences conservatively by entity type + normalized value fingerprint.

    Pure and deterministic: the same entities always produce the same groups and group ids.
    Different entity types never group together; matching is exact (post-normalization), never
    fuzzy or proximity-based.
    """
    order: list[str] = []
    occurrences_by_group: dict[str, list[PiiEntity]] = {}
    fingerprint_by_group: dict[str, str] = {}
    type_by_group: dict[str, str] = {}

    for entity in entities:
        normalized = _normalize_value(entity.entity_type, entity.text)
        fingerprint = _fingerprint(entity.entity_type, normalized)
        group_id = fingerprint[:32]
        if group_id not in occurrences_by_group:
            order.append(group_id)
            occurrences_by_group[group_id] = []
            fingerprint_by_group[group_id] = fingerprint
            type_by_group[group_id] = entity.entity_type
        occurrences_by_group[group_id].append(entity)

    groups = [
        PiiEntityGroup(
            entity_group_id=group_id,
            entity_type=type_by_group[group_id],
            occurrence_ids=[
                occurrence.id
                for occurrence in sorted(
                    occurrences_by_group[group_id],
                    key=lambda occurrence: (occurrence.start_offset, occurrence.end_offset),
                )
            ],
            occurrence_count=len(occurrences_by_group[group_id]),
            normalized_fingerprint=fingerprint_by_group[group_id],
            projection_summary=_projection_summary(occurrences_by_group[group_id]),
        )
        for group_id in order
    ]
    first_offset_by_group = {
        group_id: min(occurrence.start_offset for occurrence in occurrences)
        for group_id, occurrences in occurrences_by_group.items()
    }
    groups.sort(key=lambda group: first_offset_by_group[group.entity_group_id])
    return groups


def _projection_summary(occurrences: list[PiiEntity]) -> PiiEntityGroupProjectionSummary:
    exact = sum(1 for occurrence in occurrences if occurrence.projection_status == "exact")
    partial = sum(1 for occurrence in occurrences if occurrence.projection_status == "partial")
    unmapped = len(occurrences) - exact - partial
    return PiiEntityGroupProjectionSummary(
        exact_count=exact, partial_count=partial, unmapped_count=unmapped
    )
