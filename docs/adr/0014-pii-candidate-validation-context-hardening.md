# ADR-0014: PII candidate validation — document-layout context hardening

## Status

Accepted — 2026-07-01

## Context

Manual UI review of Engine-5 candidate validation ([ADR-0013](0013-pii-candidate-validation.md))
surfaced a class of false positives/negatives that pure token-level lexical rules cannot fix,
because they depend on *where* a candidate sits on the page, not just its own text:

- A number run directly after a street name (e.g. `Obere Beispielstraße 18/10/44`) shape-matches
  `DATE_TIME` and was kept — it is a house/stair/door number, never a date.
- A 4-digit number directly before an Austrian city name (e.g. `1010 Wien`) is a postal code, not
  a bare year, but was only ever scored down as `DATE_YEAR_ONLY` with no distinguishing reason.
- An `ORGANIZATION` candidate immediately followed by a legal company-form suffix on the same line
  (e.g. `Qi Garden` before `e.U.`) was scored down as `ORG_WITHOUT_ORG_SIGNAL`, because the
  suffix — the actual signal — sits in the candidate's *context*, not its own text.
- Academic/professional titles (`MSc`, `Dr.`, `Mag.`, `DI`, …) and contact-role labels
  (`Ansprechpartner`, `Geschäftsführung`, …) support a nearby `PERSON` candidate but were only
  partially recognised (a narrow, undifferentiated context-signal list).
- The top-of-document header/address block (sender, contact, address, postal code, document
  title) is the single densest concentration of true-positive `PERSON`/`ORGANIZATION`/`LOCATION`
  candidates in an insurance/legal document, yet candidate validation treated every line
  identically regardless of position.

Candidate validation is not only token-level. It must account for document-layout context such as
address headers, company suffixes, contact labels, postal-code lines, and street-number patterns.

## Decision

- Extend `pii_validation_rules.py` with layout-aware predicates, still dependency-free and still
  operating only on the candidate's own text plus the existing 60-character context window (no
  new data source, no logging of raw context):
  - `has_address_line_context` — combined with a `looks_like_a_house_number` shape guard
    (`\d{1,4}(?:/\d{1,4}){1,2}`), suppresses a house/stair/door-number run on a line carrying
    street vocabulary (`Straße`, `Gasse`, `Platz`, `Weg`, `Adresse`, `Hausnummer`, `Stiege`,
    `Tür`, `Top`, `Allee`, `Ring`, and the compound word-ending forms `-straße`/`-gasse`/`-platz`/
    `-weg`). The shape guard keeps a genuine dot-formatted date on the same line as a street
    mention from being swept up by this rule.
  - `has_postal_code_context` — a 4-digit candidate at the *start* of its own line, immediately
    followed (only whitespace in between) by a small AT city list or the general
    `^\d{4}\s+[\p{L}]` shape, is a postal code, not a bare year.
  - `has_company_suffix_context` — an `ORGANIZATION` candidate immediately followed (only
    whitespace in between) by a company-form suffix is kept. Anchored to the very next token, not
    the whole line, so an unrelated company mentioned later in the same sentence cannot leak onto
    an earlier candidate (caught by a regression test:
    `Rechnung von Muster GmbH` must still drop `Rechnung`, not keep it via `Muster GmbH`'s suffix).
  - `has_person_title_context` / `has_contact_label_context` — split out of the single, narrower
    "name context" signal list into two dedicated lists (academic/professional titles;
    contact/responsible-person labels), each recorded with its own reason code. The original
    honorific list (`Herr`/`Frau`/`geboren`/`geb.`) is unchanged and still records no reason, so
    existing behaviour there is bit-for-bit stable.
  - `is_in_header_block` — true when a candidate sits in the first ~30 lines of a *multi-line*
    document, ending early at a document-title line (`Angebot`/`Rechnung`/`Gutachten`/`Vertrag`).
    A single-line text has no header/body distinction to make and is never treated as a header
    block, which keeps every existing single-line unit/integration test byte-for-bit unaffected.
- `validate_candidate` gains an `in_header_block: bool = False` parameter (default preserves every
  existing call site's behaviour); `validate_candidates` computes it per candidate from the exact
  local page text and the candidate's own offset — no new field is added to any artifact.
- Six new reason codes: `ADDRESS_LINE_NUMERIC_CONTEXT`, `POSTAL_CODE_CONTEXT`,
  `COMPANY_SUFFIX_CONTEXT`, `PERSON_TITLE_CONTEXT`, `CONTACT_PERSON_CONTEXT`,
  `HEADER_BLOCK_CONTEXT`. The first two suppress (`SCORE_DOWN`) a `DATE_TIME` candidate; the next
  two are recorded on a `KEEP` decision at the pure-function level for auditability, but — like
  every other `KEEP` reason — are not persisted onto the artifact, preserving ADR-0013's existing
  invariant (`validation_reasons` stays empty unless `validation_status` is `score_down`);
  `HEADER_BLOCK_CONTEXT` turns what would otherwise be a hard `DROP` (`GENERIC_DOCUMENT_WORD`) for
  an `ORGANIZATION`/`LOCATION` candidate in the header block into a `SCORE_DOWN`, so a borderline
  header-block candidate is downgraded rather than unconditionally destroyed.
- No new entity type, no new recognizer, no UI change, no new dependency. This is a refinement of
  the same subtractive post-processing filter described in ADR-0013, not a new detection
  mechanism.

## Consequences

- `DATE_TIME` false positives from address/postal-code lines are suppressed with a distinguishing
  reason instead of a generic shape/year reason, or (previously) not suppressed at all.
- `ORGANIZATION`/`PERSON` true positives common in document headers (company name plus legal
  suffix, contact person after a role label, name plus academic title) are kept instead of scored
  down, without loosening any of the existing lexical rules.
- All existing Engine-5 unit and integration tests remain green unchanged; the new layout rules
  are purely additive and gated so that short, single-line synthetic texts (the shape of most
  existing tests) fall back to prior behaviour exactly.
- Deliberately not solved here: a full address/postal-code *recognizer* (still open, per
  [`pii-engine-levels.md`](../engine/pii-engine-levels.md) Level 2); an exhaustive AT/DE
  city/title gazetteer (the lists stay small and general, consistent with ADR-0013); per-profile
  validation aggressiveness configuration (unchanged — aggressiveness is still purely a function
  of which entity types a profile enables).
