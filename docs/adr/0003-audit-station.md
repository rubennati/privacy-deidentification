# ADR-0003: Synchronous file-based audit station

## Status

Accepted — 2026-07-01

## Context

Verified original artifacts need lightweight structural analysis before a later OCR station can
decide how to process them. Audit v1 must remain independent from OCR and preserve the existing
database-free architecture.

## Decision

- Run Audit v1 synchronously through document-scoped `POST` and `GET` endpoints.
- Verify the stored original against its SHA-256 before analysis and dispatch only by its
  server-verified MIME type.
- Use pypdf for PDF page/text-layer statistics, python-docx for body-paragraph statistics, and
  Pillow for PNG/JPEG dimensions. Audit does not persist extracted document text.
- Store each result as an immutable JSON artifact under
  `uploads/artifacts/{document_id}/{artifact_id}.json`, using a temporary file, `fsync`, and an
  atomic same-filesystem rename.
- Remove all derived artifacts when their document is deleted.

## Consequences

- Multiple audits can coexist; `GET` returns the newest valid result.
- Legacy records without an original artifact cannot be audited and return a conflict.
- Analysis is request-bound; there is deliberately no queue, run resource, or workflow engine.
