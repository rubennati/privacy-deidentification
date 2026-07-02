# OCR / Layout Text Contract

The contract that fixes the OCR/Text output model **before** any layout implementation begins. It
separates three text layers on purpose — **canonical**, **readable**, and **layout** — so that
human-readable and layout-preserving renderings can evolve without ever endangering the offset
stability that PII and Review depend on.

This is a **planning / contract document**: it defines names, invariants, and representation rules.
It changes no code, no API, no schema, and no dependency. Implementation happens later, in its own
PR, and must satisfy the invariants below.

## Purpose

OCR/Text is the foundation for PII, Review, and later Redaction. If the extracted text loses its
structure — two-column blocks linearised, table headers separated from their values — everything
built on top degrades. This contract deliberately separates:

- **canonical text** — correctness-first, offset-stable, the only PII/Review input;
- **readable text** — a human-readable normalisation of the same content;
- **layout text** — a plain-text reconstruction of the document's visual structure.

Keeping them separate means a nicer rendering can never shift a PII offset.

## Text layers

### 1. Canonical text

- **Field:** `text_result.text` (per-page `text_result.pages[].text`, joined with `\n\n`).
- **Existing name / synonym:** **`best_text_result`** — this is and remains the canonical,
  correctness-first text (as already documented in
  [`engine-artifacts.md`](engine-artifacts.md#canonical-and-readable-text)).
- **Purpose:** correctness-first, **offset-stable**, the PII/Review basis.
- **Invariant:** PII offsets reference **exclusively** this layer.
- **Rule:** it must **not** be changed by readable/layout experiments. `best_text_result` is **not**
  redefined to mean readable text.

### 2. Readable text

- **New optional field/artifact:** `readable_text` (additive; absent on older artifacts).
- **Purpose:** a human-readable rendering of the same content.
- **May:** improve whitespace, join paragraphs, repair hyphenation, normalise line breaks.
- **Must not:** carry a PII-offset guarantee, and must **not** be used as a PII input.

### 3. Layout text

- **New optional field/artifact:** `layout_text_result` (additive; absent on older artifacts).
- **Purpose:** a plain-text reconstruction of the document's **visual structure**.
- **Covers:** pages, blocks, two-column areas, tables, header/footer, sum/total blocks.
- **Form:** monospaced, best-effort.
- **Must not:** carry a PII-offset guarantee.
- **UI:** may display it, but must be able to **fall back to canonical text** (`text_result.text`)
  when it is absent (e.g. OCR-only or DOCX documents).

## Invariants

These hold for any future implementation:

- **Existing `text_result` remains stable** — `text`, `pages[].text`, and `text_char_count` are
  byte-identical to today; the existing content validators are untouched.
- **PII detection uses only canonical text.**
- **PII highlights and offsets remain bound to canonical text.**
- **`readable_text` and `layout_text_result` are additive** — new optional fields/artifacts.
- **No existing artifacts are rewritten** — a re-run creates a new artifact; nothing is mutated.
- **Legacy artifacts remain valid** — older artifacts without the new fields still validate.
- **Layout reconstruction must not create a new source-of-truth text for PII** — canonical text
  stays the single source of truth for detection and review.

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

## Example

Synthetic illustration only — **no real data**. Target shape of `layout_text_result` for a
two-column offer with a table:

```text
AUFTRAGNEHMER                                  AUFTRAGGEBER
Sanierungsbau Perchtoldsdorf GmbH              Herr Dipl.-Ing. Franz Hubermayr
Lindenstraße 42                                Rosengasse 7/12

Pos.  Leistung                              Menge  Einheit  Einzelpreis      Gesamt
1     Abbrucharbeiten Innenwände            45     m²       € 38,00          € 1.710,00
2     Fassadendämmung                       180    m²       € 92,00          € 16.560,00
```

The canonical `text_result.text` for the same document is unchanged and may linearise the above;
`layout_text_result` is an additional, best-effort readable reconstruction — never the PII input.

## Relationship to OCR levels

Anchored to the existing 0–19 ladder in [`ocr-engine-levels.md`](ocr-engine-levels.md), which stays
**authoritative** — this contract invents no new level numbers:

- **OCR L6:** OCR confidence.
- **OCR L7:** `quality_report`.
- **OCR L8:** human-readable text output — the point at which the canonical vs readable split is
  first realised (`best_text_result` stays canonical; `readable_text` is the readable rendering).
- **OCR L9:** `layout_text_result` — layout-aware reading order and block structure.
- **OCR L10+:** bounding boxes / per-block source lineage.
- **OCR L11+:** table / form reconstruction.
- **Higher levels:** document understanding / redaction-ready geometry.

`layout_text_result` v1 targets OCR L8→L9; deeper structure (geometry, tables) lands at the higher
levels above. See also the sequence in
[`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md).

## Future implementation direction

Plan only — **not implemented here**:

- v1 can start with libraries already present (no new dependency).
- For the PDF text layer, a layout-aware extraction mode can be evaluated.
- OCR-box-based layout, `pdfplumber` / `PyMuPDF` geometry, and Docling / PP-Structure remain later
  spikes (each needs its own PR and dependency review).
- Any implementation must prove:
  - canonical text remains unchanged;
  - PII tests remain green;
  - `layout_text_result` is optional;
  - the UI fallback to canonical text works.

## Non-scope

- no implementation;
- no UI change;
- no OCR confidence;
- no `quality_report`;
- no table engine;
- no perfect PDF reproduction;
- no PII change;
- no redaction;
- no new dependencies.

## References

- [`engine-artifacts.md`](engine-artifacts.md#canonical-and-readable-text) — canonical/readable/layout
  text artifacts and privacy rules
- [`ocr-engine-levels.md`](ocr-engine-levels.md) — authoritative OCR 0–19 ladder
- [`ocr-pii-implementation-plan.md`](ocr-pii-implementation-plan.md) — the OCR/PII PR sequence and
  checkpoint loop
- [`README.md`](README.md) — engine capability model + 0–19 maturity scale
