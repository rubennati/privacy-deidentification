# ADR-0002: Upload/Core artifact metadata

## Status

Accepted — 2026-06-30

## Context

The file-based upload MVP needs an auditable identity for the byte-identical original before
later extraction or de-identification stages are introduced. The project intentionally has no
database or queue at this stage.

## Decision

- Compute SHA-256 while streaming the upload to storage.
- Derive a canonical MIME type from validated content signatures; DOCX additionally requires
  minimal OOXML ZIP structure.
- Embed one independently identified `original` artifact in the existing document JSON
  sidecar.
- Finalize both binary and sidecar through same-filesystem temporary files and atomic renames,
  with best-effort rollback when ordinary finalization errors occur.
- Keep legacy sidecars readable; their new integrity fields remain absent until re-uploaded.

## Consequences

- New originals have stable integrity and provenance metadata without adding infrastructure.
- Two files cannot be committed as one filesystem transaction; a process or host crash between
  renames can still leave an orphaned binary, but never a finalized sidecar before its binary.
- Existing sidecars are not backfilled automatically.
