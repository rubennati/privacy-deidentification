"""Presidio pattern specifications for the AT/DE insurance and legal domain pack.

The specifications are dependency-free so the normal test suite stays model-free. The adapter
materializes them as Presidio ``PatternRecognizer`` instances only when the optional PII runtime is
first used.

Matching policy (which types may match a value without an adjacent label):

- Match directly (format-strong, low ambiguity): ``PHONE_NUMBER`` (``+43``/``+49``/``0…`` shapes),
  ``UID_AT`` (``ATU`` + 8 digits), ``FN_AT`` (``FN`` + digits + check letter), ``BIC``,
  ``IBAN_CODE`` (``AT``/``DE`` + fixed length), ``URL`` (scheme/``www`` or a bare domain that is
  not part of an e-mail address). Each strong domain-identifier prefix (``POL-…``, ``SCH-…``,
  ``AKT-…`` …) also matches directly because the prefix + separator structure is unambiguous.
- Require an immediately adjacent, tested label (``\\bLABEL<sep>``) so a nearby word cannot boost an
  unrelated number: ``SVNR_AT``, ``TAX_ID_AT``, ``CREDIT_CARD``, ``LICENSE_PLATE_AT``,
  ``PASSPORT_NUMBER``, ``ID_CARD_NUMBER`` and the *generic* value form of every domain identifier
  (``POLICY_NUMBER`` … ``USER_ID``). The match span is only the value, never the label.

Format-strong direct matches can still be false positives on look-alike values; no candidate
validation runs here — that is deliberately left to the Engine-5 follow-up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PatternSpec:
    """One Presidio regex pattern and its base confidence."""

    name: str
    regex: str
    score: float


@dataclass(frozen=True)
class RecognizerSpec:
    """Dependency-free inputs for one Presidio PatternRecognizer."""

    name: str
    entity_type: str
    patterns: tuple[PatternSpec, ...]
    context: tuple[str, ...] = ()


class _PatternFactory(Protocol):
    def __call__(self, *, name: str, regex: str, score: float) -> object: ...


class _PatternRecognizerFactory(Protocol):
    def __call__(
        self,
        *,
        supported_entity: str,
        name: str,
        patterns: list[object],
        context: list[str],
        supported_language: str,
    ) -> object: ...


class PresidioPatternApi(Protocol):
    Pattern: _PatternFactory
    PatternRecognizer: _PatternRecognizerFactory


class RecognizerRegistry(Protocol):
    def add_recognizer(self, recognizer: object) -> None: ...


_GENERIC_CONTEXTUAL_ID = r"(?i)(?<![\w])(?=[a-z0-9._/@-]*\d)[a-z0-9][a-z0-9._/@/-]{2,39}(?![\w])"
_CONTEXT_SEPARATORS = (": ", ":", ".: ", "- ", " ")


def _contextual_patterns(
    name: str,
    value_regex: str,
    labels: tuple[str, ...],
    score: float = 0.65,
) -> tuple[PatternSpec, ...]:
    """Match only the value following a fixed label, without including that label in the span."""
    value_body = value_regex.removeprefix("(?i)")
    return tuple(
        PatternSpec(
            name=f"{name}_label_{label_index}_{separator_index}",
            regex=(
                rf"(?i)(?<=\b{re.escape(label)}{re.escape(separator)}){value_body}"
            ),
            score=score,
        )
        for label_index, label in enumerate(labels)
        for separator_index, separator in enumerate(_CONTEXT_SEPARATORS)
    )


def _domain_identifier(
    name: str,
    entity_type: str,
    strong_regex: str,
    context: tuple[str, ...],
) -> RecognizerSpec:
    return RecognizerSpec(
        name=name,
        entity_type=entity_type,
        patterns=(
            PatternSpec(f"{name}_strong", strong_regex, 0.7),
            *_contextual_patterns(name, _GENERIC_CONTEXTUAL_ID, context),
        ),
        context=context,
    )


INSURANCE_AT_DE_RECOGNIZER_SPECS: tuple[RecognizerSpec, ...] = (
    RecognizerSpec(
        name="AtDePhoneRecognizer",
        entity_type="PHONE_NUMBER",
        patterns=(
            PatternSpec(
                "at_de_phone_international",
                r"(?i)(?<![\w])(?:\+|00)(?:43|49)(?:[ ()/-]*\d){7,12}(?![\w])",
                0.75,
            ),
            PatternSpec(
                "at_de_phone_national",
                r"(?i)(?<![\w+])0(?:1|[2-9]\d{1,4})[ /()-]\d(?:[ /-]?\d){4,10}(?![\w])",
                0.6,
            ),
        ),
        context=("telefon", "tel", "mobil", "handy", "fax", "durchwahl"),
    ),
    RecognizerSpec(
        name="AustrianUidRecognizer",
        entity_type="UID_AT",
        patterns=(
            PatternSpec("austrian_uid", r"(?i)\bATU(?:[ -]?\d){8}\b", 0.8),
        ),
        context=("uid", "uidnummer", "umsatzsteuer", "vat"),
    ),
    RecognizerSpec(
        name="AustrianCompanyRegisterRecognizer",
        entity_type="FN_AT",
        patterns=(
            PatternSpec(
                "austrian_company_register",
                r"(?i)\bFN\s*:?[ ]*\d{1,6}[ ]*[a-z]\b",
                0.8,
            ),
        ),
        context=("firmenbuch", "firmenbuchnummer", "fn"),
    ),
    RecognizerSpec(
        name="AustrianSocialSecurityRecognizer",
        entity_type="SVNR_AT",
        patterns=_contextual_patterns(
            "austrian_social_security",
            r"(?<!\d)\d{4}[ -]\d{6}(?!\d)",
            (
                "svnr",
                "sv-nummer",
                "sv nummer",
                "sozialversicherungsnummer",
                "versicherungsnummer",
            ),
        ),
        context=(
            "svnr",
            "sv",
            "svnummer",
            "sozialversicherung",
            "sozialversicherungsnummer",
            "versicherungsnummer",
        ),
    ),
    RecognizerSpec(
        name="AustrianTaxIdRecognizer",
        entity_type="TAX_ID_AT",
        patterns=(
            *_contextual_patterns(
                "austrian_tax_id_separated",
                r"(?<!\d)\d{2,3}[ /-]\d{3,4}[ /-]\d{4}(?!\d)",
                ("steuernummer", "steuerkonto", "abgabenkonto", "finanzamtsnummer"),
            ),
            *_contextual_patterns(
                "austrian_tax_id_compact",
                r"(?<!\d)\d{9}(?!\d)",
                ("steuernummer", "steuerkonto", "abgabenkonto", "finanzamtsnummer"),
            ),
        ),
        context=(
            "steuernummer",
            "steuerkonto",
            "abgabenkonto",
            "finanzamtsnummer",
        ),
    ),
    RecognizerSpec(
        name="AtDeBicRecognizer",
        entity_type="BIC",
        patterns=(
            PatternSpec(
                "at_de_bic",
                r"(?i)\b[A-Z]{4}(?:AT|DE)[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b",
                0.7,
            ),
        ),
        context=("bic", "swift", "bankverbindung"),
    ),
    RecognizerSpec(
        name="AtDeIbanRecognizer",
        entity_type="IBAN_CODE",
        patterns=(
            PatternSpec("austrian_iban", r"(?i)\bAT(?:[ ]?\d){18}\b", 0.75),
            PatternSpec("german_iban", r"(?i)\bDE(?:[ ]?\d){20}\b", 0.75),
        ),
        context=("iban", "bankverbindung", "konto"),
    ),
    RecognizerSpec(
        name="ContextualCreditCardRecognizer",
        entity_type="CREDIT_CARD",
        patterns=_contextual_patterns(
            "contextual_credit_card",
            r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)",
            ("kreditkarte", "kartennummer", "kreditkartennummer", "creditcard"),
        ),
        context=("kreditkarte", "kartennummer", "creditcard"),
    ),
    RecognizerSpec(
        name="AtDeUrlRecognizer",
        entity_type="URL",
        patterns=(
            PatternSpec(
                "url_with_scheme_or_www",
                r"(?i)\b(?:https?://|www\.)[^\s<>()]+",
                0.75,
            ),
            PatternSpec(
                # The leading ``(?<![\w@.])`` excludes an e-mail's domain (``max@example.at``) and a
                # sub-label suffix from matching as a bare domain, so a detected e-mail is not also
                # double-counted as a URL. Genuine bare domains in running text still match.
                "at_de_bare_domain",
                r"(?i)(?<![\w@.])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:at|de|com|org|net|eu)\b(?:/[^\s<>()]*)?",
                0.65,
            ),
        ),
        context=("web", "website", "homepage", "url"),
    ),
    RecognizerSpec(
        name="AtDeLicensePlateRecognizer",
        entity_type="LICENSE_PLATE_AT",
        patterns=_contextual_patterns(
            "at_de_license_plate",
            r"(?i)\b[A-ZÄÖÜ]{1,3}(?:-| )[A-Z]{0,2}[ -]?\d{1,5}(?:[ -]?[A-Z])?\b",
            ("kennzeichen", "kfz-kennzeichen", "kfz kennzeichen", "amtliches kennzeichen"),
        ),
        context=("kennzeichen", "kfzkennzeichen", "amtliches", "fahrzeug"),
    ),
    RecognizerSpec(
        name="AtDePassportRecognizer",
        entity_type="PASSPORT_NUMBER",
        patterns=(
            *_contextual_patterns(
                "at_passport",
                r"(?i)\b[A-Z]\d{7,8}\b",
                ("reisepass", "passnummer", "pass-nr", "pass nr", "passport"),
            ),
            *_contextual_patterns(
                "de_passport",
                r"(?i)\b[CFGHJKLMNPRTVWXYZ0-9]{9}\b",
                ("reisepass", "passnummer", "pass-nr", "pass nr", "passport"),
            ),
        ),
        context=("reisepass", "passnummer", "passnr", "passport"),
    ),
    RecognizerSpec(
        name="AtDeIdCardRecognizer",
        entity_type="ID_CARD_NUMBER",
        patterns=(
            *_contextual_patterns(
                "at_id_card",
                r"(?i)\b[A-Z]{2}\d{7}\b",
                (
                    "personalausweis",
                    "ausweisnummer",
                    "ausweis-nr",
                    "ausweis nr",
                    "identitätskarte",
                ),
            ),
            *_contextual_patterns(
                "de_id_card",
                r"(?i)\b[CFGHJKLMNPRTVWXYZ0-9]{9}\b",
                (
                    "personalausweis",
                    "ausweisnummer",
                    "ausweis-nr",
                    "ausweis nr",
                    "identitätskarte",
                ),
            ),
        ),
        context=("personalausweis", "ausweisnummer", "ausweisnr", "identitätskarte"),
    ),
    _domain_identifier(
        "PolicyNumberRecognizer",
        "POLICY_NUMBER",
        r"(?i)\bPOL(?:[-/][A-Z0-9]+){2,5}\b",
        (
            "polizzennummer",
            "polizzennr",
            "polizzennr.",
            "polizzen-nr",
            "versicherungsschein",
            "policy",
        ),
    ),
    _domain_identifier(
        "ClaimNumberRecognizer",
        "CLAIM_NUMBER",
        r"(?i)\b(?:SCH|SB)(?:[-/][A-Z0-9]+){1,5}\b",
        ("schadennummer", "schadennr", "schadennr.", "schaden-nr", "claim"),
    ),
    _domain_identifier(
        "ContractNumberRecognizer",
        "CONTRACT_NUMBER",
        r"(?i)\b(?:VN|VER)(?:[-/][A-Z0-9]+){1,5}\b",
        ("vertragsnummer", "vertragsnr", "vertragsnr.", "vertrags-nr", "contract"),
    ),
    _domain_identifier(
        "CaseNumberRecognizer",
        "CASE_NUMBER",
        r"(?i)\b(?:AKT|AZ)(?:[-/][A-Z0-9]+){1,5}\b",
        ("aktenzeichen", "geschäftszahl", "geschäftszeichen", "case"),
    ),
    _domain_identifier(
        "FileReferenceRecognizer",
        "FILE_REFERENCE",
        r"(?i)\b(?:GZ|REF)(?:[-/][A-Z0-9]+){1,5}\b",
        ("aktenreferenz", "ablagereferenz", "referenz", "geschäftszahl", "file-reference"),
    ),
    _domain_identifier(
        "ReportNumberRecognizer",
        "REPORT_NUMBER",
        r"(?i)\b(?:BER|REP)(?:[-/][A-Z0-9]+){1,5}\b",
        ("berichtsnummer", "berichtsnr", "berichtsnr.", "berichts-nr", "report"),
    ),
    _domain_identifier(
        "AssessmentNumberRecognizer",
        "ASSESSMENT_NUMBER",
        r"(?i)\bGUT(?:[-/][A-Z0-9]+){1,5}\b",
        ("gutachtennummer", "gutachtennr", "gutachtennr.", "gutachten-nr", "assessment"),
    ),
    _domain_identifier(
        "InvoiceNumberRecognizer",
        "INVOICE_NUMBER",
        r"(?i)\b(?:RE|RG)(?:[-/][A-Z0-9]+){1,5}\b",
        ("rechnungsnummer", "rechnungsnr", "rechnungsnr.", "rechnungs-nr", "invoice"),
    ),
    _domain_identifier(
        # Only the separator-structured ``ANG-…`` form matches without a label; a bare ``AN`` +
        # digits run is indistinguishable from ordinary German prose ("an" + a number) and is
        # therefore left to the label-gated contextual pattern, consistent with every other
        # generic domain identifier below.
        "OfferNumberRecognizer",
        "OFFER_NUMBER",
        r"(?i)\bANG(?:[-/][A-Z0-9]+){1,5}\b",
        ("angebotsnummer", "angebotsnr", "angebotsnr.", "angebots-nr", "offerte", "offer"),
    ),
    _domain_identifier(
        "CustomerNumberRecognizer",
        "CUSTOMER_NUMBER",
        r"(?i)\b(?:KD|KDN)(?:[-/][A-Z0-9]+){1,5}\b",
        ("kundennummer", "kundennr", "kundennr.", "kunden-nr", "kundenkonto", "customer"),
    ),
    _domain_identifier(
        "ProjectIdRecognizer",
        "PROJECT_ID",
        r"(?i)\b(?:PRJ|PROJ)(?:[-/][A-Z0-9]+){1,5}\b",
        ("projekt-id", "projektid", "projektnummer", "projekt", "project-id"),
    ),
    _domain_identifier(
        "TransactionIdRecognizer",
        "TRANSACTION_ID",
        r"(?i)\b(?:TXN|TX)(?:[-/][A-Z0-9]+){1,5}\b",
        (
            "transaktions-id",
            "transaktionsid",
            "transaktionsnummer",
            "transaction-id",
        ),
    ),
    _domain_identifier(
        "UserIdRecognizer",
        "USER_ID",
        r"(?i)(?<![\w])(?:USR|USER)(?:[-/][A-Z0-9._@]+){1,5}(?![\w])",
        ("benutzerkennung", "benutzer-id", "benutzerid", "user-id", "userid", "login"),
    ),
)


def register_insurance_at_de_recognizers(
    registry: RecognizerRegistry,
    presidio: PresidioPatternApi,
    language: str,
) -> None:
    """Materialize and register the local pattern pack with Presidio."""
    for spec in INSURANCE_AT_DE_RECOGNIZER_SPECS:
        patterns = [
            presidio.Pattern(name=pattern.name, regex=pattern.regex, score=pattern.score)
            for pattern in spec.patterns
        ]
        registry.add_recognizer(
            presidio.PatternRecognizer(
                supported_entity=spec.entity_type,
                name=spec.name,
                patterns=patterns,
                context=list(spec.context),
                supported_language=language,
            )
        )
