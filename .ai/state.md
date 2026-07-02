# Current State

> If this file conflicts with the current branch or commits, trust git.

- Current phase: **OCR/Text readable-output foundation**.
- Current objective: advance cumulative OCR/Text L8 with a separate human-readable rendering while
  preserving the canonical text and all offset-bearing consumers.
- Branch policy: feature and documentation PRs target `dev`; `main` is the curated user-stable
  branch. Windows install/update tooling always follows `main`.

## Product snapshot

- Docker Compose runs a React/Vite SPA behind nginx and a private FastAPI backend.
- The product supports upload, document listing/deletion, Audit, OCR/Text, detection-only PII, and
  lineage-safe manual inspection. It does not redact, anonymize, or pseudonymize documents.
- Originals, metadata, and immutable derived artifacts use separate validated storage boundaries.
- OCR/Text routes each PDF page between a usable text layer and the adapter-bound PaddleOCR runtime;
  OCR pages store additive engine-reported page/line confidence metrics on `text_result`, and every
  successful OCR/Text run appends a metrics-only `quality_report` linked to the exact
  original/audit/text artifacts. DOCX extraction includes paragraphs, tables, headers, and footers.
- PII uses Presidio/spaCy behind an adapter, named profiles, AT/DE and domain recognizers, candidate
  validation, and reproducible engine settings.
- The local private benchmark measures routing and PII quality from existing artifacts. Its
  committed test suite uses synthetic data; private corpus data remains under git-ignored volumes.

## Engine maturity snapshot (0–19)

- **OCR/Text: L7 done.** Each successful PDF/image/DOCX OCR/Text run appends an immutable,
  metrics-only `quality_report` containing source mix, audit-quality counts, confidence, coverage,
  and exact original/audit/text lineage. Reruns preserve old artifacts; the benchmark prefers a
  lineage-matching report and falls back for legacy data. Canonical text, routing, and PII input are
  unchanged. L8 readable text is next. Two additive, out-of-order OCR L9 slices exist on top, both
  leaving `text_result.text`
  byte-stable with PII still running only on canonical text:
  - `layout_text_result` — optional field on `text_result`; pypdf layout mode, PDF text-layer pages;
    OCR/DOCX/image → `null`. Display-only; the Review UI can optionally show it as unhighlighted
    plain text, with canonical text remaining the default and the only highlighted/offset-bearing
    view.
  - `pii_input_text` — a second optional field on `text_result`; internal/experimental semantic
    reading-order text (left/right block grouping, row-wise table reconstruction) for PDF
    text-layer pages, built from pypdf text-position data. **Not** the active PII input; no UI.
- **PII/Sensitive-Data: L9 done; L10 partial.** Dev-only human-feedback capture exists; grouping
  (L11), overlap resolution (L12), and binding review (L13) remain open.
- **Review/Human-Feedback: L2 production; L3–L5 dev-only.** Grouping (L6) and a lineage-bound
  `review_result` overlay (L8) remain open.
- **Benchmark/Regression: L8 done; out-of-order L10 OCR confidence/coverage slice delivered.** L9
  per-profile reporting in one run is next.
- **Redaction/De-Identification: L0 by design.** It remains blocked on mature OCR, PII, and review
  foundations.

See [`docs/engine/`](../docs/engine/README.md),
[ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md), and
[ADR-0017](../docs/adr/0017-entity-taxonomy-and-risk-classes.md).

## Dev feedback boundary

- When `ENABLE_DEV_ENGINE_SETTINGS=true`, per-entity feedback is appended locally to
  `volumes/document-data/<document_id>/feedback/pii_feedback.jsonl`.
- New writes must match an entity in the referenced `pii_result` by type, offsets, and recognizer;
  summaries ignore historical lines that do not match that artifact.
- This is a gated analysis side-channel, not a learning system and not the binding review artifact.
- The structured fingerprint excludes raw document/entity text and optional `text_hash` is limited
  to a SHA-256 digest. Comments are short reviewer notes and must not contain copied document text,
  OCR text, or raw PII; the file still belongs inside the protected document-data boundary.

## Governance checkpoint

- Core OCR, NER, redaction, and pseudonymization intelligence comes from established tools behind
  adapters.
- Adapter-bound Presidio pattern recognizers, context rules, candidate validation, domain
  recognizers, and small deterministic heuristics are permitted only when documented, tested,
  benchmarkable, reviewable, and auditable.
- Major architecture/dependency changes, large opaque rule systems, or ad-hoc intelligence require
  human approval before implementation.

## Immediate next steps

The binding OCR/PII sequence, cadence, and next-12-PR list live in
[`docs/engine/ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md)
([ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md)). **Current priority: cumulative
OCR/Text readable text (L8)**, now that confidence capture (L6) and `quality_report` (L7) are
complete.

The OCR L8/L9 text-layer work is contract-first: the output model and invariants are fixed in
[`docs/engine/ocr-layout-text-contract.md`](../docs/engine/ocr-layout-text-contract.md). Four layers
— canonical `best_text_result` (source of truth, offset-stable), an internal detection-optimised
`pii_input_text`, `readable_text`, and `layout_text_result` — tied by a `text_lineage_map`.
`layout_text_result` and `pii_input_text` each have a delivered PDF-text-layer v1 slice (see above);
`readable_text` and `text_lineage_map` remain open. There must be **no two unconnected
source-of-truth texts**: every layer maps back to canonical/source. `pii_input_text` may become the
**active PII detection input** only with a tested `text_lineage_map` (the separation gate) — PII
runs exclusively on canonical text today, regardless of `pii_input_text`'s v1 content. The readable/
layout/PII-input layers are additive and never a standalone PII input.

Feedback integrity hardening completes the planned trust-boundary bugfix without advancing an engine
level. The checkpoint leaves OCR/Text at L7, PII L10 partial, and Redaction L0; the next plan is:

1. Advance OCR/Text to **L8 — human-readable text**, preserving canonical text and offsets.
2. Interleave PII **L11 — entity grouping + occurrences** without changing detection.
3. Complete OCR/Text **L9 — layout-aware text** beyond the already-delivered additive v1 slices.

**Latest checkpoint (OCR L7):** OCR/Text advanced from L6 to L7 and remains sufficiently ahead of
the binding PII/review frontier; no benchmark/feedback signal changed priority. The new artifact has
exact lineage and introduces no routing, canonical-text, PII-input, dependency, or configuration
drift. This is the third planned foundation PR checkpoint; re-reading the implementation plan and
roadmap confirms the next three steps as OCR L8, PII L11, then completion of OCR L9.

**Checkpoint loop:** after every engine PR, record which level changed, confirm OCR/Text is still
sufficiently ahead of PII/Redaction, check for benchmark/feedback-driven re-prioritisation and
config/artifact drift, and update state/docs; after every third PR, re-confirm or adjust the next
three PRs (see the plan's checkpoint loop).

## Dev maintenance

- Safe Docker cleanup targets exist: `make docker-df`, `make docker-prune`,
  `make docker-prune-project`, `make dev-rebuild`. None of them delete volumes, uploads, or
  document data.

## Active constraints

- Docker-first; no host-local application toolchain is required.
- Keep changes focused and `.ai/` files concise.
- Do not read or commit private material under `volumes/`.
- Follow the approval, branch, and PR rules in [`AGENTS.md`](../AGENTS.md).
