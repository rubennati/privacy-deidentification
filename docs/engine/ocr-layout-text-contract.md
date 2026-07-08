# OCR / Layout Text Contract

The contract that fixes the OCR/Text output model **before** any layout implementation begins. It
separates five text layers on purpose — **technical raw**, **canonical reading**, **PII-input**,
**readable**, and **layout** —
tied together by a single **lineage map**, so that a detection-optimised internal representation and
human-readable/layout-preserving renderings can evolve without ever endangering the offset stability
that PII and Review depend on, and without creating a second, unconnected source of truth.

This is the **contract document** for the OCR/Text multi-layer output model. It defines names,
invariants, and representation rules that implementation must satisfy; parts of the contract are
now delivered incrementally, while later geometry/lineage work remains open.

## Purpose

OCR/Text is the foundation for PII, Review, and later Redaction. If the extracted text loses its
structure — two-column blocks linearised, table headers separated from their values — detection
quality and review both degrade. We want, long term, not only a nice user-facing rendering but also
an internal, **PII-optimised** representation. This contract deliberately separates:

- **technical raw text** — legacy extraction, offset-stable, the current PII coordinate system;
- **canonical reading text** — deterministic, block-aware main document text for humans and future
  AI-ready placeholder workflows;
- **PII-input text** — an internal, detection-optimised representation (preserving logical blocks,
  roles, table rows, address blocks, page structure) — **not** optimised for visual beauty;
- **readable text** — a human-readable normalisation of the same content;
- **layout text** — a plain-text reconstruction of the document's visual structure (Review/UI);
- **lineage map** — the mapping that marries all of the above to the same source blocks/lines/words.

Keeping them separate — but **mapped** — means a nicer rendering or a smarter detection view can
never shift a canonical PII offset, and no layer becomes an island.

## Text layers

### 1. Technical raw text (legacy canonical coordinate text)

- **Field:** `text_result.text` (per-page `text_result.pages[].text`, joined with `\n\n`).
- **Historical name / synonym:** **`best_text_result`** or “canonical text.” Those names describe
  its compatibility/offset role; the UI and current product contract call it **Technical Raw Text /
  Technischer Rohtext** so a messy extraction is not presented as the canonical document reading.
- **Purpose:** preserve the extractor/OCR result as the byte-stable offset coordinate system for
  current PII/Review and old artifacts.
- **Invariant:** technical raw text is the coordinate system every other layer will map back to.
- **Rule:** it must **not** be changed by PII-input/readable/layout experiments. `best_text_result`
  is a deprecated ambiguous label, not a persisted-field rename.

### 2. Canonical reading text

- **Fields:** optional `reading_text_version = "1"`, `reading_text`, `reading_text_status`,
  `reading_text_flags`, and offset-only `reading_text_map_version`/`reading_text_map` on
  `text_result` (absent on older artifacts).
- **Purpose:** the cleaned, deterministic, block-aware main document text: sensible top-to-bottom
  order, intact party/address/account blocks, stable pipe-delimited line-item rows, major-block blank
  lines, and conservative prose joining without visual A4 spacing.
- **Derivation priority:** transient fine-grained positions feeding L10 geometry, persisted L10
  `text_geometry`, L9 `layout_blocks`, `layout_text_result`, then safe raw page order. Low-confidence
  input falls back rather than fabricating structure.
- **Metadata:** `reading_text_status` is `heuristic` or `fallback`; `reading_text_flags` records only
  non-sensitive strategy/coverage codes and never copied text.
- **UI:** User View defaults to **Kanonischer Lesetext** when present. Dev View can switch among
  **Kanonischer Lesetext**, **Technischer Rohtext**, and **Layout-Text**.
- **Review projection:** the conservative map covers only safely matched fragments. Existing raw
  PII entities may carry additive exact reading offsets. Otherwise-unmapped entities may fall back
  to one unique in-memory exact/whitespace/known-identifier format match in reading text; duplicate
  or absent values stay raw-only, and partial map projections remain partial. Segments contain
  offsets/status/flags, never copied text, and ambiguous repeats are not guessed.
