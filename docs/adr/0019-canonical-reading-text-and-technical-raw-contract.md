# ADR-0019: Canonical reading text and technical raw-text contract

- **Status:** Accepted
- **Date:** 2026-07-03
- **Decision scope:** OCR/Text L10.5 intermediate prerequisite

## Context

`text_result.text` is byte-stable and suitable as an offset coordinate system, but PDF/OCR
extraction order can interleave columns and explode table cells. Calling that output “Canonical
Text” in the product confuses compatibility/offset stability with useful document reading order.
OCR L11 structured content must not be built before the plain-text layers have explicit roles.

## Decision

1. Preserve `text_result.text`, `text_char_count`, and `pages[].text` unchanged and label this layer
   **Technical Raw Text / Technischer Rohtext**. It remains the current PII input and offset basis.
2. Add optional versioned `reading_text` as **Canonical Reading Text / Kanonischer Lesetext** with
   `reading_text_status` (`heuristic`/`fallback`) and non-sensitive strategy flags.
3. Build reading text deterministically from trustworthy position/geometry, layout blocks, layout
   text, then safe raw order. Bounded heuristics may group obvious party columns, offer metadata,
   line-item rows, totals, and split prose, but must not invent or change values.
4. User View defaults to reading text when available. Dev View retains reading, raw, and layout
   modes. An optional offset-only `reading_text_map` may safely project existing raw PII findings
   into reading mode. Entities still unmapped may use their existing raw entity value in memory for
   one unique exact or conservative format-normalized reading-text match; ambiguous matches remain
   raw-only. Projection metadata stores offsets and a method enum, never another text copy.
5. Reading text is an intended future PII/typed-placeholder candidate, but no input switch is
   permitted until a tested lineage map translates reading spans to raw/source coordinates.

## Consequences

- Legacy artifacts remain valid and all current PII offsets remain stable.
- New text artifacts contain another sensitive text field under the existing protected artifact
  boundary; benchmark summaries must ignore its contents.
- The builder is deterministic, adapter-bound to existing pypdf/PaddleOCR geometry, and has an exact
  synthetic quote fixture. No dependency or external/LLM rewriting is introduced.
- OCR L11 may now add structured tables/fields/sections without overloading either plain-text layer.
- The reading projection is a display/review bridge, not the complete round-trippable
  `text_lineage_map`; it does not satisfy the gate for changing the active PII input.

## Non-scope

No PII input switch, full source/view lineage map, pseudonymization, placeholder mapping,
redaction/export, worker/queue, database, or artifact mutation.
