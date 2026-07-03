# Engine Artifacts

Each processing station appends an immutable, lineage-linked JSON artifact. This document defines
the existing and planned artifact contracts and their privacy boundaries using the **0–19 maturity
scale**.

## Storage

```text
volumes/
├── uploads/<document_id>.<ext>                     # byte-identical original
└── document-data/<document_id>/
    ├── document.json                               # metadata + original artifact
    ├── artifacts/<artifact_id>.json                # audit/text/quality/PII artifacts
    └── feedback/pii_feedback.jsonl                 # dev-only feedback side-channel
```

Everything under `volumes/` is local and git-ignored. No artifact, feedback log, private benchmark
input, or report may be committed.

## Artifact catalogue

| Artifact | Status | Purpose | Raw text / values | Persistence |
| --- | --- | --- | --- | --- |
| `document.json` | ✅ today | document metadata and embedded `original_artifact` | filename may be sensitive | local file |
| `original_artifact` | ✅ today | byte-identical source pointer and digest | source bytes live in upload storage | embedded in `document.json` |
| `audit_result` | ✅ today | per-page structure, quality verdict, and routing metrics | no page text | immutable artifact |
| `text_result.text` (legacy `best_text_result`) | ✅ today | technical raw extraction; byte-stable PII/review offset basis plus additive OCR-page confidence metrics | yes | immutable artifact |
| `ocr_result` / `text_layer_result` | ◻ conceptual | source-specific page output | yes | folded into `text_result` today |
| `quality_report` | ✅ OCR L7 | source mix, coverage, audit quality counts, confidence summary, exact input lineage | metrics only | immutable artifact |
| `readable_text` | ✅ OCR L8 (field on `text_result`) | earlier human-readable normalization of technical raw text, with conservative paragraph/whitespace cleanup and visible page boundaries | yes | additive optional field on `text_result` |
| `reading_text` | ✅ OCR L10.5 (field on `text_result`) | canonical reading text: deterministic block-aware main document text with heuristic/fallback metadata; future PII/placeholder candidate, not active today | yes | additive optional versioned field on `text_result` |
| `layout_text_result` | ✅ OCR L9 (field on `text_result`) | readable layout plain-text for PDF text layers; Review UI alternative | yes | additive optional field on `text_result` |
| `layout_blocks` | ✅ OCR L9 (field on `text_result`) | ordered typed review blocks with coarse normalized page bounds and extraction source | yes | additive optional versioned field on `text_result` |
| `pii_input_text` | ✅ v1 (field on `text_result`) | internal, experimental semantic reading-order text for PDF text layer (L9 v1: left/right block grouping, row-wise tables); **not** the active PII input, no lineage map yet | yes | additive optional field on `text_result` |
| `text_geometry` | ✅ OCR L10 (field on `text_result`) | per-page line boxes mapping technical raw spans (persisted `canonical_*` compatibility names) to page-local `x0/y0/x1/y1` bounds (`pdf_points`/`image_pixels`), with page status and coverage; source-anchoring/traceability only, no raw line text | no raw text (offsets + bounds only) | additive optional versioned field on `text_result` |
| `structured_content` | ✅ OCR L11 (field on `text_result`) | span-backed tables/cells, label/value fields, sections, and metrics-only counts/flags | short labels/headings only; values/table contents remain raw/canonical spans | additive optional versioned field on `text_result` |
| `pii_result` | ✅ today | detected spans, offsets, counts, PII L6–L8 validation fields, and L9 run settings | yes | immutable artifact |
| `review_result` | 🔜 Review L8 | lineage-bound human decision overlay on `pii_result` | yes | immutable artifact |
| `benchmark_result` | ✅ today as private reports | routing and PII quality metrics | guarded report metadata and metrics | local report files |

`◻ conceptual` means the concept is currently embedded in another artifact and may be separated
only when a later station requires it.

## Raw, canonical reading, and layout text

Distinct text layers, structured layout blocks, and a lineage map are fixed by the
[OCR/Layout text contract](ocr-layout-text-contract.md):

- **`text_result.text`** is the legacy **technical raw text**. It remains byte-stable and is the
  authoritative offset coordinate system for current PII/review and old artifacts. The historical
  `best_text_result` / “canonical text” name refers to this compatibility role only and must not be
  used as the product-facing label.
