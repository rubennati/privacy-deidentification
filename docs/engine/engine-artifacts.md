# Engine Artifacts

Each processing station appends an immutable, lineage-linked JSON artifact. This document defines
the existing and planned artifact contracts and their privacy boundaries using the **0–19 maturity
scale**.

## Storage

```text
volumes/                                            # host DATA_ROOT (default ./volumes)
├── uploads/<document_id>.<ext>                     # byte-identical original
├── job-state/
│   └── jobs.sqlite3                                # default SQLite job metadata DB (ids/status only)
└── document-store/
    └── <document_id>/
        ├── document.json                           # metadata + original artifact
        ├── artifacts/<artifact_id>.json            # audit/text/quality/PII artifacts
        ├── feedback/pii_feedback.jsonl             # dev-only feedback side-channel
        └── review/pii_review_decisions.jsonl       # review-decision overlay (see below)
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
| `reading_text` | ✅ OCR L10.5 + L12 + L13 (field on `text_result`) | canonical reading text: deterministic block-aware main document text with heuristic/fallback metadata; L12 adds safe multi-column layout reconstruction, fused table-header rendering, and geometry-bound label/value pairing; L13 adds geometry-only table detection with no header-keyword requirement, partially fused header recovery, and multiline label/value continuation; future PII/placeholder candidate, not active today | yes | additive optional versioned field on `text_result` |
| `layout_text_result` | ✅ OCR L9 (field on `text_result`) | readable layout plain-text for PDF text layers; Review UI alternative | yes | additive optional field on `text_result` |
| `layout_blocks` | ✅ OCR L9 (field on `text_result`) | ordered typed review blocks with coarse normalized page bounds and extraction source | yes | additive optional versioned field on `text_result` |
| `pii_input_text` | ✅ v1 (field on `text_result`) | internal, experimental semantic reading-order text for PDF text layer (L9 v1: left/right block grouping, row-wise tables); **not** the active PII input, no lineage map yet | yes | additive optional field on `text_result` |
| `text_geometry` | ✅ OCR L10 (field on `text_result`) | per-page line boxes mapping technical raw spans (persisted `canonical_*` compatibility names) to page-local `x0/y0/x1/y1` bounds (`pdf_points`/`image_pixels`), with page status and coverage; source-anchoring/traceability only, no raw line text | no raw text (offsets + bounds only) | additive optional versioned field on `text_result` |
| `structured_content` | ✅ OCR L11 + L13 (field on `text_result`) | span-backed tables/cells, label/value fields, sections, and metrics-only counts/flags; L13 adds multiline label/value field continuation | short labels/headings only; values/table contents remain raw/canonical spans | additive optional versioned field on `text_result` |
| `quality_evidence` | ✅ OCR L14 + L15 (field on `text_result`) | metrics-only provenance, reconstruction, page-zone, and lineage-coverage evidence for the run: a list of `QualityEvidenceItem`s plus a `QualityEvidenceSummary` with `QualityLineageCoverage`; explains where text came from and how well it maps back, without changing any text. L15 adds deterministic noise/token artifact *evidence* (glyph artifacts, suspicious token shapes, character-confusion candidates, spacing candidates, and a document-level `ocr_noise_summary`) into the same list | no raw text (offsets, counts, flags, page zones, coarse bounds, stable reason codes; `details` is `dict[str, int]`) | additive optional versioned field on `text_result` |
| `document_text_package` (OCR Output Contract v1) | ✅ today, derived API package (ADR-0027) | versioned external package of the `text_result` layers (raw/canonical/layout/structured) + `reading_text_map` + `quality_evidence` + a `contract_status`; the stable boundary consumers depend on instead of OCR internals | packages existing text layers; adds no new raw text beyond them | computed on request by `GET /api/documents/{document_id}/text-package`; not persisted |
| `pii_result` | ✅ today | detected spans, offsets, counts, PII L6–L8 validation fields, L9 run settings, and L12 per-entity `provenance` + `input_contract`/`overlap_resolution` summaries | yes (spans); provenance/summaries are reason-codes/counts/ids only | immutable artifact |
| entity groups (PII L11) | ✅ today | derived, non-persisted grouping of `pii_result` entities by type + normalized-value fingerprint | no (hash + offsets only) | computed on request, never stored |
| `pii_entity_contract` (review-ready entity contract v1) | ✅ today, derived API view (ADR-0029) | packages the latest `pii_result` entities review-ready: stable `entity_id`, raw + optional canonical span, explicit `mapping_status` (`exact`/`projected`/`partial`/`missing`/`ambiguous`/`not_applicable`), overlap provenance, resolved review state, and a text-free display model | entity `value` mirrors `pii_result` (already on `GET …/pii`); display/warnings/provenance carry ranges + codes only, no snippet | computed on request by `GET /api/documents/{document_id}/pii/entity-contract`; not persisted |
| review-decision overlay | ✅ today (partial Review L8) | lineage-bound `pseudonymize`-by-default `keep`/`false_positive`-opt-out decisions per entity group/occurrence (ADR-0021) | no raw entity/document text by default; optional reviewer `note` is free text (same policy as feedback `comment`) | append-only JSONL, latest-per-target on read |
| `review_result` | 🔜 Review L8 (formal model) | the single-artifact-per-run shape this level originally described; today's decision overlay above covers much of its practical intent | yes | immutable artifact |
| `benchmark_result` | ✅ today as private reports | routing and PII quality metrics | guarded report metadata and metrics | local report files |
| `job_record` (ADR-0023 Phase 2) | ✅ today (durable metadata) | OCR/PII job lifecycle (id, document id, kind, status, execution mode, timestamps, attempt count, safe error code/message, produced artifact id/type); *references* immutable artifacts, never stores their bytes | no (ids, timestamps, sanitized error only) | SQLite metadata DB (`DATA_JOB_STATE_DIR/jobs.sqlite3` by default, in its own job-state root), deleted with document boundary |

`◻ conceptual` means the concept is currently embedded in another artifact and may be separated
only when a later station requires it.

The `job_record` is durable metadata, not an engine artifact. ADR-0023 Phase 1 introduced the
in-process seam; Phase 2 persists that seam in SQLite; Phase 3 reuses the same rows as the OCR
worker's claim/status mechanism (an atomic `UPDATE … RETURNING` claim under WAL — no Redis/broker)
when `OCR_EXECUTION_MODE=worker`, which is now the default OCR runtime mode. `sync` remains an
explicit fallback; PII execution is still synchronous in the API. It carries only non-sensitive
lifecycle metadata and references the immutable artifacts a job produces; raw document text,
canonical reading text, layout text, structured-content payloads, PII values, artifact JSON, stack
traces, and raw exception text never enter it.

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
  non-sensitive `reading_text_flags`. OCR L12 extends this same field with bounded multi-column
  reconstruction, fused-header table rendering, and safe label/value pairing flags. OCR L13 further
  extends it with geometry-only table detection (no header keyword required), partially fused header
  recovery, and multiline label/value continuation. It has no offset guarantee yet and is only an
  intended future PII/placeholder input candidate after tested lineage exists.
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
  describe fallback or partial structure. OCR L13 adds a `multiline_value` field flag when a
  label/value field's value spans more than one line. It is not a PII input or a
  pseudonymization/redaction/export artifact.
- **`quality_evidence`** (new, optional, additive; `quality_evidence_version = "1"`) records OCR L14
  quality evidence and lineage coverage: a list of `QualityEvidenceItem`s (each with a stable
  `evidence_id`, `level`, `type`, `status`, optional bounded `confidence`, stable `reason_code`,
  optional offset ranges / page number / page zone / coarse bounds / `related_artifact`, non-sensitive
  `flags`, and an integer-only `details` map) plus a `QualityEvidenceSummary` (`overall_status`,
  advisory `overall_score`, status/type counts, `warnings`, `blockers`, `reconstruction_summary`,
  `fallback_summary`, and a `QualityLineageCoverage` block). It explains where text came from (PDF
  text layer, OCR, or fallback), which parts were confidently reconstructed versus fell back,
  conservative page zones from existing geometry, and how well canonical reading text maps back to
  technical raw text and source geometry. It carries **no raw text** (`details` is `dict[str, int]`
  by construction) and changes no text layer, PII input, or PII decision. **OCR L15** extends the
  same list with deterministic noise/token artifact evidence — glyph artifacts, suspicious token
  shapes, O/0, I/l/1, and rn/m character-confusion candidates, and spacing candidates (single-letter
  token runs, long letters-only tokens with one internal case transition) — plus a document-level
  `ocr_noise_summary` item; it is *evidence, not correction* and never rewrites, removes, or reorders
  any text.
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

## Quality evidence boundary (OCR L14)

OCR L14 attaches additive `quality_evidence` to every new `text_result`. Unlike the separate,
lineage-bound, benchmark-consumed `quality_report` (which summarizes routing/confidence), this field
travels with the text artifact and explains the reading/reconstruction/lineage of *that* artifact:
provenance (text layer / OCR / fallback), reconstruction paths used, conservative page zones, and how
much canonical reading text maps back to technical raw text and source geometry. It is derived
deterministically from already-computed inputs, re-runs nothing, and classifies missing signals as
`unavailable`/`not_applicable` rather than inventing them. It contains no raw page text, OCR line
text, PII, or entity values — only offsets, counts, flags, page zones, coarse bounds, and stable
reason codes, with an integer-only `details` map. It is not a PII input and never changes PII
detection or review decisions; benchmark loaders ignore it, and it follows the same sensitive-artifact
handling as the other text-artifact fields (never logged, never committed). Legacy `text_result`
artifacts without it remain valid.

## Noise/token artifact evidence boundary (OCR L15)

OCR L15 extends the same `quality_evidence` list — no new artifact, no new schema version — with
deterministic noise/token artifact *evidence*: a dedicated builder (`ocr_noise.py`) scans technical
raw per-page text only (never `reading_text` or `structured_content`) for glyph artifacts, suspicious
token shapes, character-confusion candidates (O/0, I/l/1, rn/m, and a general letter↔digit
*alternation*-based `mixed_alnum_confusion`), and spacing candidates (single-letter-token runs, long
letters-only tokens with one internal case transition), tags findings with the existing L14 page-zone
classification, and always appends one document-level `ocr_noise_summary` item (even when clean).
Structured-identifier- and IBAN-shaped tokens are exempted, as are intentional divider/bullet/leader
character runs; trailing sentence punctuation is stripped before shape analysis so an abbreviation is
judged on its own shape. It is **evidence, not correction**: nothing is ever rewritten, removed, or
reordered, and no dictionary/lexicon, second OCR engine, or local LLM is used. It carries no raw
token text — every locator is an offset range, page number, page zone, count, or stable
`reason_code`, and `details` remains `dict[str, int]` — and never changes PII detection, review
decisions, or any text layer. A local, metrics-only private-corpus validation pass (never committed;
`.local` outputs) found and fixed four generic (non-corpus-specific) over-flagging patterns before
this reached its final state; see [ADR-0026](../adr/0026-ocr-l15-noise-token-artifact-evidence.md).

## OCR Output Contract v1 / Document Text Package boundary (implemented)

The cross-cutting stabilization step ([ADR-0027](../adr/0027-ocr-output-contract-v1-strategy.md))
is implemented additively as a derived API package. `DocumentTextPackageV1` packages the
`text_result` text layers — `text` (**technical raw**, authoritative), `reading_text`
(**canonical**, derived/contextual), `layout_text_result` (**layout**), `structured_content`
(**structured**, semantic hints), the offset-only `reading_text_map`, and `quality_evidence`
(**evidence**, trust/uncertainty metadata incl. L15 noise) — into one **versioned** container with
`contract_version = "1.0"` and an explicit `contract_status`
(`valid`/`degraded`/`invalid`) plus `warnings`/`blockers`/`missing_capabilities`.

`invalid` marks blockers such as missing required raw text, invalid document id, unsupported
contract version, or malformed source roles. `degraded` marks usable packages with missing optional
layers or incomplete lineage/evidence signals. `valid` means no warnings/blockers. The package is
computed on request by `GET /api/documents/{document_id}/text-package`, is not persisted as its own
artifact, and does not change `GET/POST .../ocr`.

Consumers (PII, Review, pseudonymization, document analysis, export, local AI) can depend on the
contract and its source roles rather than on individual fields or the underlying engine. **PII is
now the first migrated consumer** ([ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md)):
it consumes `DocumentTextPackageV1` through the `pii_input` intake adapter (`PiiInputDocumentV1`)
rather than reaching into `TextContent`. Technical raw text stays the **primary and only active
detection input**; canonical is contextual, structured content a hint layer, and quality/noise
evidence trust context — none of which is treated as authoritative or applied to silently suppress
an entity. A structurally invalid package is rejected (`422`), empty raw text stays the benign
empty-result path, and a degraded package with raw text still processes. Switching the active PII
detection input away from raw still requires the tested `text_lineage_map` separation gate.

The `pii_result` records what PII consumed and how overlaps resolved in additive, optional fields —
`PiiContent.input_contract` (contract version/status/package id and which layers were present),
`PiiContent.overlap_resolution` (deterministic PII L12 merge/drop/flag counts by reason code), and
`PiiEntity.provenance` (detection source/role, contributing recognizers, merge/overlap reason codes,
and superseded candidate ids). These are reason-codes/counts/ids only and never copy raw document or
entity text; legacy `pii_result` artifacts without them stay valid.

## Review-ready PII entity contract (implemented)

The **review-ready entity contract v1** ([ADR-0029](../adr/0029-pii-review-ready-entity-contract.md))
is a pure, derived API view over the latest `pii_result`, exposed by
`GET /api/documents/{document_id}/pii/entity-contract` (`pii_entity_contract.py`). It packages each
L12-resolved entity review-ready: a **stable `entity_id`** (hash of document id + entity type + raw
span, so it survives a re-run while the volatile occurrence id is kept as `source_entity_id`), the
authoritative `raw_text_range`, an optional `canonical_reading_text_range`, an explicit
`mapping_status` (`exact`/`projected`/`partial`/`missing`/`ambiguous`/`not_applicable`), the overlap
`provenance`, the resolved review state from the decision overlay, and a text-free `display` model
(preferred text source, raw + optional canonical highlight ranges, entity-type label,
`needs_review`, and review reason codes). A missing/partial/ambiguous canonical mapping never drops
an entity — it stays reviewable and flagged; `not_applicable` (no canonical text at all for the run)
is not flagged. It mutates nothing, adds no detection, and reuses the existing review-decision
overlay for review state. This is **not** the formal binding `review_result` — it is the stable
review-ready read model that model will build on.

## Dev feedback side-channel

`volumes/document-store/<document_id>/feedback/pii_feedback.jsonl` is an append-only, dev-only log,
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

## PII entity grouping and the review-decision overlay

See [ADR-0021](../adr/0021-pii-entity-grouping-and-review-decisions.md) for the full design. In
short:

- **Entity grouping (PII L11)** is a pure, derived view computed from the latest `pii_result` on
  every `GET …/pii/review` request (`pii_grouping.py`). It stores nothing on `PiiEntity`,
  `PiiContent`, or `PiiArtifact` — detection and the existing `pii_result` schema are unchanged.
  `entity_group_id` and `normalized_fingerprint` are SHA-256 hashes of entity type + a conservative
  per-type normalized value; the normalized value itself is never persisted or logged.
- **The review-decision overlay** (unlike the dev-only feedback side-channel above) is **not**
  gated behind `ENABLE_DEV_ENGINE_SETTINGS` — it is the binding handoff layer a future
  pseudonymization engine will consume, so it must be available whenever a PII result exists.
  `volumes/document-store/<document_id>/review/pii_review_decisions.jsonl` is an append-only log of
  one decision per line (`target_type`, `target_id`, `decision`, optional `note`, the exact
  `pii_result.id` it was recorded against); reading collapses it to the **latest line per target**.
  A decision never mutates `pii_result` or any raw/projected offset, and a re-run producing a new
  PII artifact id makes prior decisions invisible rather than silently reapplying them.
- Group-level decisions apply to every occurrence in the group unless an occurrence-level decision
  overrides it for that one occurrence. No decision (the default) is treated the same as an
  explicit `pseudonymize` — there is no separate "pending" state. A decision resolves to a coarse
  `accepted/kept/rejected` status for display: `rejected` (false positive) suppresses the Review UI
  highlight entirely, `kept` stays highlighted but visually distinguishable, and the default/
  `accepted` case renders as a normal highlight.
- This is not pseudonymization, placeholder generation, text replacement, or export — only a
  reviewer's recorded intent for later stages to consume.

## Privacy rules

- **Metrics-only artifacts** (`audit_result`, `quality_report`) contain counts, statuses, reasons,
  coverage, and confidence; they contain no page text or raw entity values.
- **Text artifacts** contain extracted text and therefore may contain PII. `reading_text` is subject
  to the same boundary as technical raw, readable, layout, block, and PII-input text. They remain
  under the local document-store root and are never logged or committed. Additive `text_geometry`
  stores only offsets and page-local bounds (no raw line text); `structured_content` stores offsets
  plus short labels/headings but no duplicated field values or table contents. Both follow the same
  sensitive-artifact handling — geometry offsets/bounds and structured labels must never be logged —
  and benchmark loaders do not copy their payloads into summaries. Additive `quality_evidence`
  (OCR L14, extended by L15's noise/token artifact evidence) is metrics-only by construction —
  offsets, counts, flags, page zones, coarse bounds, and stable reason codes, with an integer-only
  `details` map — so it carries no raw text (L15 never stores a suspicious token's own characters,
  only its location and shape-derived counts); it still lives inside the sensitive text artifact and
  is never logged or committed, and benchmark loaders ignore it.
- **PII and review artifacts** contain spans and may contain raw entity values. They remain local and
  are never written to application logs.
- **Private benchmark reports** remain under `volumes/` and pass through `privacy_guard.py` before
  writing. Published documentation uses aggregate figures only.
- **Feedback JSONL** follows the separate boundary above; it must not be described as a hard
  privacy-by-construction guarantee because optional free text is accepted.
- **Entity groups** store only a SHA-256 fingerprint (never the raw normalized value) plus
  occurrence ids and projection counts. **Review-decision JSONL** stores offsets/ids/decision/scope
  plus an optional free-text `note` (same policy as feedback `comment`: no copied document text, OCR
  text, or raw PII); it is not dev-gated, so it must never be logged either.

## Versioning and lineage

- Existing artifacts carry explicit versions (`audit_version`, `ocr_version`,
  `quality_report_version`, `pii_version`). New artifact types follow the same convention.
- Artifacts are append-only: a rerun creates a new artifact id and never mutates the prior result.
- `text_result` references the original and audit artifacts; `quality_report` references that exact
  original/audit/text triple; `pii_result` references its exact text artifact. The review-decision
  overlay references the exact `pii_result.id` it was recorded against (not yet `text_result.id`); a
  future formal `review_result` artifact would extend this chain explicitly.
- Downstream results whose input changes are stale and are never silently reused.
- Additive optional fields preserve legacy artifact readability. Audits written before OCR L4 have
  no `needs_ocr`; routing falls back to `has_text_layer`.
