# OCR / Layout Text Contract

The contract that fixes the OCR/Text output model **before** any layout implementation begins. It
separates four text layers on purpose — **canonical**, **PII-input**, **readable**, and **layout** —
tied together by a single **lineage map**, so that a detection-optimised internal representation and
human-readable/layout-preserving renderings can evolve without ever endangering the offset stability
that PII and Review depend on, and without creating a second, unconnected source of truth.

This is a **planning / contract document**: it defines names, invariants, and representation rules.
It changes no code, no API, no schema, and no dependency. Implementation happens later, in its own
PR, and must satisfy the invariants below.

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
- **v1:** `pii_input_text = canonical_text` (identity). PII detection continues to run on canonical
  text; this layer is an **alias** until a real representation is justified.
- **Later:** it may become its own representation, but **only with a clean mapping/lineage** (see the
  [lineage map](#5-lineage-map)) so every `pii_input_text` span resolves deterministically back to
  canonical offsets.
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

## Invariants

These hold for any future implementation:

- **Existing `text_result` remains stable** — `text`, `pages[].text`, and `text_char_count` are
  byte-identical to today; the existing content validators are untouched.
- **One source of truth.** There must be **no two unconnected source-of-truth texts**. Canonical text
  is the single source of truth and coordinate system; every other layer maps back to it (and to
  source) via `text_lineage_map`.
- **PII detection resolves to canonical.** In v1, PII runs on canonical text (`pii_input_text =
  canonical_text`). If a distinct `pii_input_text` is later introduced, PII detection may run on it,
  but **every** result must map deterministically to canonical offsets — no PII result may exist that
  cannot be expressed in canonical coordinates.
- **PII highlights and offsets remain anchored to canonical text.** Visible marking in
  `layout_text_result` happens **through** the lineage map, never by re-detecting on the layout text.
- **PII-input text and layout text must be married via lineage/mapping** — neither is a standalone
  island; both trace to the same source blocks/lines/words as canonical.
- **`pii_input_text`, `readable_text`, `layout_text_result`, and `text_lineage_map` are additive** —
  new optional fields/artifacts.
- **No existing artifacts are rewritten** — a re-run creates a new artifact; nothing is mutated.
- **Legacy artifacts remain valid** — older artifacts without the new fields still validate.
- **Separation gate.** A later implementation may separate `pii_input_text` from canonical **only
  when** a tested `text_lineage_map` exists, canonical↔pii_input offsets round-trip without loss, and
  the existing PII tests stay green. Until then, `pii_input_text = canonical_text`.

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
truth. In v1, `pii_input_text = canonical_text`, so the internal example above is a *target* shape for
a later, mapping-backed representation — not v1 behaviour.

## Relationship to OCR levels

Anchored to the existing 0–19 ladder in [`ocr-engine-levels.md`](ocr-engine-levels.md), which stays
**authoritative** — this contract invents no new level numbers:

- **OCR L6:** OCR confidence.
- **OCR L7:** `quality_report`.
- **OCR L8:** human-readable text output — canonical vs readable split first realised
  (`best_text_result` stays canonical; `readable_text` is the readable rendering).
- **OCR L9:** `layout_text_result` — layout-aware reading order and block structure.
- **OCR L10+:** bounding boxes / per-block source lineage — the structural basis for
  `text_lineage_map` and any real `pii_input_text` divergence.
- **OCR L11+:** table / form reconstruction.
- **Higher levels:** document understanding / redaction-ready geometry (the lineage map's long-term
  payoff for bounding boxes and redaction).

`layout_text_result` v1 targets OCR L8→L9. A distinct `pii_input_text` and a full `text_lineage_map`
are **not** v1 — they build on the block/geometry structure from OCR L9–L10 and gate on the
separation rule above. See the sequence in
[`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md).

## Implementation status (v1)

- **Delivered:** `layout_text_result` as an **additive optional field on the existing `text_result`**
  (Option A — simpler and lower-risk than a separate artifact). Produced for **PDF text-layer pages**
  via pypdf's `extract_text(extraction_mode="layout")` (no new dependency). OCR pages are marked "not
  reconstructed" and fall back to their linear text; page boundaries are shown with a visible marker.
  DOCX, image, and all-OCR documents leave the field `null`.
- **Unchanged:** `text_result.text` (canonical) is byte-identical to before; PII runs only on it;
  legacy artifacts without the field stay valid. `pii_input_text` remains an alias of canonical.
- **Review UI:** when the optional field is present, reviewers can switch from the default canonical
  view to a display-only monospaced layout view. PII highlights and offset links remain canonical;
  layout text is never highlighted, and legacy artifacts fall back silently to canonical text.
- **Not in v1:** `readable_text`, a distinct `pii_input_text`, `text_lineage_map`, block/line
  geometry, and table reconstruction.

## Future implementation direction

Plan for the layers beyond the v1 slice:

- v1 can start with libraries already present (no new dependency); `pii_input_text = canonical_text`
  and `layout_text_result` is optional.
- For the PDF text layer, a layout-aware extraction mode can be evaluated.
- OCR-box-based layout, `pdfplumber` / `PyMuPDF` geometry, and Docling / PP-Structure remain later
  spikes (each needs its own PR and dependency review).
- A distinct `pii_input_text` and `text_lineage_map` are later steps, gated on the separation rule.
- Any implementation must prove:
  - canonical text remains unchanged;
  - PII tests remain green;
  - `pii_input_text`, `readable_text`, `layout_text_result`, and `text_lineage_map` are optional;
  - every non-canonical layer maps back to canonical (and source) — no islands;
  - the UI fallback to canonical text works.

## Non-scope

- no implementation (in v1, `pii_input_text` is an alias of canonical, not a separate representation);
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