- **`reading_text`** (optional, additive; `reading_text_version = "1"`) is the **canonical reading
  text** and product-facing main text. It deterministically uses trustworthy position/geometry,
  layout blocks, layout text, then raw-order fallback; it carries `reading_text_status` and
  non-sensitive `reading_text_flags`. It has no offset guarantee yet and is only an intended future
  PII/placeholder input candidate after tested lineage exists.
- **`pii_input_text`** (new, optional, additive; internal) is a **detection-optimised** view that
  preserves logical blocks/roles/table structure. v1 (PDF text layer) delivers a real, geometric
  left/right block grouping and row-wise table reconstruction — but it is **not** the active PII
  detection input, and it may become one later **only** with a tested lineage map (round-trippable
  to canonical). Not user-facing, not a rival source of truth.
- **`readable_text`** (new, optional, additive) is a **human-readable** normalisation of the same
  content (whitespace/paragraph/hyphenation). OCR L8 delivers a deterministic first rendering:
  line-ending cleanup, conservative paragraph joining, simple line-break de-hyphenation, and
  visible page boundaries between raw pages. No PII-offset guarantee; never a PII input.
- **`layout_text_result`** (new, optional, additive) is a **layout-preserving** plain-text
  reconstruction (pages, blocks, columns, tables) for Review/UI, starting at OCR L9. The Review UI
  renders it as an unhighlighted display-only alternative and falls back to reading/raw text when it
  is absent. No PII-offset guarantee.
- **`layout_blocks`** (new, optional, additive; `layout_blocks_version = "1"`) records deterministic
  page/order, conservative type (`heading`/`body`/`caption`/`header`/`footer`/`fallback`), block text,
  extraction source, and coarse normalized 0..1 bounds. PDF blocks use pypdf positions; OCR blocks
  use transient PaddleOCR polygons when valid and otherwise degrade to a marked fallback block.
  These are review/ordering regions only: no canonical offsets, persisted line/word boxes,
  canonical-offset lookup, lineage-map claim, or redaction-ready geometry.
- **`text_geometry`** (new, optional, additive; `text_geometry_version = "1"`) is the first
  raw-offset-bearing geometry: per page it stores line boxes that map a technical raw span
  (`canonical_start`/`canonical_end` into `text`) and page span (`page_start`/`page_end` into
  `pages[].text`) to page-local `x0/y0/x1/y1` bounds in the page's `coordinate_unit` (`pdf_points`
  for text-layer, `image_pixels` for OCR). Offsets are matched against immutable technical raw text,
  never regenerated. Each page reports `status` (`complete`/`partial`/`unsupported`) and the geometry
  reports `coverage`/`flags`; pages without safe geometry degrade rather than guess, and DOCX has
  none. It carries no raw line text and provides line-level source anchoring and traceability — a
  foundation for future placeholder mapping toward AI-ready pseudonymized document generation. It
  does not perform pseudonymization, placeholder mapping, document export, or pixel-perfect visual
  redaction. The internal `resolve_span_geometry` helper resolves a canonical span to intersecting
  line boxes. This is a line-level slice, not the full `text_lineage_map` below.
- **`structured_content`** (new, optional, additive; `structured_content_version = "1"`) records
  conservative L11 tables, fields, and sections per physical page (or one logical DOCX page).
  Table cells and field values reference half-open canonical/page spans rather than duplicating raw
  content; short labels/headings support interpretation. Optional bounds come from L10 line
  geometry, L9 heading blocks can support section detection, and explicit source/confidence/flags
  describe fallback or partial structure. It is not a PII input or a pseudonymization/redaction/
  export artifact.
- **`text_lineage_map`** (new, optional, additive) marries source (page/block/line/word) ↔ canonical
  ↔ PII-input ↔ readable ↔ layout, so PII detected internally can be shown in the layout view while
  its authoritative offsets stay canonical. Long-term basis for bounding boxes and redaction.

