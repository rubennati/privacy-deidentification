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
    ├── artifacts/<artifact_id>.json                # audit/text/PII and future artifacts
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
| `best_text_result` | ✅ today as `text_result` | canonical text used by PII and review | yes | immutable artifact |
| `ocr_result` / `text_layer_result` | ◻ conceptual | source-specific page output | yes | folded into `text_result` today |
| `quality_report` | 🔜 OCR L7 | source mix, coverage, confidence summary | metrics only | immutable artifact |
| `layout_text_result` | 🔜 OCR L8–L9 | readable text at L8; layout-aware blocks at L9 | yes | immutable artifact |
| `structured_document_result` | 🔜 OCR L11 | tables, sections, key-value regions | yes | immutable artifact |
| `pii_result` | ✅ today | detected spans, offsets, counts, PII L6–L8 validation fields, and L9 run settings | yes | immutable artifact |
| `review_result` | 🔜 Review L8 | lineage-bound human decision overlay on `pii_result` | yes | immutable artifact |
| `benchmark_result` | ✅ today as private reports | routing and PII quality metrics | guarded report metadata and metrics | local report files |

`◻ conceptual` means the concept is currently embedded in another artifact and may be separated
only when a later station requires it.

## Canonical and readable text

Four distinct text layers plus a lineage map, fixed by the
[OCR/Layout text contract](ocr-layout-text-contract.md):

- **`best_text_result`** is the **canonical**, correctness-first text represented today by
  `text_result`. It is the single source of truth and coordinate system; PII offsets always resolve
  to this text. It is **not** redefined to mean readable text.
- **`pii_input_text`** (new, optional, additive; internal) is a **detection-optimised** view that
  preserves logical blocks/roles/table/address structure. In v1 it equals canonical text; it may
  diverge later **only** with a tested lineage map (round-trippable to canonical). Not user-facing,
  not a rival source of truth.
- **`readable_text`** (new, optional, additive) is a **human-readable** normalisation of the same
  content (whitespace/paragraph/hyphenation) starting at OCR L8. No PII-offset guarantee; never a PII
  input.
- **`layout_text_result`** (new, optional, additive) is a **layout-preserving** plain-text
  reconstruction (pages, blocks, columns, tables) for Review/UI, starting at OCR L9. No PII-offset
  guarantee.
- **`text_lineage_map`** (new, optional, additive) marries source (page/block/line/word) ↔ canonical
  ↔ PII-input ↔ readable ↔ layout, so PII detected internally can be shown in the layout view while
  its authoritative offsets stay canonical. Long-term basis for bounding boxes and redaction.

These layers are additive and never mutate canonical text or shift PII offsets; there are **no two
unconnected source-of-truth texts** — every layer maps back to canonical (and source) via
`text_lineage_map`. Older artifacts without the new fields stay valid.

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
- **Text artifacts** contain extracted text and therefore may contain PII. They remain under the
  local document-data root and are never logged or committed.
- **PII and review artifacts** contain spans and may contain raw entity values. They remain local and
  are never written to application logs.
- **Private benchmark reports** remain under `volumes/` and pass through `privacy_guard.py` before
  writing. Published documentation uses aggregate figures only.
- **Feedback JSONL** follows the separate boundary above; it must not be described as a hard
  privacy-by-construction guarantee because optional free text is accepted.

## Versioning and lineage

- Existing artifacts carry explicit versions (`audit_version`, `ocr_version`, `pii_version`). New
  artifact types follow the same convention.
- Artifacts are append-only: a rerun creates a new artifact id and never mutates the prior result.
- `text_result` references the original and audit artifacts; `pii_result` references its exact text
  artifact. Future `quality_report` and `review_result` artifacts extend this chain explicitly.
- Downstream results whose input changes are stale and are never silently reused.
- Additive optional fields preserve legacy artifact readability. Audits written before OCR L4 have
  no `needs_ocr`; routing falls back to `has_text_layer`.
