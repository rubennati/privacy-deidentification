# ADR-0027: OCR Output Contract v1 — Document Text Package

## Status

Accepted / implemented additively — 2026-07-09. The v1 contract boundary is implemented as a
derived, read-only package built on demand from existing immutable `text_result` artifacts. It adds
`DocumentTextPackageV1`, `DocumentTextSourceV1`, `DocumentTextPackageValidationSummary`, a
builder/validator service, and `GET /api/documents/{document_id}/text-package` with
`contract_version = "1.0"`. Existing OCR endpoints remain backward-compatible, the package is not
persisted as its own artifact, and PII is **not migrated yet** at the time of this ADR: PII still
uses technical raw text from `text_result.text`.

**Update (2026-07-09):** PII is now the first migrated consumer — it intakes this package through a
dedicated adapter and resolves overlapping candidates deterministically (PII L12). Technical raw
text remains PII's primary and only active detection input. See
[ADR-0028](0028-pii-intake-document-text-package-v1.md).

This builds on
[ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 maturity scale),
[ADR-0018](0018-ocr-pii-implementation-plan.md) (OCR stays ahead of PII),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md) (technical-raw vs
canonical-reading contract), and [ADR-0023](0023-runtime-worker-architecture.md) (worker
runtime). It elevates the existing five-layer text model in
[`ocr-layout-text-contract.md`](../engine/ocr-layout-text-contract.md) into a single, versioned
**output contract** that downstream engines can consume. It changes no OCR extraction algorithm,
runtime/worker behavior, or existing text artifact semantics.

## Position in the sequence

This is the **OCR/Text stabilization step after L15** — a cross-cutting milestone, not a numbered
level (the 0–19 scale, [ADR-0016](0016-engine-maturity-levels-0-19.md), is unchanged). **PII is a
consumer of the contract and a downstream migration target, not part of this implementation:** PII
L12 overlap resolution and other consumer work follow the stabilized boundary. Future OCR capability
tracks — dictionary/lexicon evidence, correction suggestions, multi-OCR/source agreement,
feedback-driven improvement — **enrich the contract additively without breaking consumers**; their
formal level numbering stays governed by ADR-0016 and future ADRs.

## Context

OCR/Text has matured to L15: technical raw text, canonical `reading_text` (L10.5/L12/L13),
`layout_text_result`, `structured_content` (L11/L13), `text_geometry` (L10), the offset-only
`reading_text_map`, and additive metrics-only `quality_evidence` (L14 provenance/lineage +
L15 noise/token evidence). These are strong building blocks, but today a consumer such as PII
still reaches into individual `text_result` fields and OCR-specific implementation details
(pypdf/PaddleOCR provenance, reading-order heuristics, worker internals) to decide what text to
use.

That coupling is the problem this ADR addresses. As OCR/Text becomes more capable and gains
future evidence sources (dictionary/lexicon, multi-OCR agreement, correction *suggestions*,
local-AI hints), and as more consumers appear (Review UI, pseudonymization, document/invoice
analysis, summarization, export/reconstruction, local AI), each consumer independently learning
OCR internals multiplies the blast radius of any OCR change and blurs the engine boundary
[ADR-0018](0018-ocr-pii-implementation-plan.md) depends on.

The strategic direction is: **OCR/Text must be an independent, reusable module with a stable,
versioned output contract.** PII should consume that contract, not OCR internals.

## Decision

Implement, **after L15 and before further OCR/Text capability levels**, the **OCR Output Contract
v1**, also called the **Document Text Package** — a single, versioned package that exposes the
already-produced text layers, structure, lineage, and evidence together with an explicit trust
status, so consumers depend on the contract rather than on `text_result` internals or the external
OCR/PDF tool that produced them.

The implementation is additive: it builds the package from the newest existing text artifact on
request, never mutates the source artifact, and does not change `GET/POST .../ocr` response shapes.

### Why an independent module + contract

- **Reusability.** The same stable text output should serve PII detection, Review UI,
  pseudonymization, document/invoice/contract analysis, summarization, export/reconstruction,
  and future local AI — not just PII.
- **Decoupling.** A change inside OCR (a new reconstruction heuristic, a second OCR engine, a
  swapped PDF library) must not ripple into consumers as long as the contract holds. Consumers
  code against roles and a version, not against pypdf/PaddleOCR specifics.
- **Boundary integrity.** It makes [ADR-0018](0018-ocr-pii-implementation-plan.md)'s "OCR stays
  ahead of PII" boundary concrete: PII becomes a *consumer of a contract*, so OCR can advance
  without dragging PII's input surface with it.

### Why package raw / canonical / layout / structured / evidence together

Consumers need different views of the same document, and they need to know how those views
relate. Packaging them together — with lineage and evidence — lets a consumer pick the right
view for its job and reason about trust in one place, instead of stitching together separate
fields and re-deriving provenance:

