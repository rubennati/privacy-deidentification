# OCR / Layout Text Contract

The contract that fixes the OCR/Text output model **before** any layout implementation begins. It
separates four text layers on purpose — **canonical**, **PII-input**, **readable**, and **layout** —
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

- **canonical text** — correctness-first, offset-stable, the source of truth and coordinate system;
- **PII-input text** — an internal, detection-optimised representation (preserving logical blocks,
  roles, table rows, address blocks, page structure) — **not** optimised for visual beauty;
- **readable text** — a human-readable normalisation of the same content;
- **layout text** — a plain-text reconstruction of the document's visual structure (Review/UI);
- **lineage map** — the mapping that marries all of the above to the same source blocks/lines/words.

Keeping them separate — but **mapped** — means a nicer rendering or a smarter detection view can
never shift a canonical PII offset, and no layer becomes an island.

## Text layers

### 1. Canonical text

- **Field:** `text_result.text` (per-page `text_result.pages[].text`, joined with `\n\n`).
- **Existing name / synonym:** **`best_text_result`** — this is and remains the canonical,
  correctness-first text (as documented in
  [`engine-artifacts.md`](engine-artifacts.md#canonical-and-readable-text)).
- **Purpose:** correctness-first, **offset-stable**, the **single source of truth** and the offset
  coordinate system for PII/Review.
- **Invariant:** canonical text is the coordinate system every other layer maps back to.
- **Rule:** it must **not** be changed by PII-input/readable/layout experiments. `best_text_result`
  is **not** redefined to mean readable text.

### 2. PII-input text

- **New optional field/artifact:** `pii_input_text` (a.k.a. `pii_text_result`) — internal, not
  primarily user-visible.
- **Purpose:** improve **detection quality and context** by preserving logical blocks, roles, table
  rows, address blocks, and page structure better than a linearised string.
- **v1 (delivered, PDF text layer only):** a real, additive, experimental reconstruction — two-column
  blocks grouped left-block-fully-then-right-block-fully, and table rows reconstructed row-wise from
  a known header line. It is **not** an alias of canonical text, but it is also **not the active PII
  detection input**: PII continues to run exclusively on canonical text, unaffected by this field.
  `pii_input_text` is marked internal/experimental precisely because no lineage map exists yet — see
  the [separation gate](#invariants). Pages without a confident reconstruction (OCR pages, or
  uncertain fragment/column detection) fall back to `None`, mirroring `layout_text_result`.
- **Later:** becomes the **active** detection input only with a clean mapping/lineage (see the
  [lineage map](#5-lineage-map)) so every `pii_input_text` span resolves deterministically back to
  canonical offsets — and only after the [separation gate](#invariants) is satisfied.
- **Must not:** be optimised for visual beauty, and must **never** become a second, unconnected
  source of truth. It is a detection **view** over canonical + source, not a rival original.

### 3. Readable text

- **New optional field/artifact:** `readable_text` (additive; absent on older artifacts).
- **Purpose:** a human-readable rendering of the same content.
- **May:** improve whitespace, join paragraphs, repair hyphenation, normalise line breaks.
- **Must not:** carry a PII-offset guarantee, and must **not** be used as a PII input.

### 4. Layout text

- **New optional field/artifact:** `layout_text_result` (additive; absent on older artifacts).
- **Purpose:** a plain-text reconstruction of the document's **visual structure** for Review/UI.
- **Covers:** pages, blocks, two-column areas, tables, header/footer, sum/total blocks.
- **Form:** monospaced, best-effort.
- **Must not:** carry a PII-offset guarantee.
- **UI:** may display it, but must be able to **fall back to canonical text** (`text_result.text`)
  when it is absent (e.g. OCR-only or DOCX documents).

### 5. Lineage map

- **New optional field/artifact:** `text_lineage_map` (a.k.a. `layout_mapping`).
- **Purpose:** connect **source** (page → block → line → word) ↔ **canonical** ↔ **PII-input** ↔
  **readable** ↔ **layout**, so the layers are one married model, not islands.
- **Enables:** PII is detected internally on `pii_input_text`, its spans map to canonical offsets,
  and canonical offsets map to positions in `layout_text_result` — so a detection can be **visibly
  marked in the layout view** while its authoritative offsets stay canonical.
- **Long term:** the same map is the basis for **bounding boxes** and **redaction** (canonical span →
  page geometry), aligning with OCR L10+ per-block lineage and redaction-ready geometry.
- **Must:** be deterministic and round-trippable (canonical ↔ pii_input without loss) wherever
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
- **Purpose:** provide the first canonical-offset-bearing geometry — resolve a canonical line span to
  one or more page-local line boxes — for source anchoring, review/debug, and traceability, and as a
  foundation for future placeholder mapping toward AI-ready pseudonymized document generation.
- **Contents:** per page, a `coordinate_unit` (`pdf_points` for text-layer, `image_pixels` for OCR),
  `page_width`/`page_height`, extraction `source`, a `status` (`complete`/`partial`/`unsupported`),
  and `lines[]`. Each line maps `canonical_start`/`canonical_end` (into `text`) and
  `page_start`/`page_end` (into `pages[].text`) to page-local `x0/y0/x1/y1` bounds, with optional OCR
  confidence. The geometry also carries overall `coverage` and `flags`. It stores **no** raw line
  text.
- **Derivation:** offsets are obtained by matching page-local text segments against the immutable
  canonical page text — the canonical text is never regenerated or altered. Pages without safely
  derivable geometry degrade to `partial`/`unsupported` rather than guessing; DOCX has no geometry.
- **Boundary:** line-level source anchoring only. It does not perform pseudonymization, placeholder
  mapping, document export, or pixel-perfect visual redaction; word-level geometry and a general
  `text_lineage_map` remain L11+ work. The internal `resolve_span_geometry` helper is the
  canonical-span→box lookup; it never returns raw text.

## Invariants

These hold for any future implementation:

- **Existing `text_result` remains stable** — `text`, `pages[].text`, and `text_char_count` are
  byte-identical to today; their existing validation rules remain enforced.
- **One source of truth.** There must be **no two unconnected source-of-truth texts**. Canonical text
  is the single source of truth and coordinate system; every other layer maps back to it (and to
  source) via `text_lineage_map`.
- **PII detection resolves to canonical.** PII runs exclusively on canonical text today —
  independent of whatever `pii_input_text` contains, including its populated v1 reconstruction. If
  `pii_input_text` is later made the active detection input, **every** result must map
  deterministically to canonical offsets — no PII result may exist that cannot be expressed in
  canonical coordinates.
- **PII highlights and offsets remain anchored to canonical text.** Visible marking in
  `layout_text_result` happens **through** the lineage map, never by re-detecting on the layout text.
- **PII-input text and layout text must be married via lineage/mapping** — neither is a standalone
  island; both trace to the same source blocks/lines/words as canonical.
- **`pii_input_text`, `readable_text`, `layout_text_result`, `layout_blocks`, `text_geometry`, and
  `text_lineage_map` are additive** — new optional fields/artifacts.
- **No existing artifacts are rewritten** — a re-run creates a new artifact; nothing is mutated.
- **Legacy artifacts remain valid** — older artifacts without the new fields still validate.
- **Separation gate.** `pii_input_text` may become the **active PII detection input** only when a
  tested `text_lineage_map` exists, canonical↔pii_input offsets round-trip without loss, and the
  existing PII tests stay green. Until that gate is satisfied, PII detection uses canonical text
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
- **OCR L11+:** table / form reconstruction.
- **Higher levels:** document understanding / redaction-ready geometry (the lineage map's long-term
  payoff for bounding boxes and redaction).

`layout_text_result` v1, `pii_input_text` v1, and the structured layout blocks complete OCR L9 —
visible layout, internal experimental reading order, and review-oriented typed regions. A full
`text_lineage_map` (and `pii_input_text` becoming the active detection input) are **not** v1 — they
build on the
block/geometry structure from OCR L10 and gate on the separation rule above. See the sequence in
[`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md).

## Implementation status (v1)

- **Delivered:** `readable_text` as an **additive optional field on the existing `text_result`**
  (Option A; no separate artifact in v1). Produced for any non-empty canonical text with a small,
  deterministic normalization pass: line-ending cleanup, trailing-space removal, conservative
  paragraph joining, simple line-break de-hyphenation, and visible page boundaries between
  canonical pages. It never feeds PII and carries no offset guarantee.
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
- **Unchanged:** `text_result.text` (canonical) is byte-identical to before; PII runs only on it;
  `layout_text_result` v1 generation is unaffected; legacy artifacts without either field stay
  valid. `pii_input_text` is now an additive, internal v1 field — not an alias of canonical — but
  it remains **not** the active PII detection input; PII continues to run on canonical text only.
- **Review UI:** when `layout_text_result` is present, reviewers can switch from the default
  canonical view to a display-only monospaced layout view, falling back to canonical text when the
  field is absent. PII highlights and offset links remain bound to canonical text only; layout text
  is never highlighted. `pii_input_text` has no UI in v1 (internal/experimental).
- **Delivered (L10):** `text_geometry_version = "1"` and additive `text_geometry`. Per page it maps
  canonical line spans to page-local line boxes (`pdf_points` for text-layer via pypdf positions,
  `image_pixels` for OCR via PaddleOCR polygons) with `status`/`coverage`/`flags`; offsets are matched
  against the immutable canonical text, so canonical/page text stays byte-stable and PII still uses
  canonical text only. Pages without safe geometry degrade to `partial`/`unsupported`; DOCX has none.
  Geometry stores no raw line text and the internal `resolve_span_geometry` lookup returns none. No
  new dependency was added and benchmark loaders ignore it. This delivers line-level source
  anchoring and traceability, and a foundation for future placeholder mapping toward AI-ready
  pseudonymized document generation.
- **Not in L10:** `text_lineage_map`, word-level geometry, a PII-input switch, a general table
  detector, a structured `pii_input_blocks` schema, semantic role labelling (contractor vs.
  customer) for `pii_input_text` blocks, active PII use of `pii_input_text`, pseudonymization,
  placeholder mapping, document export, and pixel-perfect visual redaction.

## Future implementation direction

Plan for the layers beyond the v1 slice:

- `readable_text` and a UI for either `layout_text_result` or `pii_input_text` can start with
  libraries already present (no new dependency).
- `pdfplumber` / `PyMuPDF` geometry and Docling / PP-Structure remain later spikes (each needs its
  own PR and dependency review) — candidates for precise L10 geometry or extending
  `pii_input_text` beyond the current header-token table heuristic.
- A `text_lineage_map` is the next step for `pii_input_text`: it is required before `pii_input_text`
  may become the active PII detection input, gated on the [separation rule](#invariants).
- Any implementation must prove:
  - canonical text remains unchanged;
  - PII tests remain green;
  - `readable_text`, `layout_text_result`, `pii_input_text`, `layout_blocks`, and
    `text_lineage_map` are optional;
  - every non-canonical layer maps back to canonical (and source) — no islands;
  - the UI fallback to canonical text works.

## Non-scope

- `pii_input_text` is delivered but remains additive/experimental and not the active PII detection
  input (see [Implementation status](#implementation-status-v1) and the
  [separation gate](#invariants));
- no UI change;
- no OCR confidence;
- no `quality_report`;
- no table engine;
- no perfect PDF reproduction;
- no PII change;
- no redaction;
- no new dependencies.

## References

- [`engine-artifacts.md`](engine-artifacts.md#canonical-and-readable-text) — canonical / PII-input /
  readable / layout text artifacts, the lineage map, and privacy rules
- [`ocr-engine-levels.md`](ocr-engine-levels.md) — authoritative OCR 0–19 ladder
- [`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md) — the OCR/PII PR sequence and
  checkpoint loop
- [`pii-engine-levels.md`](pii-engine-levels.md) — PII ladder (detection consumes canonical text)
- [`README.md`](README.md) — engine capability model + 0–19 maturity scale
