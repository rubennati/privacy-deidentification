# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- OCR/Text extraction (worker-based, PaddleOCR) producing a clean, human-readable reading text.
- PII detection: default local GLiNER (names/organisations) plus deterministic recognizers for
  structured identifiers (IBAN, e-mail, phone, UID, tax number, birth date/place, …).
- Manual review workflow: grouped per-entity decisions (pseudonymize / keep / not PII), manual add
  of a missed entity, recorded in an immutable review result. The in-place decision popover shows
  the detected value so a reviewer can judge it.
- Private OCR/PII benchmark (`make benchmark-private`) over a git-ignored local corpus.
- Docker-first foundation: `docker compose up -d` serves the app at `http://localhost:8080`.
- FastAPI backend with health checks and a validated upload endpoint (`POST /api/uploads`).
- React + Vite + TypeScript + Tailwind upload page with click, drag & drop, and paste upload.
- Engine capability model under `docs/engine/`; AI-collaboration workspace (`.ai/`), `AGENTS.md`.

### Changed

- Reading-view PII highlights are projected **precisely per entity** onto the clean reading text
  (detection stays on the faithful raw text, so every occurrence is caught for later redaction).
- The review UI focuses on two texts (reading + raw); the layout-text view was retired.

### Fixed

- Reading-view over-marking: highlights no longer span whole paragraphs.
- Image build reliability on Colima (removed a costly per-file ownership rewrite in the venv copy;
  ~16 min stall → ~4 min build).
- ADDRESS detection no longer bleeds across a line break; jump-navigation only targets rendered
  marks; TAX_ID (Steuernummer) recall raised to full on the benchmark.