- **raw** = the authoritative, offset-stable source text (today's `text_result.text`);
- **canonical** = the human-readable derived reading text (`reading_text`);
- **layout** = a visual/debug rendering (`layout_text_result`);
- **structured** = semantic hints (`structured_content` tables/fields/sections);
- **evidence** = trust/uncertainty hints (`quality_evidence`, including L15 noise/token items).

### Why versioned

A `contract_version` lets consumers detect the shape they were built against, lets OCR evolve
the package additively, and makes breaking changes explicit and negotiable rather than silent.
Legacy `text_result` artifacts predating the contract must remain readable (the package is
derivable from them or marked accordingly).

### Why a contract status (valid / degraded / invalid) matters

Extraction is not always trustworthy (a scanned page with no OCR runtime, a broken text layer,
an encrypted PDF, heavy noise). A `contract_status` plus `warnings` / `blockers` /
`missing_capabilities` lets a consumer decide *before* using the text: PII may lower confidence
or force review on `degraded`, and must refuse to treat `invalid` as good. This encodes the
existing "fail loud, never silently degrade" invariant
([`target-architecture.md`](../engine/target-architecture.md#design-invariants-the-engine-must-keep))
at the contract boundary.

### Why external OCR/PDF tool output must be normalized

pypdf, PaddleOCR, python-docx, and any future engine each emit tool-specific shapes,
coordinate units, and quirks. Those must be normalized by the OCR adapter/normalization layer
**before** crossing the contract boundary, so a consumer never sees, and never has to special-
case, a specific tool. Swapping or adding an engine then stays an OCR-internal concern.

### Why this helps future PII, AI, export, and document analysis

One stable, trustworthy, role-labelled, versioned text package is exactly what every later
consumer needs: PII detection/confidence, context-preserving pseudonymization, key-value and
invoice/contract analysis, summarization, export/reconstruction, and local-AI plausibility all
consume the same contract instead of re-learning OCR internals.

## High-level shape (v1 schema)

The Document Text Package packages what OCR/Text already produces:

- `contract_version` — package shape version, currently `"1.0"` (independent of per-field versions).
- `document_id` / source `text_result` `artifact_id` — lineage to the immutable artifact.
- `technical_raw_text` — authoritative, offset-stable source text (today `text_result.text`).
- `canonical_reading_text` — human-readable derived text (`reading_text` + status/flags).
- `layout_text` — visual/debug rendering (`layout_text_result`), may be absent.
- `structured_content` — semantic hints (tables/fields/sections), may be absent.
- `reading_text_map` / lineage — offset mapping from reading fragments back to raw (partial
  today; a full `text_lineage_map` remains future work).
- `quality_evidence` — provenance / reconstruction / page-zone / lineage-coverage evidence
  (L14), plus L15 `noise_evidence` (glyph/token-shape/confusion/spacing + `ocr_noise_summary`).
- processing metadata — source mix (text-layer vs OCR), engine/reconstruction summary, and (at
  L16) reproducible engine settings; metrics only, no raw text.
- `contract_status` — `valid` / `degraded` / `invalid`, with `warnings`, `blockers`, and
  `missing_capabilities`. `invalid` is reserved for blockers such as missing required raw text,
  invalid document id, unsupported contract version, or malformed source roles; `degraded` is used
  when optional layers or lineage/evidence signals are missing; `valid` means no warnings/blockers.

### Source roles

- **raw** — authoritative source text; the offset coordinate system.
- **canonical** — human-readable derived text; convenient, not authoritative.
- **layout** — visual/debug text; presentation only.
- **structured** — semantic hints; context, not a source of truth.
- **evidence** — trust/uncertainty hints; advisory, never a correction.

### Consumer rules (PII first, then others)

- PII **may** use `raw` as its primary source (today it uses raw exclusively).
- PII **may** use `canonical` as a contextual/secondary source.
- PII **may** use `structured_content` as a hint layer.
- PII **may** use quality/noise evidence to adjust confidence or raise review flags.
- PII **must not** assume `canonical` is authoritative.
- PII **must not** break if optional evidence/structure/layout is absent.
- Other engines (Review, pseudonymization, analysis, export, local AI) consume the **same**
  package under the same rules.
- Switching PII's *active detection input* away from `raw` still requires the tested
  `text_lineage_map` separation gate in
  [`ocr-layout-text-contract.md`](../engine/ocr-layout-text-contract.md#invariants); the
  contract does not bypass it.

## Explicitly not included yet

- No persisted package artifact; the package is derived on request.
- No change to `text_result.text`, `reading_text`, `structured_content`, `quality_evidence`,
  existing OCR endpoints, the active PII input, PII decisions, benchmark payloads, or runtime
  behavior.
- No `text_lineage_map`, no PII-input switch, no pseudonymization / redaction / export.
- No new OCR/PDF engine, no dictionary/lexicon, no multi-OCR, no local LLM (those remain
  deferred additive **evidence, not truth**, and — once built — plug into this contract).
- No decision on the final numbering of OCR/Text L16+; the 0–19 scale (ADR-0016) is unchanged
  and this contract is a cross-cutting stabilization milestone, not a numbered level.

## Consequences

- OCR/Text gains an implemented, versioned package boundary; consumers can be migrated to it
  incrementally without an OCR behavior change.
- Future OCR evidence/engine work becomes additive behind the contract, keeping the OCR↔PII
  boundary and blast radius small.
- Existing consumers keep working: PII still reads technical raw text directly, and the new
  `text-package` endpoint is additive beside the backward-compatible OCR endpoints.
