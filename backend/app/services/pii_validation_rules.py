"""Deterministic lexical/shape signals for PII candidate validation (Engine-5).

Dependency-free: no spaCy/Presidio import here. Every list below is intentionally small and
domain-general (stopwords, generic document words, company-form/name/address signals) rather
than an exhaustive gazetteer — this is a lightweight plausibility filter over already-detected
candidates, not a new detection mechanism or a hard-coded name/city list. See
``docs/adr/0013-pii-candidate-validation.md``.
"""

from __future__ import annotations

import re

# Articles/pronouns whose *only* content, as a whole candidate, is never a name/org/location.
_ARTICLES_AND_PRONOUNS: frozenset[str] = frozenset(
    {"der", "die", "das", "ein", "eine", "einer", "eines"}
)

# Prepositions/conjunctions (German + English); same rationale as articles/pronouns above.
_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "und", "oder", "für", "mit", "von", "zu", "im", "in", "am", "an", "bei", "auf",
        "aus", "bis", "als", "um",
        "the", "and", "or", "for", "with", "from", "to", "of", "on", "at", "by",
    }
)

# Generic document vocabulary that recurs across insurance/legal paperwork. On its own, as the
# *entire* candidate, it is never a company name or a place — German capitalises all nouns, so
# capitalisation alone cannot distinguish "Rechnung" (the document word) from a real entity.
_GENERIC_DOCUMENT_WORDS: frozenset[str] = frozenset(
    {
        "rechnung", "angebot", "gutachten", "schaden", "versicherung", "vertrag", "kunde",
        "seite", "summe", "betrag", "netto", "brutto", "steuer", "datum", "betreff",
        "anlage", "position", "leistung",
    }
)

# Legal company-form suffixes. A candidate containing one of these is very likely a real
# organisation name, regardless of any other signal.
_COMPANY_FORM_SIGNALS: tuple[str, ...] = (
    "gmbh", "kg", "og", "ag", "e.u.", "eu", "gesmbh", "verein", "ltd", "llc",
)

# Same suffixes, but usable as a *nearby-context* (not just in-text) signal — "eu" is excluded
# here since it collides too easily with "EU" (European Union) mentions near an unrelated org
# candidate; "e.u." (Einzelunternehmen, with the dots) stays, since it is unambiguous.
_COMPANY_SUFFIX_CONTEXT_SIGNALS: tuple[str, ...] = tuple(
    signal for signal in _COMPANY_FORM_SIGNALS if signal != "eu"
)

# Honorifics/relationship words that indicate a nearby PERSON candidate is a real name. Kept
# deliberately small and distinct from the title/contact-label lists below, since one existing
# behaviour (a bare "Herr"/"Frau" context keeps a candidate with no recorded reason) must stay
# stable.
_NAME_CONTEXT_SIGNALS: tuple[str, ...] = ("herr", "frau", "geboren", "geb.")

# Academic/professional titles, before or after a name, that support a PERSON candidate.
_PERSON_TITLE_SIGNALS: tuple[str, ...] = (
    "mag.", "dr.", "di", "ing.", "msc", "bsc", "ba", "ma", "mba", "phd",
)

# Labels that introduce a contact/responsible person; the following name is very likely a real
# PERSON candidate.
_CONTACT_LABEL_SIGNALS: tuple[str, ...] = (
    "ansprechpartner", "kontaktperson", "geschäftsführung", "geschäftsführer",
    "geschäftsführerin", "bearbeiter", "sachbearbeiter", "kontakt",
)

# Street/place vocabulary plus a handful of major AT cities (deliberately not a full gazetteer:
# it only needs to catch the obvious cases, not resolve every place name).
_LOCATION_SIGNALS: tuple[str, ...] = (
    "straße", "strasse", "str.", "gasse", "platz", "weg", "adresse", "plz", "ort",
    "wien", "graz", "linz", "salzburg", "innsbruck", "klagenfurt", "st. pölten",
    "eisenstadt", "bregenz", "österreich",
)

# Address-line vocabulary for suppressing a house/stair/door-number run (e.g. "18/10/44") that
# would otherwise shape-match a DATE_TIME candidate. "straße"/"gasse"/"platz"/"weg" are also
# matched as *word endings* below, since German compounds them onto the street name itself
# (e.g. "Musterstraße" has no word boundary before "straße").
_ADDRESS_LINE_WORDS: tuple[str, ...] = (
    "adresse", "hausnummer", "stiege", "tür", "top", "allee", "ring", "str.",
)
_ADDRESS_LINE_SUFFIX_RE = re.compile(r"\b\w*(?:straße|strasse|gasse|platz|weg)\b", re.IGNORECASE)

