# ADR-0026: OCR L15 is noise/token artifact evidence

## Status

Accepted — 2026-07-09. Builds on [ADR-0016](0016-engine-maturity-levels-0-19.md),
[ADR-0018](0018-ocr-pii-implementation-plan.md),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md),
[ADR-0022](0022-ocr-l12-multi-column-layout-reconstruction.md),
[ADR-0024](0024-ocr-l13-table-form-reconstruction-v2.md), and
[ADR-0025](0025-ocr-l14-quality-evidence-and-lineage-coverage.md), which re-scoped L12/L13/L14 the
same way this ADR re-scopes L15.

## Context

L14 made OCR/Text provenance, reconstruction, and lineage coverage measurable. It did not, however,
say anything about the *quality of the extracted characters themselves*: whether a span of text
looks like scanner/rendering garbage, a suspicious token shape, a plausible O/0, I/l/1, or rn/m
character confusion, or broken spacing (a word split into single letters, or two words joined
without a space). Today those questions can only be answered by eyeballing raw text, which does not
scale and cannot be captured as regression-safe evidence.

The older planning placeholder described OCR/Text L15 as "redaction-ready text/geometry mapping" — a
stable canonical-offset-to-pixel-box mapping for the [Redaction engine](../engine/redaction-engine-levels.md).
That capability is a materially larger, different-shaped step (word-level geometry, a redaction
consumer contract) with no immediate product signal ahead of PII L12/Review L8, while a bounded,
deterministic noise/token-artifact evidence layer is directly useful now: it tells us where future
dictionary, multi-OCR, or local-LLM evidence should focus, without requiring any of those heavier
capabilities first.

## Decision

- Re-scope OCR/Text L15 to **noise/token artifact evidence**, mirroring how ADR-0022/ADR-0024/
  ADR-0025 re-scoped L12/L13/L14. Redaction-ready geometry is deferred to a later level, to be
  re-scoped explicitly (as this ADR and its predecessors do) once redaction/review/PII prerequisites
  justify it.
- Add a dedicated, additive module (`backend/app/services/ocr_noise.py`) that scans **technical raw
  per-page text only** (never reading text, structured content, or any reconstruction) for
  deterministic shape-based signals and folds its output into the existing, additive
  `quality_evidence` list built by `ocr_quality.py` — no new artifact, no new schema version.
  `QualityEvidenceType` gains nine additive values: `glyph_artifact`, `suspicious_token_shape`,
  `suspicious_spacing`, `character_confusion`, `low_information_symbol_run`,
  `joined_word_candidate`, `split_word_candidate`, `non_text_artifact`, and `ocr_noise_summary`.
  `QualityEvidenceLevel` and `QualityEvidenceStatus` already covered every value L15 needs
  (`span`/`document`; `confident`/`partial`/`low_confidence`/`skipped`/`not_applicable`) — nothing
  new was added there.
- Signals are strictly deterministic and shape-based:
  - **Symbol/glyph runs**: a maximal run of non-alphanumeric characters is noise only once it
    contains at least a handful of characters outside a small, intentional divider/bullet/leader
    allowlist (`-+|_=.*~` and a few Unicode bullet marks) — one incidental character landing next to
    a genuine long divider or blank-field run must not disqualify the whole run from being
    structure.
  - **Suspicious token shape**: very low letter ratio or very high symbol ratio, computed only after
    excluding tokens that look like structured identifiers (letters/digits joined by `-_./:` into
    homogeneous segments — invoice/policy numbers, dates, filenames) or IBAN-shaped strings, and
    only after stripping trailing sentence punctuation (a comma/closing quote/bracket attached from
    context, never a load-bearing period) so a short abbreviation is judged on its own shape.
  - **Character confusion candidates**: O/0, I/l/1, and rn/m as narrow, digit-adjacent patterns
    (never firing on plain prose, since prose words carry no digits), plus a general
    letter-digit-*alternation* count (not a raw run count) for `mixed_alnum_confusion` — a token
    split into several same-class segments by symbols (e.g. a hyphenated compound word) has zero
    alternations and never counts, only genuine back-and-forth mixing does.
  - **Spacing candidates**: a run of 2+ consecutive single-letter tokens on the same line
    (`suspicious_spacing`, low confidence) escalating to `split_word_candidate` at 5+ (partial); a
    long, letters-only token with exactly one internal lower→upper transition and word-length
    fragments on both sides (`joined_word_candidate`).
  - **Page/zone aggregation**: noise items reuse the existing L14 page-zone classification
    (`ocr_quality._page_zone_map`) rather than inventing a second one; zones remain evidence only.
  - **Document summary**: one always-present `ocr_noise_summary` item per artifact (even when clean)
    with total/reason/status/zone counts, the strongest reason code, and a `noise_density_ratio`
    (merged-span character coverage over non-whitespace raw characters).
