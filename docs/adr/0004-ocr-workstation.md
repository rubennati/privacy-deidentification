# ADR-0004: Synchronous OCR/Text Workstation with adapter boundaries

## Status

Accepted — 2026-07-01

## Context

Audit v1 identifies text layers per PDF page. The next station must turn the verified original
and newest matching audit into ordered text without introducing a database, queue, workflow
engine, or a direct dependency from routing code to a heavyweight OCR implementation.

## Decision

- Expose synchronous document-scoped `POST` and `GET` OCR endpoints and store every result as an
  immutable `text_result` JSON artifact alongside audit artifacts.
- Reverify the original SHA-256 and require the newest valid audit to reference that original.
- Route each PDF page from its own audit entry: pypdf extracts existing text layers; pages without
  text are rendered through a replaceable pdf2image/Poppler renderer and passed to an OCR adapter.
- Extract DOCX body paragraphs directly and represent no synthetic DOCX pages. Represent images
  as a single OCR page. Join ordered page text with two newlines.
- Keep PaddleOCR behind an `OcrAdapter`, with lazy import and initialization. Package PaddleOCR
  and PaddlePaddle in an optional `ocr` dependency extra so ordinary quality gates load no models.
- Require explicitly provisioned local detection and recognition model directories. Do not fall
  back to runtime model downloads when model configuration is absent or invalid.
- Render OCR input pages only under the container's ephemeral `/tmp` tmpfs, never under the
  persistent upload volume.
- Return `503` when a route needs PaddleOCR but the optional runtime cannot initialize. Treat
  rendering and document-processing failures as `422`, and stale/missing station inputs as `409`.

## Consequences

- Mixed PDFs preserve page order while using OCR only where the audit requires it.
- Tests replace both OCR and rendering boundaries and need neither models, Poppler, nor network.
- The default backend image supports direct PDF/DOCX extraction but requires
  `INSTALL_OCR=true` plus a configured local model directory for image or scanned-page OCR.
  PaddlePaddle wheel availability and runtime memory remain platform constraints.
- Processing stays request-bound in v1; very large documents may eventually motivate a separate,
  explicitly approved asynchronous execution step.
