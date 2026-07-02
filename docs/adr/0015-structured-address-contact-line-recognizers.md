# ADR-0015: Structured address & contact-line recognizers

## Status

Accepted — 2026-07-02

## Context

After Engine-5 the private benchmark's largest remaining *unsupported* recall gaps are the
line-level ground-truth labels `ADDRESS` (21 candidates), `CONTACT_LINE` (4), and `CUSTOMER_LINE`
(1): no recognizer produced these types, so every occurrence counted as a false negative in the
`other_types` bucket and the labels appeared under "unsupported entity types" in every report.

The ground-truth candidates for these labels are deterministic in shape: AT/DE street lines
(street word + house number, optional `PLZ Ort` tail) and single lines directly following a
contact/customer label (`Kontakt:`, `Ansprechpartner:`, `Kunde:` …).

## Decision

Add three deterministic Presidio pattern recognizers to the existing `insurance-at-de` pack
(`pii_recognizers.py`) — no new dependency, no NER, no architecture change:

- **`ADDRESS`** matches directly only on the unambiguous street shape: a compound street word
  (`…straße/strasse/gasse/platz/weg/allee` — a bare suffix word alone cannot match) or a
  case-sensitive two-word street (`Linzer Straße`), followed by a house number with optional
  stair/door parts and an optional `, PLZ Ort` tail. A unit lookahead rejects distance phrases
  (`Anfahrtsweg 12 km`). A labelled fallback (`Adresse:`/`Anschrift:` …) captures one line that
  must contain a digit.
- **`CONTACT_LINE`** and **`CUSTOMER_LINE`** are label-gated line captures: the label must sit
  immediately before the value (on the same line or on its own line directly above), the span is only the
  value line (never the label), and the captured line must pass a content-shape check
  (contact signal such as honorific/title/phone/e-mail for `CONTACT_LINE`; at least two letters
  for `CUSTOMER_LINE`). A label followed by unrelated text never blindly marks a section.

The three types form a new `ADDRESS_CONTACT_TYPES` profile group, enabled in `insurance-at-de`,
`broad-review`, and `review-heavy`; `structured-only` stays unchanged. In candidate validation
they are deliberate pass-throughs ("light" types): their recognizers are already structure- or
label-gated, matching the existing posture for label-gated domain identifiers. The benchmark
maps them into a new `address_contact_types` group.

## Consequences

- The three labels leave the benchmark's unsupported list; `other_types` false negatives shrink
  without touching NER, OCR, review, or redaction behaviour.
- Detected entities may overlap structured spans inside the same line (a `CONTACT_LINE` can
  contain a `PHONE_NUMBER`); engine-level overlap resolution remains Engine-6 work.
- The conservative shapes deliberately miss exotic street names without a labelled line and
  contact lines without a recognisable label — recall on these labels is bounded by design.
- Remaining unsupported labels (`BIRTH_DATE`, `BIRTH_PLACE`, `FAMILY_NAME`, `GIVEN_NAME`) are out
  of scope here.
