# Engine Artifacts

The engine is a chain of stations that each append an **immutable JSON artifact** referencing its
input. This document defines every artifact — existing and planned — and its privacy rules. It is
the contract between the sub-engines and the source of truth for "what may contain raw text or PII".

Storage today (see the root [README](../../README.md#storage-layout)):

```text
volumes/
├── uploads/<document_id>.<ext>                     # byte-identical original only
└── document-data/<document_id>/
    ├── document.json                               # metadata + original artifact
    └── artifacts/<artifact_id>.json                # audit_result / text_result / pii_result / …
```

`volumes/` is entirely git-ignored (`/volumes/*`). **No artifact is ever committed.**

## Legend

- **Raw text?** may the artifact contain extracted document text?
- **PII?** may it contain PII values (as spans of the stored text)?
- **Persisted?** written to disk as an immutable artifact?
- **Local-only?** must it never leave the machine / never be committed?
- **DB-index later?** a candidate to index in a future database (see
  [target-architecture](target-architecture.md#database-considerations))?

## Artifact catalogue

| Artifact | Status | Purpose | Source (station) | Raw text? | PII? | Persisted? | Local-only? | DB-index later? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `document.json` | ✅ today | Document metadata + embedded `original_artifact` | Upload | no (filename only) | filename may be sensitive | yes | yes | yes (index/state) |
| `original_artifact` | ✅ today | Byte-identical source pointer + digest | Upload | no | no | yes (in `document.json`) | yes | yes |
| `audit_result` | ✅ today | Per-page text-layer stats + **quality verdict/routing** (metrics only) | Audit | **no** (counts only) | no | yes | yes | yes (routing/state) |
| `quality_report` | 🔜 planned (OCR L4) | Per-document OCR/text quality summary: coverage, source mix, confidence | Audit/OCR | **no** | no | yes | yes | yes (regression) |
| `ocr_result` | ◻ conceptual | Per-page OCR output (text + confidence + boxes) | OCR | **yes** | yes | folded into `text_result` pages today | yes | no (large/raw) |
| `text_layer_result` | ◻ conceptual | Per-page extracted text-layer output | OCR | **yes** | yes | folded into `text_result` pages today | yes | no |
| `best_text_result` | ✅ today (as `text_result`) | **Canonical text** for PII + review | OCR/Text | **yes** | yes | yes (`text_result`) | yes | no (large/raw) |
| `layout_text_result` | 🔜 planned (OCR L5–6) | **Human-readable** text: paragraphs, reading order, tables | OCR/Text | **yes** | yes | yes | yes | no |
| `structured_document_result` | 🔜 planned (OCR L7) | Structured output: tables, sections, key-value pairs | OCR/Text | **yes** | yes | yes | partial (structure yes, values no) |
| `pii_result` | ✅ today | Detected PII spans + offsets + per-type counts, **plus an additive Engine-5 candidate-validation summary and per-entity verdict** | PII (+ post-processing) | via spans | **yes** | yes | yes | yes (counts/offsets, not values) |
| ~~`pii_validation_result`~~ | ✅ delivered differently (PII L5) | Considered as a separate artifact, **not built**: candidate validation is additive fields/summary directly on `pii_result` instead (no independent lineage — see [ADR-0013](../adr/0013-pii-candidate-validation.md)) | — | — | — | — | — | — |
| `review_result` | 🔜 planned (Review L2+) | Human confirm/reject/add/comment over a `pii_result` | Review | via spans | yes | yes | yes | yes |
| `benchmark_result` | ✅ today (private report) | Aggregate routing + PII P/R/F1 regression report | Benchmark runner | **no** (guarded) | **no** (guarded) | report file(s) | yes | yes (trend) |

`◻ conceptual` = a distinct notion in the model that is currently *folded into* another artifact
rather than emitted separately; it may be split out if a station needs it independently.

## The two text artifacts — why they are separate

This is the most important distinction in the model:

- **`best_text_result` (canonical).** Correctness-first text. **This is the only text PII and review
  run against.** Offsets are stable Unicode codepoint offsets into this string. It is never rewritten
  by layout passes or AI.
- **`layout_text_result` (human-readable).** A rendering for humans — paragraphs, reading order,
  tables. It may reflow text; therefore it must **not** be the PII input, or offsets would drift.

Keeping them separate means: a nicer human rendering can evolve freely without ever endangering PII
offset integrity. Today only the canonical text exists (`text_result`); `layout_text_result` arrives
at OCR L5–L6.

## Privacy rules per artifact class

- **Metrics-only artifacts** (`audit_result`, `quality_report`, `benchmark_result`) contain **no
  page text and no PII values** — only counts, statuses, types, offsets, coverage. `audit_result`
  stores per-page quality *verdicts*, never the page text. `benchmark_result` is additionally
  protected by `privacy_guard.py`, which blocks any write containing a forbidden field name or a
  PII-shaped string.
- **Text artifacts** (`best_text_result`, `layout_text_result`, `structured_document_result`,
  `ocr_result`, `text_layer_result`) contain raw extracted text and therefore PII. They live only
  under the git-ignored document-data root, are never logged, and are **not** DB-indexed as raw text.
- **PII artifacts** (`pii_result`, `review_result`) contain PII *values* (as spans of the stored
  text) and stay inside the protected artifact directory in cleartext; they are never written to
  logs. Candidate validation (Engine-5) is additive fields/summary on `pii_result` — counts and
  reason codes only, never a value — not a separate PII artifact.

## Versioning

- Each artifact type carries an explicit version field (`audit_version`, `ocr_version`,
  `pii_version`) so its schema can evolve without breaking older artifacts. New artifact types
  (`quality_report`, `layout_text_result`, `structured_document_result`, `review_result`) will
  follow the same `<name>_version` convention.
- Artifacts are **append-only and immutable**: a re-run creates a new `artifact_id`, never mutates an
  existing one. "Latest" is resolved by creation time.
- **Lineage** is explicit: `text_result` references its `input_artifact_id` (original) and
  `input_audit_artifact_id` (audit); `pii_result` references `input_text_artifact_id`. New artifacts
  extend this chain (`review_result` → `pii_result` + `text_result`). Downstream artifacts whose
  input changed are marked **stale**, never silently reused.
- **Backward compatibility** is preserved additively: e.g. audit artifacts written before the L3
  quality gate have no `needs_ocr`, and routing falls back to the original `has_text_layer` rule.
  New fields are optional so older artifacts still validate.
