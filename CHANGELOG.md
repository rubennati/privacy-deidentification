# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Docker-first foundation: `docker compose up -d` serves the app at `http://localhost:8080`.
- FastAPI backend with health checks (`/api/health/live`, `/api/health/ready`) and a
  validated upload endpoint (`POST /api/uploads`).
- React + Vite + TypeScript + Tailwind upload page (Screenshot 1): click, drag & drop, and
  paste (Ctrl+V) upload with client- and server-side validation.
- AI-collaboration workspace (`.ai/`), `AGENTS.md`/`CLAUDE.md`, and ADR-0001.
- `Makefile` with shared quality commands (lint, typecheck, test, build, up, down).