# Small AT postal-code cities, deliberately not an exhaustive gazetteer (see module docstring).
_AT_POSTAL_CITIES: tuple[str, ...] = (
    "wien", "graz", "linz", "salzburg", "innsbruck", "klagenfurt", "st. pölten",
    "eisenstadt", "bregenz",
)
# "1010 Wien"-shaped line: a 4-digit code followed by a capitalised place name, anchored to the
# start of the candidate's own line (a postal code is never mid-sentence).
_POSTAL_CODE_LINE_RE = re.compile(r"^\d{4}\s+[^\W\d_]")

# Document-title words that mark the end of the top-of-document header/address block.
_HEADER_TITLE_WORDS: frozenset[str] = frozenset({"angebot", "rechnung", "gutachten", "vertrag"})
_HEADER_MAX_LINES = 30

# Business date roles that make a bare date/year meaningful. Birth date is one of several; this
# PR deliberately does not further classify "sensitive" vs. "informational" date roles.
_DATE_CONTEXT_SIGNALS: tuple[str, ...] = (
    "geburtsdatum", "geboren", "geb.", "schadendatum", "rechnungsdatum", "vertragsdatum",
    "ausstellungsdatum", "antragsdatum", "fälligkeitsdatum",
)

_BIC_CONTEXT_SIGNALS: tuple[str, ...] = ("bic", "swift", "bankverbindung", "bank", "iban", "konto")

# Context keyword sets for the "moderate" domain identifiers, mirroring each recognizer's own
# label list in ``pii_recognizers.py``. Duplicated here (rather than imported) so this module has
# no dependency on the recognizer pack and stays independently testable.
_MODERATE_TYPE_CONTEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "CASE_NUMBER": ("aktenzeichen", "geschäftszahl", "geschäftszeichen", "case"),
    "OFFER_NUMBER": ("angebotsnummer", "angebotsnr", "angebots-nr", "offerte", "offer"),
    "PROJECT_ID": ("projekt-id", "projektid", "projektnummer", "projekt", "project-id"),
    "USER_ID": ("benutzerkennung", "benutzer-id", "benutzerid", "user-id", "userid", "login"),
    "FILE_REFERENCE": (
        "aktenreferenz", "ablagereferenz", "referenz", "geschäftszahl", "file-reference",
    ),
    "REPORT_NUMBER": ("berichtsnummer", "berichtsnr", "berichts-nr", "report"),
    "ASSESSMENT_NUMBER": ("gutachtennummer", "gutachtennr", "gutachten-nr", "assessment"),
    "CUSTOMER_NUMBER": ("kundennummer", "kundennr", "kunden-nr", "kundenkonto", "customer"),
}

_YEAR_ONLY = re.compile(r"^\d{4}$")
_DATE_SHAPE = re.compile(r"\d.*[./-].*\d")
# House/stair/door-number run (e.g. "18/10/44", "12/3/7"): 2-3 slash-separated small numbers.
# Deliberately narrower than "any DATE_TIME shape sharing a line with a street word", so a real
# dot-formatted date on the same line as an address is not swept up by the address-line rule.
_HOUSE_NUMBER_SHAPE = re.compile(r"^\d{1,4}(?:/\d{1,4}){1,2}$")
_MONTH_NAMES: tuple[str, ...] = (
    "januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
    "oktober", "november", "dezember",
    "january", "february", "march", "june", "july", "october", "december",
)


def tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[\s/]+", text.strip()) if token]


def is_numeric_only(text: str) -> bool:
    stripped = re.sub(r"[.,\s-]", "", text)
    return bool(stripped) and stripped.isdigit()


def is_stopword(text: str) -> bool:
    return text.strip().lower() in _ARTICLES_AND_PRONOUNS


def is_function_word(text: str) -> bool:
    return text.strip().lower() in _FUNCTION_WORDS


def is_generic_document_word(text: str) -> bool:
    tokens = tokenize(text)
    return len(tokens) == 1 and tokens[0].lower() in _GENERIC_DOCUMENT_WORDS


def has_company_form_signal(text: str) -> bool:
    return _contains_any(text.lower(), _COMPANY_FORM_SIGNALS)


def has_company_suffix_context(text: str, context_before: str, context_after: str) -> bool:
    """True if the candidate itself, or a company-form suffix immediately following it (only
    whitespace in between, e.g. "Qi Garden" followed by "e.U."), marks it as an organisation
    name. Anchored to the very next token — not the whole line — so an unrelated company
    mentioned later in the same sentence cannot leak onto this candidate."""
    if has_company_form_signal(text):
        return True
    return _starts_with_signal(context_after.lstrip(), _COMPANY_SUFFIX_CONTEXT_SIGNALS)


