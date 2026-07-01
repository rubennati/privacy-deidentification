# Decisions

Architecture decisions are recorded as ADRs under `docs/adr/`.

- [ADR-0001](../docs/adr/0001-stack-and-architecture.md) — Stack and architecture
  (Docker-first, FastAPI backend, React/Vite SPA behind nginx).
- [ADR-0002](../docs/adr/0002-upload-core-artifact-metadata.md) — Upload/Core integrity
  metadata and embedded original artifact in the existing JSON sidecar.
- [ADR-0003](../docs/adr/0003-audit-station.md) — Synchronous Audit v1 with immutable,
  file-based JSON result artifacts.
- [ADR-0004](../docs/adr/0004-ocr-workstation.md) — Synchronous per-page OCR/text routing with
  replaceable PaddleOCR and PDF-rendering adapter boundaries.
- [ADR-0005](../docs/adr/0005-pii-workstation.md) — Synchronous, detection-only PII labeling over
  immutable text artifacts with a lazy Presidio/spaCy adapter.
