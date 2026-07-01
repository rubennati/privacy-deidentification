# ADR-0008: Separate original-upload and document-data storage

## Status

Accepted — 2026-07-01

## Context

The file-based pilot originally stored original uploads, metadata sidecars, and derived JSON
artifacts below one upload root. That made the upload volume serve incompatible roles and made it
hard to reason about backup, retention, access, and deletion boundaries. The application still
does not need a database, but each document's application-managed data needs a clear home that is
separate from its byte-identical original.

## Decision

- Configure two equal-level, non-nested roots: `UPLOAD_STORAGE_DIR` for originals and
  `DOCUMENT_DATA_DIR` for metadata and results. Continue accepting `UPLOAD_DIR` only as a legacy
  configuration fallback for the original-storage root.
- Store each original as `<document_id>.<validated_extension>` under the upload-storage root.
  Never use a client-supplied filename in a storage path; keep its Unicode display value only in
  metadata.
- Store application data as
  `<document_id>/document.json` and `<document_id>/artifacts/<artifact_id>.json` below the
  document-data root. Validate document and artifact ids as 32-character lowercase UUID hex
  values before using them in paths.
- Create the empty `artifacts/` directory with `document.json` during upload. Audit, OCR/Text, and
  PII continue to emit immutable, atomically finalized JSON artifacts there.
- On deletion, remove the UUID-named original and exactly the validated document-data directory.
- Do not migrate, move, or delete old local data automatically. Older development data remains
  untouched but undiscovered; developers can re-upload it or reshape a backed-up copy manually.
- Keep each individual file finalization atomic within its own filesystem. There is no atomic
  transaction across the two mounted roots; an ordinary metadata failure triggers best-effort
  rollback of both the finalized original and the document-data directory.

This ADR supersedes only the co-located storage-path details in ADR-0001, ADR-0002, and ADR-0003.
Their architecture, integrity, and immutable-artifact decisions remain in force.

## Consequences

- The upload directory has one auditable responsibility and can no longer accumulate sidecars or
  derived cleartext results.
- Metadata and all derived artifacts for one document share a deletion and retention boundary.
- Readiness must verify both mounts, and local deployments must provide both writable directories.
- Existing local development records are not listed after upgrade until they are explicitly
  re-uploaded or manually migrated.