def has_location_signal(text: str, context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {text} {context_after}".lower()
    return _contains_any(haystack, _LOCATION_SIGNALS)


def has_name_context(context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, _NAME_CONTEXT_SIGNALS)


def has_person_title_context(context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, _PERSON_TITLE_SIGNALS)


def has_contact_label_context(context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, _CONTACT_LABEL_SIGNALS)


def has_date_context(context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, _DATE_CONTEXT_SIGNALS)


def has_financial_context(context_before: str, context_after: str) -> bool:
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, _BIC_CONTEXT_SIGNALS)


def has_domain_label_context(entity_type: str, context_before: str, context_after: str) -> bool:
    """True if a known label for ``entity_type`` appears nearby, or the type has none defined."""
    signals = _MODERATE_TYPE_CONTEXT_SIGNALS.get(entity_type)
    if not signals:
        return True
    haystack = f"{context_before} {context_after}".lower()
    return _contains_any(haystack, signals)


def is_year_only(text: str) -> bool:
    return bool(_YEAR_ONLY.match(text.strip()))


def looks_like_a_house_number(text: str) -> bool:
    return bool(_HOUSE_NUMBER_SHAPE.match(text.strip()))


def has_address_line_context(text: str, context_before: str, context_after: str) -> bool:
    """True if ``text`` has a house/stair/door-number shape (e.g. "18/10/44") *and* the
    candidate's own line (not the whole 60-char window) carries street/address vocabulary — used
    to keep such a run from being read as a DATE_TIME. The shape check keeps a real dot-formatted
    date on the same line as an address mention from being swept up by this rule."""
    if not looks_like_a_house_number(text):
        return False
    line_before = context_before.rsplit("\n", 1)[-1]
    line_after = context_after.split("\n", 1)[0]
    haystack = f"{line_before} {line_after}"
    if _contains_any(haystack.lower(), _ADDRESS_LINE_WORDS):
        return True
    return bool(_ADDRESS_LINE_SUFFIX_RE.search(haystack))


def has_postal_code_context(text: str, context_before: str, context_after: str) -> bool:
    """True if a 4-digit candidate sits at the start of its line, directly followed (only
    whitespace in between) by a place name — the Austrian "PLZ Ort" shape (e.g. "1010 Wien"),
    never a bare year."""
    if not is_year_only(text):
        return False
    line_before = context_before.rsplit("\n", 1)[-1]
    if line_before.strip():
        return False
    line_after = context_after.split("\n", 1)[0]
    if _starts_with_signal(line_after.lstrip(), _AT_POSTAL_CITIES):
        return True
    return bool(_POSTAL_CODE_LINE_RE.match(f"{text.strip()}{line_after}"))


def is_in_header_block(local_text: str, start: int) -> bool:
    """True if ``start`` falls within the top-of-document header/address block: the first
    ``_HEADER_MAX_LINES`` lines of a multi-line document, ending early at a document-title line
    (e.g. a line that is just "Angebot"/"Rechnung"/"Gutachten"/"Vertrag"). A single-line text has
    no header/body distinction to make, so it is never considered a header block."""
    if "\n" not in local_text:
        return False
    prefix = local_text[:start]
    lines = prefix.split("\n")
    if len(lines) - 1 >= _HEADER_MAX_LINES:
        return False
    return not any(
        line.strip().lower().rstrip(":.") in _HEADER_TITLE_WORDS for line in lines[:-1]
    )


def looks_like_a_date(text: str) -> bool:
    lowered = text.lower()
    if any(month in lowered for month in _MONTH_NAMES):
        return True
    return bool(_DATE_SHAPE.search(text))


def has_name_shape(text: str) -> bool:
    """Two or more capitalised tokens — a plausible ``Vorname Nachname`` shape."""
    tokens = tokenize(text)
    if len(tokens) < 2:
        return False
    return all(re.match(r"^[A-ZÄÖÜ][a-zA-ZäöüßÄÖÜ.'-]*$", token) for token in tokens)


def _contains_any(haystack: str, signals: tuple[str, ...]) -> bool:
    return any(_contains_signal(haystack, signal) for signal in signals)


def _contains_signal(haystack: str, signal: str) -> bool:
    """Word-boundary match for alphanumeric signals; plain substring for punctuated ones
    (e.g. ``geb.``/``e.u.``), where a trailing ``\\b`` cannot match after the final dot."""
    if signal.isalnum():
        return re.search(rf"\b{re.escape(signal)}\b", haystack) is not None
    return signal in haystack


def _starts_with_signal(remainder: str, signals: tuple[str, ...]) -> bool:
    """True if ``remainder`` (already stripped of leading whitespace) starts with one of
    ``signals``, honouring a word boundary for alphanumeric signals so e.g. ``"kg"`` does not
    match inside an unrelated word like ``"Kganz"``."""
    lowered = remainder.lower()
    for signal in signals:
        if not lowered.startswith(signal):
            continue
        if not signal.isalnum():
            return True
        tail = lowered[len(signal) : len(signal) + 1]
        if not tail.isalnum():
            return True
    return False