These layers are additive and never mutate technical raw text or shift PII offsets. `reading_text`
is a deterministic view over the same extracted source, not an independent source artifact. Until
`text_lineage_map` exists, technical raw text remains the sole offset authority and all other views
remain inactive for PII. The future map must connect reading/PII/layout spans back to raw offsets and
source geometry before any detection-input switch. Older artifacts without the new fields stay
valid.

## OCR confidence boundary

OCR L6 stores confidence additively on OCR-produced `text_result.pages[]` as
`ocr_confidence` (the arithmetic mean of valid PaddleOCR line scores) and
`ocr_line_confidences` (line index, confidence, and character count only). The metric structure does
not duplicate raw OCR line text. Text-layer pages use `null`/an empty list, DOCX remains pageless,
and legacy text artifacts without these fields remain valid.

`audit_result` stays the immutable pre-OCR routing/quality input and is never rewritten after OCR.

## Quality report boundary

OCR L7 appends a separate `quality_report` after every successful OCR/Text run. It references the
exact `original_artifact`, `audit_result`, and `text_result` ids and contains only source counts,
audit status counts, OCR confidence aggregates, character/word counts, pages-without-text coverage,
flags, and tool-version metadata. It contains no canonical/page text, OCR line text, PII, entity
values, layout output, or detection input. Its contract uses `artifact_type = quality_report`,
`station = ocr_quality`, and `quality_report_version = 1`.

Rerunning OCR/Text creates a new `text_result` and a new matching `quality_report`; previous audit,
text, and quality artifacts remain byte-immutable. The benchmark uses a report only when its
lineage matches the latest available inputs and otherwise falls back to legacy audit/text summaries.

## Dev feedback side-channel

`volumes/document-data/<document_id>/feedback/pii_feedback.jsonl` is an append-only, dev-only log,
not an engine artifact and not a binding review result. It is available only behind
`ENABLE_DEV_ENGINE_SETTINGS` and records identifiers, offsets, type, recognizer, score, verdict,
issue type, optional comment, and copied engine settings. Feedback is accepted only when its type,
offsets, and recognizer match an entity in the referenced `pii_result`; the score is copied from the
artifact.

The structured entity fingerprint intentionally excludes document text, OCR full text, and raw
entity values. Optional `text_hash` values are restricted to lowercase SHA-256 digests. Comments
are short reviewer notes and must not contain copied document text, OCR text, or raw PII. The file
must still be treated as sensitive local data; it remains under `volumes/`, is never committed, and
is suitable only for controlled local or aggregate analysis.

## Privacy rules

- **Metrics-only artifacts** (`audit_result`, `quality_report`) contain counts, statuses, reasons,
  coverage, and confidence; they contain no page text or raw entity values.
- **Text artifacts** contain extracted text and therefore may contain PII. `reading_text` is subject
  to the same boundary as technical raw, readable, layout, block, and PII-input text. They remain
  under the local document-data root and are never logged or committed. Additive `text_geometry`
  stores only offsets and page-local bounds (no raw line text); `structured_content` stores offsets
  plus short labels/headings but no duplicated field values or table contents. Both follow the same
  sensitive-artifact handling — geometry offsets/bounds and structured labels must never be logged —
  and benchmark loaders do not copy their payloads into summaries.
- **PII and review artifacts** contain spans and may contain raw entity values. They remain local and
  are never written to application logs.
- **Private benchmark reports** remain under `volumes/` and pass through `privacy_guard.py` before
  writing. Published documentation uses aggregate figures only.
- **Feedback JSONL** follows the separate boundary above; it must not be described as a hard
  privacy-by-construction guarantee because optional free text is accepted.

## Versioning and lineage

- Existing artifacts carry explicit versions (`audit_version`, `ocr_version`,
  `quality_report_version`, `pii_version`). New artifact types follow the same convention.
- Artifacts are append-only: a rerun creates a new artifact id and never mutates the prior result.
- `text_result` references the original and audit artifacts; `quality_report` references that exact
  original/audit/text triple; `pii_result` references its exact text artifact. Future
  `review_result` artifacts extend this chain explicitly.
- Downstream results whose input changes are stale and are never silently reused.
- Additive optional fields preserve legacy artifact readability. Audits written before OCR L4 have
  no `needs_ocr`; routing falls back to `has_text_layer`.
