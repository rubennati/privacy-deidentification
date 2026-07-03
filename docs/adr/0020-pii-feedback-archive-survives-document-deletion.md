# ADR-0020: PII review-feedback archive survives document deletion

## Status

Accepted — 2026-07-03

## Context

Dev-only per-entity PII review feedback (`POST/GET …/pii/feedback`, ADR/Level 5 in
[review-feedback-levels.md](../engine/review-feedback-levels.md)) was persisted only as an
append-only JSONL under `document-data/{document_id}/feedback/pii_feedback.jsonl`. Per
[ADR-0008](0008-separate-upload-and-document-data-storage.md), deleting a document removes exactly
its document-data directory — which meant this feedback died with its document.

That is the right default for document content and derived artifacts (right-to-erasure friendly:
delete a document, everything derived from it disappears). But review feedback is different in
kind from OCR/PII results: it is a human's structured verdict on detection quality (entity type,
offsets, recognizer, correct/issue, optional short comment), explicitly designed from the start to
exclude document text, OCR text, and raw entity values (only an optional SHA-256 `text_hash`). Its
whole purpose (Level 14, "Feedback-to-regression workflow") is to improve PII detection later,
including for documents that have since been deleted — which the previous coupling made
impossible.

## Decision

- Add a third, separate storage root, `PII_FEEDBACK_ARCHIVE_DIR` (default
  `/data/pii-feedback-archive`, host `volumes/pii-feedback-archive/`), validated at startup to be
  disjoint from both `UPLOAD_STORAGE_DIR` and `DOCUMENT_DATA_DIR` (extends the pairwise-separation
  check from ADR-0008 to all three roots).
- Every accepted feedback write appends the **same** `PiiFeedbackRecord`, unchanged, to both:
  1. the existing per-document JSONL (used by `GET …/pii/feedback` to restore/lock UI state; still
     deleted with the document), and
  2. a single, shared, cross-document JSONL in the archive root — never touched by
     `delete_document`/`delete_document_data`.
- `document_id` is retained in the archived record (not anonymized or hashed): the goal is future
  aggregate PII-quality analysis, and knowing which document a correction came from remains useful
  even after that document is gone (e.g. to group corrections by document type or profile). This is
  a deliberate choice — teams with stricter retention requirements can layer redaction/anonymization
  or a retention job on top of the archive file without changing this ADR's storage boundary.
- The archive is write-only from the API today: no read/aggregation endpoint exists yet. Reading it
  for analysis is a manual/scripted step (mirrors how the private benchmark runner reads its own
  JSON/JSONL inputs directly), matching Level 14's still-open promotion step.
- The archive inherits the existing `ENABLE_DEV_ENGINE_SETTINGS` gate: with the gate off, neither
  copy is written and both endpoints stay `403`.

## Consequences

- PII review feedback now has two different retention boundaries depending on purpose: the
  per-document copy for UI restore (dies with the document), and the archive for long-term
  aggregate analysis (survives every document's deletion, by design).
- Operators must provision and back up a third writable mount (`volumes/pii-feedback-archive/`),
  analogous to the two existing ones; it is git-ignored like the rest of `volumes/`.
- Because `document_id` and comments persist beyond document deletion, the existing comment policy
  ("no document text, OCR text, or raw PII in comments") becomes more consequential — it is the only
  free-text field, and it now outlives the source document rather than being deleted alongside it.
- A future retention/anonymization job for the archive (e.g. periodic hashing of `document_id`, or
  time-based pruning) is a legitimate follow-up but is out of scope here; this ADR only establishes
  that the archive exists and is deliberately decoupled from document lifecycle.
- This does not change or supersede ADR-0008's boundary for document data/artifacts — only adds a
  third, independent root for this one dev-gated side-channel.
