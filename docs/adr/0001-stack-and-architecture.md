# ADR-0001: Stack and architecture

## Status

Accepted — 2026-06-30

## Context

We are starting a document de-identification pilot. Step 1 needs a Docker-first foundation
and a fully working upload page. The product must look modern, grow into richer interactive views (document list, side-by-side extracted/anonymized text), and align with the project's code standards (type safety,
linting, tests, container hardening). The de-identification domain (text extraction, PII
detection) is Python-centric.

## Decision

- **Backend:** Python 3.12 + FastAPI + Pydantic, dependency-managed with `uv`. Rationale:
  best fit for the upcoming NLP/PII pipeline; type-safe; auto-generated OpenAPI.
- **Frontend:** React 18 + Vite + TypeScript (strict) + Tailwind CSS. Rationale: matches the
  modern SPA look of the screenshots and scales cleanly to Screens 2 and 3.
- **Topology:** Two containers via Docker Compose. `frontend` (nginx) serves the built SPA
  and reverse-proxies `/api/*` to `backend` (FastAPI). Single external entry point at
  `http://localhost:8080`; the backend port is not published to the host (least exposure).
- **Storage (Step 1):** uploaded files are written to a host-mounted directory
  (`./volumes/uploads`, bind-mounted into the backend container at `/data/uploads`) behind a
  service layer. No database yet.

## Consequences

- Positive: clear layer separation; type-safe both ends; reproducible Docker-first runs;
  minimal external attack surface; a structure that scales to later steps.
- Negative: two build toolchains (Node + Python) and a multi-stage frontend build add some
  complexity compared to a single server-rendered service.
