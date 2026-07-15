"""Named PII profiles and their stable entity-type groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PiiProfileName = Literal[
    "structured-only",
    "insurance-at-de",
    "broad-review",
    "review-heavy",
]

STRUCTURED_TYPES: tuple[str, ...] = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "URL",
)

REGIONAL_SENSITIVE_TYPES: tuple[str, ...] = (
    "UID_AT",
    "FN_AT",
    "SVNR_AT",
    "TAX_ID_AT",
    "BIC",
    "LICENSE_PLATE_AT",
    "PASSPORT_NUMBER",
    "ID_CARD_NUMBER",
)

DOMAIN_IDENTIFIER_TYPES: tuple[str, ...] = (
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
)

DOMAIN_SENSITIVE_TYPES: tuple[str, ...] = (
    *REGIONAL_SENSITIVE_TYPES,
    *DOMAIN_IDENTIFIER_TYPES,
)

# Deterministic line-level types (street-shape and labelled contact/customer lines); pattern
# recognizers, not NER — see docs/adr/0015-structured-address-contact-line-recognizers.md.
ADDRESS_CONTACT_TYPES: tuple[str, ...] = (
    "ADDRESS",
    "CONTACT_LINE",
    "CUSTOMER_LINE",
)

# Context-gated birth date/place: deterministic pattern recognizers that only fire on a date/place
# following an explicit birth label ("geboren am", "Geburtsort:"), so a plain invoice date or a
# residence city never over-tags. See docs/adr/0044-pii-birth-date-place-recognizers.md.
BIRTH_TYPES: tuple[str, ...] = (
    "BIRTH_DATE",
    "BIRTH_PLACE",
)

# LOCATION is deliberately NOT in any named profile. A bare city/location over-tags heavily
# (0 true positives / many false positives on the benchmark); residence location is already
# captured by ADDRESS and birthplace by a context-gated BIRTH_PLACE recognizer. It stays a known,
# validatable type (recognizer + candidate-validation rules exist) selectable only via an explicit
# custom PII_ENTITY_TYPES allowlist — see docs/engine/pii-detection-quality-plan.md.
NER_TYPES: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
)

LOWER_CONFIDENCE_NER_TYPES: tuple[str, ...] = ("DATE_TIME",)


@dataclass(frozen=True)
class PiiProfile:
    """A named, deterministic allowlist of recognizer entity types."""

    name: PiiProfileName
    entity_types: tuple[str, ...]


PII_PROFILES: dict[PiiProfileName, PiiProfile] = {
    "structured-only": PiiProfile("structured-only", STRUCTURED_TYPES),
    "insurance-at-de": PiiProfile(
        "insurance-at-de",
        (*STRUCTURED_TYPES, *DOMAIN_SENSITIVE_TYPES, *ADDRESS_CONTACT_TYPES, *BIRTH_TYPES),
    ),
    "broad-review": PiiProfile(
        "broad-review",
        (
            *STRUCTURED_TYPES,
            *DOMAIN_SENSITIVE_TYPES,
            *ADDRESS_CONTACT_TYPES,
            *NER_TYPES,
            *BIRTH_TYPES,
        ),
    ),
    "review-heavy": PiiProfile(
        "review-heavy",
        (
            *STRUCTURED_TYPES,
            *DOMAIN_SENSITIVE_TYPES,
            *ADDRESS_CONTACT_TYPES,
            *NER_TYPES,
            *LOWER_CONFIDENCE_NER_TYPES,
            *BIRTH_TYPES,
        ),
    ),
}

# Known/validatable types that are intentionally not part of any named profile but remain
# selectable via an explicit custom PII_ENTITY_TYPES allowlist (see NER_TYPES note re LOCATION).
SUPPORTED_ONLY_TYPES: tuple[str, ...] = ("LOCATION",)

SUPPORTED_PII_ENTITY_TYPES: frozenset[str] = frozenset(
    (
        *(
            entity_type
            for profile in PII_PROFILES.values()
            for entity_type in profile.entity_types
        ),
        *SUPPORTED_ONLY_TYPES,
    )
)


def get_pii_profile(name: PiiProfileName) -> PiiProfile:
    """Return one of the closed set of supported profiles."""
    return PII_PROFILES[name]
