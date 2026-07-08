# ADR-0024: OCR L13 is table/form reconstruction v2

## Status

Accepted — 2026-07-08. Builds on [ADR-0016](0016-engine-maturity-levels-0-19.md),
[ADR-0018](0018-ocr-pii-implementation-plan.md), [ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md),
and [ADR-0022](0022-ocr-l12-multi-column-layout-reconstruction.md), which re-scoped L12 the same way
this ADR re-scopes L13.

## Context

L12 stabilized canonical reading order: confident multi-column prose, fused single-cell table
headers, and geometry-bound label/value pairs all render safely, while low-confidence layouts keep
their existing row order. A private-corpus stabilization pass on L12 (`fix(ocr): prevent
label-value rows from column splitting`) closed the last known regression risk before L12 shipped.

With reading order stable, the next quality gap is in table and form *reconstruction quality*
itself, not ordering:

- A table with no recognized header vocabulary (e.g. a generic 3-column list of dates, places, and
  names) still fell back to plain, unaligned rows — safe, but less readable than it could be given
  the same geometric evidence L12 already uses for keyword-header tables.
- A table header fused across exactly *one* text fragment already reconstructed (L12); a header
  fused across *two* fragments did not, purely because the header-detection code path only accepted
  one or three-or-more cells.
- Adjacent-row label/value pairing (a label alone on its row, its value on the next) stopped after
  exactly one following row, so a value wrapping across more than one line (e.g. a multiline
  address) rendered as a broken label followed by an unattached continuation line.

The older planning placeholder described OCR/Text L13 as "document understanding" — document
type/section/zone classification. That is a materially different, larger capability (a
classification model, not a reconstruction heuristic) with no immediate product or benchmark signal
justifying it yet, while the table/form reconstruction gap above is bounded, evidence-driven, and
directly continues L11/L12's existing heuristics.

## Decision

- Re-scope OCR/Text L13 to **table/form reconstruction v2**, mirroring how ADR-0022 re-scoped L12.
- Keep the implementation inside the existing `reading_text` and `structured_content` layers:
  `reading_text_version` and `structured_content_version` both remain `"1"`; no new artifact or
  schema is introduced.
- Extend, not replace, L12's primitives:
  - a shared row-alignment helper backs both the existing keyword-header table renderer and a new
    geometry-only table detector, so a maximal run of 3+ consecutive rows sharing 3+ aligned columns
    renders row-wise even with no recognized header vocabulary, gated by the same
    party-heading/label-value-form ownership checks L12 already uses to keep prose and forms out of
    table detection;
  - a 1- or 2-cell fused table header is recovered by concatenating cell text and reusing the
    existing marker-based header split, generalizing what previously only worked for a single fused
    cell — column positions still come only from following-row evidence, never invented;
  - adjacent-row label/value pairing extends across further following rows that stay in the same
    column, at normal line spacing, and do not themselves look like a new label, heading, bullet,
    data row, filename row, or another inline `Label: value` fact;
  - `structured_content` field detection gains the equivalent multiline continuation for both the
    inline (`Label: value`) and next-line (`Label` then `value` below it) shapes, bounded by the
    same kind of stop conditions and a hard line cap.
- Add non-sensitive flags only: `generic_table_reconstruction` and `multiline_value_pairing` on
  `reading_text_flags`; `multiline_value` on `StructuredField.flags`. Both are additive; legacy
  artifacts without them remain valid.
- Do not add private-corpus-specific rules. Validate against the local private corpus, fix any
  generic regression found, and add a synthetic regression test for it — but do not force a new
  capability to fire on a document that does not clearly warrant it.
- Preserve all boundaries from ADR-0019: technical raw `text_result.text` and `pages[].text` remain
  byte-stable, PII still runs only on technical raw text, and no pseudonymization, redaction,
  reconstruction/export, or review-decision behavior is added.
- Defer document-type/section/zone classification (the older L13 placeholder) to a later level, to
  be re-scoped explicitly (as this ADR and ADR-0022 do) once a concrete product or benchmark need
  justifies it.

## Validation

A local private-corpus validation pass (never committed; see
[`ocr-pii-implementation-plan.md`](../engine/ocr-pii-implementation-plan.md)) compared
`reading_text` output before and after this change across every corpus document a standard pypdf
extraction could open (one encrypted document could not be opened locally — a pre-existing,
unrelated `pypdf`/`cryptography` dependency gap, not part of this change). The pass found one real
regression risk: an unrelated inline `Label: value` fact directly following a paired value, in the
same column, was being absorbed as a value continuation instead of staying its own fact. The fix
adds an explicit stop condition reusing the same "starts a new label/value fact" check already used
elsewhere in `reading_text.py`, with a synthetic regression test. After the fix, every validated
corpus document produced byte-identical `reading_text` output before and after this change — the
new geometry-only table and multiline-continuation paths did not additionally fire elsewhere in
that corpus. This is the expected stability-first outcome: the capabilities are tested and available
for future documents matching those patterns without needing to prove themselves on the current
corpus.

## Consequences

- Canonical Reading Text and `structured_content` improve for tables without header keywords,
  headers fused across two fragments, and multiline label/value forms, without a new dependency,
  artifact, or public API.
- `structured_content` remains the L11 span-backed structure layer; L13 makes both it and the
  display text more complete but does not redefine spans or switch PII input.
- A pre-existing, unrelated gap remains open: a page whose positioned-row extraction fails the
  existing raw-coverage safety check still falls back to plain raw order, and no version of table
  reconstruction (v1 or v2) can apply there. This is an L10/L12 row-geometry-collection limitation on
  some dense/complex table pages, not a table/form-reconstruction-logic gap, and is left for a future
  OCR/Text level rather than addressed here.
- Document-type/section/zone classification remains explicitly open and deferred, avoiding the same
  placeholder-mixing risk ADR-0022 called out for L12.

> Migration note: earlier planning placeholders described OCR/Text L13 as document understanding.
> That capability is deferred to a later level once a concrete need justifies it. L13 now means the
> table/form reconstruction v2 described here; this avoids mixing the older placeholder meaning with
> the active 0–19 engine level.