- **Evidence, not correction**: nothing is ever rewritten, removed, or reordered. No dictionary/
  lexicon, no spell-checking, no autocorrect, no second OCR engine, no local LLM, no learned
  classifier — all deferred, additive, later evidence sources per ADR-0025's precedent.
- **Privacy by construction**: every locator is an offset range, page number, page zone, count, or
  stable `reason_code`; `details` remains `dict[str, int]`. No raw token text, snippet, filename, or
  PII value is ever stored, matching the existing `QualityEvidenceItem` contract exactly (no schema
  change needed for privacy — L15 reuses the same fields L14 already defined).

## Private-corpus validation and false-positive hardening

A local, metrics-only validation pass (never committed; `.local/ocr-l15-noise-evidence/` outputs,
`.local/l15_validate.py`) against every private-corpus document a standard pypdf extraction could
open found real, generic (not corpus-specific) over-flagging risks before this reached an acceptable
state, diagnosed via a privacy-safe shape-signature tool (Unicode character *class* only — `L`/`D`/`S`
— never an actual character) so no raw private text was ever printed or persisted:

1. **Superscript/subscript digits** (`²`/`³` in `m²`/`m³` measurement units, common in German
   technical/expert reports) register `True` for `str.isdigit()` but are not real decimal digits;
   using `isdecimal()` for the confusion detector's digit class fixes this generically.
2. **A single incidental non-structural character** landing directly next to a long intentional
   divider/blank-field run (e.g. a closing bracket right after a 120-character underscore signature
   line) disqualified the *entire* run from the structural exemption. Fixed by requiring a minimum
   count (3) of non-structural characters before a run counts as noise, and by applying the same
   check to the whole-token shape ratio (a short label glued, with no separating space, to a long
   blank-field run must not have that filler drag the token's ratio over threshold).
3. **`mixed_alnum_confusion` counted any run-count**, not genuine letter↔digit mixing — a hyphenated
   German compound word split by a non-ASCII dash character (which the ASCII-only structured-
   identifier exemption does not recognize) was flagged even though every segment was pure letters.
   Redefined to require actual letter↔digit *alternation*.
4. **Trailing sentence punctuation** (a comma right after a short abbreviation like `u.s.w.`) pushed
   a token's symbol ratio over threshold. Fixed by stripping trailing non-period punctuation before
   shape analysis.

After these four fixes, every text-layer document in the corpus classified `NOISE_EVIDENCE_USEFUL`
with `NO_REGRESSION` (`reading_text`/`structured_content`/lineage coverage compared byte-for-byte
against the existing L14 baseline) and no raw-text leak; one document has no source PDF (needs the
OCR runtime, `OCR_ENGINE_BOTTLENECK`) and one has a pre-existing, unrelated `pypdf`/`cryptography`
dependency gap on an encrypted file (`LINEAGE_BOTTLENECK`), both predating this change.

## Consequences

- Every new OCR/Text artifact carries additive noise/token-artifact evidence alongside its L14
  provenance/lineage evidence, answering "where does this look like OCR garbage" without ever
  claiming a correct replacement.
- The fixes above are general, non-corpus-specific corrections (superscript units, hyphenated
  compounds, abbreviation punctuation, incidental-character contamination near dividers) — no
  private-corpus value is hard-coded, and each is covered by a synthetic regression test.
- Redaction-ready geometry remains explicitly open and deferred, avoiding the placeholder-mixing
  risk ADR-0022/ADR-0024/ADR-0025 called out for L12/L13/L14.
- Future OCR capability work may add dictionary/lexicon evidence, correction *suggestions*,
  multi-OCR/source agreement, or feedback-driven improvement. These remain out of scope here, must
  stay additive evidence (never silent rewrites), and are expected to plug into the OCR Output
  Contract ([ADR-0027](0027-ocr-output-contract-v1-strategy.md)). Exact level numbering remains
  governed by [ADR-0016](0016-engine-maturity-levels-0-19.md) and future ADRs.

> Migration note: earlier planning placeholders described OCR/Text L15 as redaction-ready text/
> geometry mapping. That capability is deferred to a later level once redaction/review/PII
> prerequisites justify it. L15 now means the noise/token artifact evidence described here; this
> avoids mixing the older placeholder meaning with the active 0–19 engine level.