- **Boundary:** this partial display map is **not** the active PII input and is not the complete
  round-trippable source/view lineage map. A future input switch still requires the full separation
  gate below.

### 3. PII-input text

- **New optional field/artifact:** `pii_input_text` (a.k.a. `pii_text_result`) — internal, not
  primarily user-visible.
- **Purpose:** improve **detection quality and context** by preserving logical blocks, roles, table
  rows, address blocks, and page structure better than a linearised string.
- **v1 (delivered, PDF text layer only):** a real, additive, experimental reconstruction — two-column
  blocks grouped left-block-fully-then-right-block-fully, and table rows reconstructed row-wise from
  a known header line. It is **not** an alias of technical raw text, but it is also **not the active
  PII detection input**: PII continues to run exclusively on `text_result.text`, unaffected by this field.
  `pii_input_text` is marked internal/experimental precisely because no lineage map exists yet — see
  the [separation gate](#invariants). Pages without a confident reconstruction (OCR pages, or
  uncertain fragment/column detection) fall back to `None`, mirroring `layout_text_result`.
- **Later:** becomes the **active** detection input only with a clean mapping/lineage (see the
  [lineage map](#5-lineage-map)) so every `pii_input_text` span resolves deterministically back to
  technical raw offsets — and only after the [separation gate](#invariants) is satisfied.
- **Must not:** be optimised for visual beauty, and must **never** become a second, unconnected
  source of truth. It is a detection **view** over raw extraction + source, not a rival original.

### 4. Readable text

- **New optional field/artifact:** `readable_text` (additive; absent on older artifacts).
- **Purpose:** a human-readable rendering of the same content.
- **May:** improve whitespace, join paragraphs, repair hyphenation, normalise line breaks.
- **Must not:** carry a PII-offset guarantee, and must **not** be used as a PII input.

### 5. Layout text

- **New optional field/artifact:** `layout_text_result` (additive; absent on older artifacts).
- **Purpose:** a plain-text reconstruction of the document's **visual structure** for Review/UI.
- **Covers:** pages, blocks, two-column areas, tables, header/footer, sum/total blocks.
- **Form:** monospaced, best-effort.
- **Must not:** carry a PII-offset guarantee.
- **UI:** may display it, but must be able to **fall back to technical raw text** (`text_result.text`)
  when it is absent (e.g. OCR-only or DOCX documents).

### 6. Lineage map

- **New optional field/artifact:** `text_lineage_map` (a.k.a. `layout_mapping`).
- **Purpose:** connect **source** (page → block → line → word) ↔ **canonical** ↔ **PII-input** ↔
  **reading** ↔ **readable** ↔ **layout**, so the layers are one married model, not islands.
- **Enables:** PII is detected internally on `pii_input_text`, its spans map to technical raw offsets,
  and raw offsets map to positions in `layout_text_result` — so a detection can be **visibly
  marked in the layout view** while its authoritative offsets stay canonical.
- **Long term:** the same map is the basis for **bounding boxes** and **redaction** (raw span →
  page geometry), aligning with OCR L10+ per-block lineage and redaction-ready geometry.
- **Must:** be deterministic and round-trippable (raw ↔ pii_input without loss) wherever
  `pii_input_text` diverges from canonical.

### L9 structured layout blocks

- **Fields:** optional `layout_blocks_version = "1"` plus `layout_blocks[]` on `text_result`.
- **Purpose:** expose deterministic layout reading order and conservative review-oriented types
  without changing the existing plain-text `layout_text_result` or UI.
- **Contents:** page number, page-local order, type, text, extraction source, optional natural OCR
  confidence, and coarse normalized 0..1 page bounds.
- **Boundary:** bounds are block regions used for ordering/typing only. They are not canonical
  offsets, reusable line/word geometry, a canonical-offset→box lookup, or a `text_lineage_map`.
  Line-level canonical-span geometry (source anchoring/traceability) is the separate L10 field below.

### L10 span geometry

- **Fields:** optional `text_geometry_version = "1"` plus `text_geometry` on `text_result`.
- **Purpose:** provide the first raw-offset-bearing geometry — resolve a technical raw line span to
  one or more page-local line boxes — for source anchoring, review/debug, and traceability, and as a
  foundation for future placeholder mapping toward AI-ready pseudonymized document generation.
- **Contents:** per page, a `coordinate_unit` (`pdf_points` for text-layer, `image_pixels` for OCR),
  `page_width`/`page_height`, extraction `source`, a `status` (`complete`/`partial`/`unsupported`),
  and `lines[]`. Each line maps `canonical_start`/`canonical_end` (into `text`) and
  `page_start`/`page_end` (into `pages[].text`) to page-local `x0/y0/x1/y1` bounds, with optional OCR
  confidence. The geometry also carries overall `coverage` and `flags`. It stores **no** raw line
  text.
- **Derivation:** offsets are obtained by matching page-local text segments against the immutable
  raw page text — the technical raw text is never regenerated or altered. Pages without safely
  derivable geometry degrade to `partial`/`unsupported` rather than guessing; DOCX has no geometry.
- **Boundary:** line-level source anchoring only. It does not perform pseudonymization, placeholder
  mapping, document export, or pixel-perfect visual redaction; word-level geometry and a general
  `text_lineage_map` remain L11+ work. The internal `resolve_span_geometry` helper is the
  canonical-span→box lookup; it never returns raw text.

### L11 structured content

- **Fields:** optional `structured_content_version = "1"` plus `structured_content` on
  `text_result`.
- **Purpose:** represent conservative tables/cells, label/value fields, and heading-bound sections
  without changing or replacing any text layer.
- **Offsets/privacy:** cells and values use canonical/page spans; raw table contents and field
  values are not duplicated. Short labels/headings may be stored inside the already-sensitive text
  artifact. Optional bounds reuse L10 line geometry.
- **Boundary:** this additive structure supports future context-preserving placeholder generation,
  but it is not the PII input, a `text_lineage_map`, pseudonymization, redaction, or export.

## Invariants

These hold for any future implementation:

- **Technical raw `text_result` remains stable** — `text`, `pages[].text`, and `text_char_count` are
  byte-identical to today; their existing validation rules remain enforced.
- **No disconnected truth.** `reading_text` is a deterministic derived view, not a second source
  artifact. Technical raw remains the sole offset authority until every other layer maps back to it
  (and to source) via `text_lineage_map`.
- **PII detection resolves to technical raw.** PII runs exclusively on `text_result.text` today —
  independent of whatever `pii_input_text` contains, including its populated v1 reconstruction. If
  `pii_input_text` is later made the active detection input, **every** result must map
  deterministically to technical raw offsets — no PII result may exist that cannot be expressed in
  raw coordinates.
- **PII highlights and authoritative offsets remain anchored to technical raw text.** Reading-mode
  marking uses only exact projected offsets; layout mode remains unhighlighted. No view is
  re-detected independently.
- **PII-input text and layout text must be married via lineage/mapping** — neither is a standalone
  island; both trace to the same source blocks/lines/words as canonical.
- **`reading_text`, `pii_input_text`, `readable_text`, `layout_text_result`, `layout_blocks`,
  `text_geometry`, `structured_content`, and `text_lineage_map` are additive** — new optional
  fields/artifacts.
- **No existing artifacts are rewritten** — a re-run creates a new artifact; nothing is mutated.
- **Legacy artifacts remain valid** — older artifacts without the new fields still validate.
- **Separation gate.** `pii_input_text` may become the **active PII detection input** only when a
  tested `text_lineage_map` exists, canonical↔pii_input offsets round-trip without loss, and the
  existing PII tests stay green. Until that gate is satisfied, PII detection uses technical raw text
  exclusively — regardless of whether `pii_input_text` itself is empty, an alias, or (as in v1) a
  populated but unmapped, experimental reconstruction.

## Representation rules for `layout_text_result` v1

- **Page boundaries** are made visible (an explicit separator between pages).
- **Page transitions** read legibly (a cross-page paragraph should not look truncated).
- **Title / header / footer** are best-effort marked or preserved (not silently merged into body
  text).
- **Two-column blocks** are best-effort placed side by side (e.g. Auftragnehmer / Auftraggeber).
- **Tables** render as monospaced plain text (a header row and its value row stay on aligned lines).
- **Column headers** are preserved.
- **Numeric / currency values** are right-aligned best-effort.
- **Address blocks** are preserved where possible.
- **Line wrapping** is stable enough for review (no gratuitous re-wrapping between runs).
- **OCR-only pages** may fall back to linear text in v1, with a marker that layout was not
  reconstructed.
- **No perfect PDF rendering** is required — the goal is a robust, review-suitable reconstruction.

## Examples

Synthetic illustration only — **no real data**.

**PII-optimised internal structure** (`pii_input_text`) — logical blocks/roles preserved for
detection, not for looks:

```text
[PAGE 1]
[BLOCK: contractor]
Sanierungsbau Perchtoldsdorf GmbH
Lindenstraße 42
2380 Perchtoldsdorf, Österreich

[BLOCK: customer]
Herr Dipl.-Ing. Franz Hubermayr
Rosengasse 7/12
2340 Mödling, Österreich
```

**Visible layout structure** (`layout_text_result`) — the same content, arranged for a human:

```text
AUFTRAGNEHMER                                  AUFTRAGGEBER
Sanierungsbau Perchtoldsdorf GmbH              Herr Dipl.-Ing. Franz Hubermayr
Lindenstraße 42                                Rosengasse 7/12
2380 Perchtoldsdorf, Österreich                2340 Mödling, Österreich
```

Both views must be **traceable to the same source blocks/lines/words** via `text_lineage_map`, and
both resolve to the same canonical offsets. The canonical `text_result.text` for the document is
unchanged and may linearise the above; neither the internal nor the visible view is a rival source of
truth.

**v1 delivered reality vs. this illustration:** the *structural shape* above — a document read
block-by-block instead of X/Y-interleaved — is what v1 produces for a stable two-column PDF
text-layer page. Two differences from the illustration: v1 labels blocks **geometrically**
(`[BLOCK: left]` / `[BLOCK: right]`), not with semantic roles like `contractor`/`customer` — v1 has
no document-understanding step to justify that label; and a page marker (`[PAGE N]`) appears only
**between** pages, mirroring `layout_text_result`, not before page 1. `text_lineage_map` and
canonical-offset traceability for `pii_input_text` remain future work — v1 does not map its spans
back to canonical offsets, which is exactly why it is not yet the active PII detection input.

## Relationship to OCR levels

Anchored to the existing 0–19 ladder in [`ocr-engine-levels.md`](ocr-engine-levels.md), which stays
**authoritative** — this contract invents no new level numbers:

- **OCR L6:** OCR confidence.
- **OCR L7:** `quality_report`.
- **OCR L8:** human-readable text output — canonical vs readable split first realised
  (`best_text_result` stays canonical; `readable_text` is the readable rendering).
- **OCR L9:** `layout_text_result` plus ordered, typed `layout_blocks` with coarse normalized bounds.
- **OCR L10:** `text_geometry` line boxes mapping canonical line spans to page-local bounds, with a
  `resolve_span_geometry` canonical-span→box lookup — line-level source anchoring and traceability,
  and the structural basis for `text_lineage_map` and any real `pii_input_text` divergence.
- **OCR L10.5:** `reading_text` establishes the canonical reading-text / technical-raw contract and
  the product-facing main text before structured content.
- **OCR L11:** span-backed table / form reconstruction in additive `structured_content`.
- **OCR L12:** deterministic multi-column layout reconstruction in canonical `reading_text`; no new
  schema, artifact, raw-text, or PII-input change.
- **OCR L13:** table/form reconstruction v2 — geometry-only table detection (no header keyword
  required), partially fused header recovery, and multiline label/value continuation, in both
  canonical `reading_text` and `structured_content`; no new schema, artifact, raw-text, or PII-input
  change.
- **OCR L14:** quality evidence and lineage coverage — additive, optional, versioned
  `quality_evidence` on `text_result` recording metrics-only provenance, reconstruction, page-zone,
  and reading↔raw lineage-coverage evidence; no new artifact, raw-text, or PII-input change, and it
  never changes PII decisions.
- **Higher levels:** local AI assist / redaction-ready geometry (the lineage map's long-term payoff
  for bounding boxes and redaction).

`layout_text_result` v1, `pii_input_text` v1, and the structured layout blocks complete OCR L9 —
visible layout, internal experimental reading order, and review-oriented typed regions. A full
`text_lineage_map` (and `pii_input_text` becoming the active detection input) are **not** v1 — they
build on the
block/geometry structure from OCR L10 and gate on the separation rule above. See the sequence in
[`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md).

## Implementation status (v1)

- **Delivered:** `readable_text` as an **additive optional field on the existing `text_result`**
  (Option A; no separate artifact in v1). Produced for any non-empty technical raw text with a small,
  deterministic normalization pass: line-ending cleanup, trailing-space removal, conservative
  paragraph joining, simple line-break de-hyphenation, and visible page boundaries between
  raw pages. It never feeds PII and carries no offset guarantee.
- **Delivered:** `layout_text_result` as an **additive optional field on the existing `text_result`**
  (Option A — simpler and lower-risk than a separate artifact). Produced for **PDF text-layer pages**
  via pypdf's `extract_text(extraction_mode="layout")` (no new dependency). OCR pages are marked "not
  reconstructed" and fall back to their linear text; page boundaries are shown with a visible marker.
  DOCX, image, and all-OCR documents leave the field `null`.
- **Delivered:** `pii_input_text` v1 as a second **additive optional field** on `text_result`
  (Option A; no `pii_input_blocks`/structured schema in v1). Produced for **PDF text-layer pages**
  by reading the text positions pypdf already computes while walking the content stream
  (`extract_text(visitor_operand_before=...)`, reading each `Tj`/`TJ` draw operation's text
  matrix — no bespoke PDF parsing, no new dependency). It groups a stable two-column layout into a
  left block followed by a right block (`[BLOCK: left]` / `[BLOCK: right]` — **geometric**
  left/right, not a semantic contractor/customer role label) and reconstructs table rows once a
  known header-token line is found (`[TABLE]`, row-wise, header through end of page). Pages where
  fragment/column detection is not confident, OCR pages, and DOCX/image documents leave the field
  `null` (a marked linear fallback per page on multi-page documents, mirroring
  `layout_text_result`). **It is internal and not displayed in the UI** — a proposed later step.
- **Delivered:** `layout_blocks_version = "1"` and additive `layout_blocks[]`. PDF text-layer blocks
  use existing pypdf positions; OCR/image blocks use transient valid PaddleOCR polygons. Ordering is
  deterministic, bounds are normalized, typing is conservative, and missing/invalid geometry
  produces an explicit fallback block. DOCX uses one fallback review block. No new dependency was
  added and benchmark summaries ignore block text.
- **Unchanged:** `text_result.text` (technical raw; historically canonical) is byte-identical to before; PII runs only on it;
  `layout_text_result` v1 generation is unaffected; legacy artifacts without either field stay
  valid. `pii_input_text` is now an additive, internal v1 field — not an alias of raw — but
  it remains **not** the active PII detection input; PII continues to run on technical raw text only.
- **Review UI:** User View defaults to canonical `reading_text` when present and falls back to
  technical raw text for legacy artifacts. Dev View exposes **Kanonischer Lesetext**,
  **Technischer Rohtext**, and **Layout-Text**. Current PII highlights and offset links render only
  in raw mode; reading/layout views are plain text until lineage exists. `pii_input_text` remains
  internal/experimental with no UI.
- **Delivered (L10):** `text_geometry_version = "1"` and additive `text_geometry`. Per page it maps
  canonical line spans to page-local line boxes (`pdf_points` for text-layer via pypdf positions,
  `image_pixels` for OCR via PaddleOCR polygons) with `status`/`coverage`/`flags`; offsets are matched
  against immutable technical raw text, so raw/page text stays byte-stable and PII still uses raw
  text only. Pages without safe geometry degrade to `partial`/`unsupported`; DOCX has none.
  Geometry stores no raw line text and the internal `resolve_span_geometry` lookup returns none. No
  new dependency was added and benchmark loaders ignore it. This delivers line-level source
  anchoring and traceability, and a foundation for future placeholder mapping toward AI-ready
  pseudonymized document generation.
- **Delivered (L10.5):** optional versioned `reading_text` on every non-empty new text artifact.
  The deterministic builder prefers trustworthy positioned/line geometry, then layout blocks,
  layout text, and raw order. It groups simple side-by-side party blocks, separates paired offer
  metadata, reconstructs recognised line-item rows with ` | `, groups totals, and joins split prose
  conservatively. Uncertain documents use `reading_text_status = fallback`; strategy and partial
  coverage are recorded as non-sensitive flags. The golden synthetic quote is asserted exactly.
  User View defaults to this text; Dev View retains explicit raw and layout access. Reading/layout
  views are unhighlighted because current PII offsets still reference raw text.
- **Delivered (L11):** `structured_content_version = "1"` and optional `structured_content` with
  conservative tables/cells, label/value fields, and sections across PDF text-layer, OCR/image, and
  DOCX paths. Values and cells remain canonical/page spans, partial structures are flagged, and
  benchmark loaders ignore the payload. Technical raw text and active PII input are unchanged.
- **Delivered (L12):** the canonical `reading_text` builder now applies a bounded layout
  reconstruction pass for confident multi-column prose: x-position clusters must have distinct
  starts, overlapping vertical ranges, and prose-like density before columns render left-to-right,
  top-to-bottom. Table-owned and party-heading-owned regions stay on their existing paths, fused
  table headers reconstruct only when following rows provide safe column positions, and adjacent
  label/value pairs join only when geometry is close enough to be unambiguous. New non-sensitive
  flags include `multi_column_reconstruction`, `dense_table_reconstruction`, and
  `label_value_pairing`. Low-confidence layouts keep the existing row order. L12 deliberately
  favors stable, measurable quality gains over aggressive correction: future dictionary, domain,
  OCR-comparison, second-engine, confidence, document-type, review-feedback, and benchmark signals
  should be added as optional confidence evidence, not as destructive rewrites or downstream PII
  dependencies.
- **Not in L12:** `text_lineage_map`, word-level/redaction-ready geometry, a PII-input switch, a
  structured `pii_input_blocks` schema, semantic role labelling (contractor vs.
  customer) for `pii_input_text` blocks, active PII use of `pii_input_text`, pseudonymization,
  placeholder mapping, document export, and pixel-perfect visual redaction.
- **Delivered (L13):** table/form reconstruction v2 builds on L12's row-alignment primitives rather
  than replacing them. A shared row-extension helper now backs both the keyword-header table
  renderer and a new geometry-only detector: a maximal run of 3+ consecutive rows sharing 3+ aligned
  columns renders row-wise even with no recognized header vocabulary, gated by the same
  party-heading/label-value-form ownership checks L12 already used to keep prose and forms out of
  table detection. A 1- or 2-cell fused table header is recovered by concatenating cell text and
  reusing the existing marker-based header split, generalizing what previously only worked for a
  single fused cell. Adjacent-row label/value pairing (a label alone on its row, paired with a value
  on the next row) now extends across further following rows that stay in the same column, at normal
  line spacing, and do not themselves look like a new label, heading, bullet, data row, filename row,
  or another inline "label: value" fact — the last check closes a gap a private-corpus validation
  pass found where an unrelated fact was being absorbed as a continuation. `structured_content` field
  detection gained the equivalent multiline continuation for both the inline (`Label: value`) and
  next-line (`Label` then `value` below it) shapes, bounded by the same kind of stop conditions. New
  non-sensitive flags: `generic_table_reconstruction` and `multiline_value_pairing` on `reading_text`;
  `multiline_value` on `StructuredField.flags`. All are additive; legacy artifacts without them
  remain valid.
- **Delivered (L14):** quality evidence and lineage coverage as an additive, optional, versioned
  `quality_evidence` field on `text_result`. A deterministic builder (`ocr_quality.py`) derives, from
  already-computed inputs, metrics-only evidence items (source_text, pdf_text_layer, ocr_engine,
  positioned_rows, page_geometry, page_zone, reading_order, the reconstruction/fallback strategies,
  structured_content, reading_text_map, lineage_coverage, projection_lineage) plus a summary with
  `QualityLineageCoverage`. Page zones are classified conservatively from existing geometry and are
  evidence only (they never delete, reorder, or reclassify text). `details` is `dict[str, int]` so no
  raw text can be stored; the schema validates that evidence offsets stay inside the actual
  raw/reading text. Technical raw text, active PII input, PII projection/decisions, the
  `quality_report` artifact, benchmark payloads, dependencies, and public APIs are unchanged.
- **Not in L14:** local AI assist for hard pages (the deferred earlier placeholder meaning; see
  [ADR-0025](../adr/0025-ocr-l14-quality-evidence-and-lineage-coverage.md)), dictionary/lexicon
  checks, multi-OCR, and local-LLM structure/quality hints (all deferred, additive *evidence, not
  truth*), automatic OCR correction, a PII-input switch, `text_lineage_map`,
  word-level/redaction-ready geometry, pseudonymization, placeholder mapping, document export, and
  pixel-perfect visual redaction.
- **Not in L13:** document-type/section/zone classification (deferred, see
  [ADR-0024](../adr/0024-ocr-l13-table-form-reconstruction-v2.md)), a fix for the pre-existing
  row-geometry-collection gap that makes some dense/complex table pages fall back to plain raw order
  before any table detector runs, `text_lineage_map`, word-level/redaction-ready geometry, a
  PII-input switch, pseudonymization, placeholder mapping, document export, and pixel-perfect visual
  redaction.

## Future implementation direction

Plan for the layers beyond the v1 slice:

- The reading/layout UI and builder use libraries already present; no dependency was added.
- `pdfplumber` / `PyMuPDF` geometry and Docling / PP-Structure remain later spikes (each needs its
  own PR and dependency review) — candidates for precise L10 geometry or extending
  `pii_input_text` beyond the current header-token table heuristic.
- A `text_lineage_map` is the next step for `pii_input_text`: it is required before `pii_input_text`
  may become the active PII detection input, gated on the [separation rule](#invariants).
- Any implementation must prove:
  - technical raw text remains unchanged;
  - PII tests remain green;
  - `reading_text`, `readable_text`, `layout_text_result`, `pii_input_text`, `layout_blocks`,
    `structured_content`, and `text_lineage_map` are optional;
  - every derived layer maps back to technical raw offsets (and source) — no islands;
  - the UI fallback from reading/layout views to technical raw text works.

## Non-scope

- `pii_input_text` is delivered but remains additive/experimental and not the active PII detection
  input (see [Implementation status](#implementation-status-v1) and the
  [separation gate](#invariants));
- no UI redesign beyond the three explicit text-layer labels/modes;
- no OCR confidence;
- no `quality_report`;
- no structured-content-driven PII detection;
- no placeholder generation or pseudonymized output;
- no perfect PDF reproduction;
- no PII change;
- no redaction;
- no new dependencies.

## References

- [`engine-artifacts.md`](engine-artifacts.md#raw-canonical-reading-and-layout-text) — technical raw /
  canonical reading / PII-input / readable / layout artifacts, lineage, and privacy rules
- [`ocr-engine-levels.md`](ocr-engine-levels.md) — authoritative OCR 0–19 ladder
- [`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md) — the OCR/PII PR sequence and
  checkpoint loop
- [`pii-engine-levels.md`](pii-engine-levels.md) — PII ladder (detection currently consumes technical raw text)
- [`README.md`](README.md) — engine capability model + 0–19 maturity scale
