# ADR-0028: PII Intake via Document Text Package v1 + PII L12 Overlap Resolution

## Status

Accepted / implemented additively — 2026-07-09. PII now consumes the OCR Output Contract v1
Document Text Package ([ADR-0027](0027-ocr-output-contract-v1-strategy.md)) through a dedicated
intake adapter instead of reaching into `text_result`/`TextContent` internals, and resolves
overlapping/duplicate detected candidates deterministically (PII **L12**). This adds
`backend/app/services/pii_input.py` (the adapter and internal `PiiInputDocumentV1` model) and
`backend/app/services/pii_overlap.py` (the deterministic resolver), plus additive, optional
`pii_result` fields (`PiiEntity.provenance`, `PiiContent.input_contract`,
`PiiContent.overlap_resolution`). Technical raw text remains the **primary and only active
detection input**; existing PII API routes and the frontend review flow are unchanged.

This builds on [ADR-0016](0016-engine-maturity-levels-0-19.md) (0–19 scale),
[ADR-0018](0018-ocr-pii-implementation-plan.md) (OCR stays ahead of PII),
[ADR-0019](0019-canonical-reading-text-and-technical-raw-contract.md) (technical-raw vs
canonical-reading contract), [ADR-0021](0021-pii-entity-grouping-and-review-decisions.md)
(entity grouping + review-decision overlay), and [ADR-0027](0027-ocr-output-contract-v1-strategy.md)
(the contract PII now consumes).

## Position in the sequence

This is the **first downstream consumer step after the OCR Output Contract v1 stabilization**. It
advances PII from **L11** to **L12** (overlap resolution) and makes PII a *consumer of the contract*,
not of OCR internals, as [ADR-0027](0027-ocr-output-contract-v1-strategy.md) intended. It does not
switch the active PII detection input away from technical raw text — that still requires the tested
`text_lineage_map` separation gate
([`ocr-layout-text-contract.md`](../engine/ocr-layout-text-contract.md#invariants)).

## Context

Before this change, `pii_service._analyze_text` reached directly into four `TextContent` fields
(`text`, `pages`, `reading_text`, `reading_text_map`) to decide what to detect on and how to project
results. That coupled PII to OCR internals exactly where [ADR-0027](0027-ocr-output-contract-v1-strategy.md)
wants a stable boundary, and it left overlapping/duplicate detections (the same span found by two
recognizers, a longer span containing a shorter one, two types claiming overlapping text) unresolved
at the engine level — only a display-layer resolver existed (`piiHighlights.ts`).

## Decision

### 1. PII consumes the contract through an intake adapter

`PiiInputAdapter.from_text_artifact` builds the `DocumentTextPackageV1` from the latest text artifact
(the ADR-0027 boundary) and adapts it into a stable internal `PiiInputDocumentV1`. Detection then
reads only from that model. The adapter is the **single bridge** and concentrates the only remaining
coupling: it reads `pages` for per-page detection segmentation (the contract exposes only the
combined raw text in v1, so segmentation is passed alongside it and validated to reconstruct the raw
text exactly). The package is never mutated, and no raw text snippet is copied into any hint/warning
metadata — only the text sources themselves carry text, because they *are* the text layers.

Consumer rules follow [ADR-0027](0027-ocr-output-contract-v1-strategy.md) exactly:

- **raw text is the primary detection source** (PII detects on raw exclusively today);
- **canonical reading text is contextual/secondary**; layout text is presentation only;
- **`structured_content` is a hint layer**; **quality/noise evidence is trust/uncertainty context**
  — attached, never applied to silently suppress an entity;
- canonical text is never treated as authoritative, and missing optional layers never crash PII.

### 2. Contract status handling

- **valid** → PII behaves normally.
- **degraded** (missing optional layers/lineage) → PII continues as long as raw text exists and
  records the degraded status + warning codes on the result.
- **invalid** → a *structurally* invalid package (unsupported version, malformed source roles,
  unresolvable document id) is rejected with a controlled `422`. A package that is invalid *only*
  because its raw text is empty is **not** a hard error: it stays the existing benign empty-result
  path (`flags=["empty_text"]`), preserving backward compatibility.

### 3. Deterministic overlap resolution (PII L12)

`resolve_pii_overlaps` runs after candidate validation and before reading-text projection, over
globally-offset entities. It is deterministic and provenance-preserving:

- **Exact duplicate** (identical start/end/type) → merge into one survivor; combine recognizer names
  and record merged candidate ids. Reason `exact_duplicate` (also `recognizer_duplicate` when
  recognizers differ), decision `merged_provenance`.
- **Same type, overlapping** (a connected cluster) → keep the single strongest span (longest, then
  highest score, then earliest start, then recognizer name, then id) and drop the rest — but record
  their ids on the survivor and count them, so nothing is dropped *silently*. Reason `nested_entity`
  or `same_type_overlap`; decision `longer_span_selected` or `stronger_confidence_selected`.
- **Different type, overlapping** → **never dropped**. Both entities are preserved and flagged for
  review (`conflicting_entity_type` + `ambiguous_overlap_review_required`), so a human resolves the
  conflict instead of the engine guessing a cross-type precedence.

Entity offsets, text, and scores are never modified — only which entities survive and their
`provenance`.

### 4. Provenance and contract transparency on `pii_result`

Three additive, optional fields let the immutable artifact explain what happened, all structural
(reason codes, counts, recognizer names, ids) and never a copy of raw text:

- `PiiEntity.provenance` (`PiiEntityProvenance`): detection source/role, contributing recognizers,
  merged-candidate count, overlap reason codes, review flag, and superseded candidate ids.
- `PiiContent.input_contract` (`PiiInputContractSummary`): the contract version/status/package id PII
  consumed, which optional layers were present, and the contract's warning/missing-capability codes.
- `PiiContent.overlap_resolution` (`PiiOverlapResolutionSummary`): applied flag and
  input/output/merged/dropped/review counts plus per-reason-code counts.

## Why a conservative cross-type policy

L12 explicitly allows overlapping candidates to be *suppressed or flagged*, with unresolved conflicts
staying visible in review. This ADR flags cross-type conflicts for review rather than auto-suppressing
one type in favour of another (e.g. structured id > generic id, ADDRESS > LOCATION). That keeps the
engine from silently discarding distinct entities and defers a specific cross-type precedence table to
a later refinement, once benchmark/review evidence justifies concrete rules. Same-type
merges/drops are safe (they are the same entity) and are always recorded.

## Explicitly not included

- No change to the active PII detection input — still technical raw text; the `text_lineage_map`
  separation gate is unchanged and not bypassed.
- No change to detection, candidate validation, recognizers, profiles, the `DocumentTextPackageV1`
  schema, OCR extraction, or runtime/worker behavior.
- No pseudonymization, redaction, reconstruction/export, dictionary/lexicon, multi-OCR, or LLM.
- No cross-type auto-suppression precedence table (deferred, see above).
- No change to the review-decision overlay, the review UI, or benchmark payloads.

## Consequences

- PII depends on the OCR Output Contract v1 boundary, not OCR internals; future OCR changes behind
  the contract no longer ripple into PII.
- The final entity set is deterministically de-duplicated and overlap-resolved, with an auditable
  provenance trail and per-run overlap/contract summaries on the immutable artifact.
- Backward compatibility holds: baseline raw-text detection is byte-identical, degraded packages with
  raw text still process, empty text still yields an empty result, and legacy artifacts (without the
  new optional fields) stay valid.
