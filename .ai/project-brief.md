# Project Brief

**privacy-deidentification-pilot** — a pilot for a document de-identification pipeline.

Users upload documents (PDF/DOCX/PNG/JPG); the system will extract text, detect sensitive
data (PII), and return an anonymized version. The product is GDPR-focused ("DSGVO-konform").

Delivery is **Docker-first**: `docker compose up -d` brings up the whole stack locally; the
web app is reachable at `http://localhost:8080`. Nothing is installed on the host.

This repository adopts the operational/AI-collaboration parts of
[ai-project-standard](https://github.com/rubennati/ai-project-standard) (this `.ai/`
workspace, `AGENTS.md`, `CLAUDE.md`, shared quality commands). It is **not** an open-source
project, so open-source governance files are intentionally omitted.
