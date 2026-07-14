# ADR-0037: PII Result Integrity v1

## Status

Accepted and implemented on `pii-result-integrity-v1`.

## Context

A PII result was not trustworthy end to end. Same-type connected overlap clusters could suppress
independently covered spans; the PII intake adapter treated an OCR contract with missing raw text as
a successful empty result; worker completion and the review contract used “latest” reads after an
operation already had exact artifact identity; and frontend nullable state could retain private text
or render no highlights while an exact contract was unavailable.

## Decision

- Text trust is fail-closed. A raw source explicitly available in a structurally valid or degraded
  package is trustworthy/analyzable; degradation may describe missing optional presentation or
  evidence layers, not missing required raw text. `missing_required_raw_text` distinguishes no text
  detected from other structural blockers (untrusted/incomplete contract). Extraction exceptions
  are technical failures and produce no PII artifact. The current OCR contract cannot positively
  certify a genuinely blank source document, so whitespace/empty output is not treated as confirmed
  blank and cannot produce a PII result.
- PII accepts only a Document Text Package whose required raw source is available. Empty/missing raw
  text remains an invalid OCR/Text package and produces no PII artifact. A valid empty result means
  trustworthy non-empty text was analyzed successfully and produced zero entities.
- Exact duplicates merge and fully contained same-type candidates may be superseded. Partial
  same-type overlaps survive because either span may cover PII outside the other. Cross-type
  overlaps remain preserved and review-flagged.
- Artifact storage exposes exact text and PII reads. Worker completion clients fetch the recorded
  `result_artifact_id`. The entity-contract endpoint requires both PII and text artifact ids,
  verifies their lineage, and builds review state, anchors, ranges, and entities from that one
  immutable snapshot. Missing snapshots are unavailable; mixed snapshots are incompatible; neither
  is degraded-valid.
- Frontend contract loading is discriminated (`idle`, `loading`, `not_found`, `incompatible`,
  `error`, `ok`) and
  keyed by document, PII artifact, and text artifact. A result is current only in `ok`. Document
  identity changes synchronously clear loaded private text and derived state before new requests.

## Consequences

The entity-contract request is intentionally breaking: callers must provide exact artifact ids.
Legacy PII artifacts whose referenced text artifact is absent cannot produce a valid entity
contract. No replacement, reconstruction, detection-input switch, or anchor-first package is added.

This is a cross-cutting integrity correction, not an engine maturity-level advance. OCR/Text remains
L15 and PII remains L14.
